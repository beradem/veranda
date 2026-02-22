"""FEC Campaign Finance Engine — surfaces HNW donors from federal contribution records.

The Federal Election Commission (FEC) requires that any individual who donates
$200 or more to a federal campaign disclose their name, employer, occupation,
city, and state. This is entirely public and accessible via the FEC's free API.

Why this matters for Veranda: Someone who writes a $25,000 check to a Senate
campaign has already proven two things — they have disposable wealth, and they
are willing to spend it on things they believe in. That's a prime prospect for
a luxury service firm.

API docs: https://api.open.fec.gov/developers/
No authentication required for the DEMO_KEY tier (60 req/hr).
Set FEC_API_KEY in .env for higher rate limits (1,000 req/hr).
"""

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from src.models.lead import Lead, LeadSource

logger = logging.getLogger(__name__)

FEC_API_BASE = "https://api.open.fec.gov/v1"

# FEC provides a public demo key — works out of the box, lower rate limit.
# Set FEC_API_KEY in .env to get 1,000 requests/hour instead of 60.
DEMO_KEY = "DEMO_KEY"

# Minimum donation to qualify as an HNW signal.
# $2,500 is the individual limit per primary election — a max donor is serious.
DEFAULT_MIN_DONATION = 2_500.0

# FEC data is typically 30–60 days behind. Use a wider lookback window.
DEFAULT_LOOKBACK_DAYS = 180

# Maximum results per API page (FEC max is 100)
MAX_PER_PAGE = 100


def _get_api_key() -> str:
    """Return the FEC API key from the environment, falling back to DEMO_KEY."""
    return os.getenv("FEC_API_KEY", DEMO_KEY)


def _parse_fec_name(raw_name: str) -> tuple[str, str]:
    """Split an FEC contributor name into (first_name, last_name).

    FEC names are formatted as "LAST, FIRST MIDDLE" or "LAST, FIRST".
    Example: "SMITH, JOHN MICHAEL" → ("John", "Smith")
    """
    if not raw_name or not raw_name.strip():
        return ("Unknown", "Unknown")

    if "," in raw_name:
        parts = raw_name.split(",", 1)
        last = parts[0].strip().title()
        first_part = parts[1].strip().split()[0].title() if parts[1].strip() else ""
        return (first_part or "Unknown", last)

    # Fallback: space-separated
    parts = raw_name.strip().split()
    if len(parts) == 1:
        return (parts[0].title(), "")
    return (parts[0].title(), parts[-1].title())


def _build_discovery_trigger(
    donor_name: str,
    amount: float,
    employer: str,
    occupation: str,
    contribution_date: str,
) -> str:
    """Create a human-readable discovery trigger string."""
    parts = [f"{donor_name} donated ${amount:,.0f} to a federal campaign on {contribution_date}"]
    if occupation:
        parts.append(f"Occupation: {occupation}")
    if employer:
        parts.append(f"Employer: {employer}")
    return " · ".join(parts)


def _calculate_confidence(amount: float, occupation: str, employer: str) -> float:
    """Score lead confidence from 0.0 to 1.0.

    Larger donations and high-status occupations (executive, partner, owner)
    are stronger HNW signals. We also give a small baseline since the FEC
    record itself is verified, public data.
    """
    score = 0.0

    # Donation amount tiers
    if amount >= 50_000:
        score += 0.5
    elif amount >= 10_000:
        score += 0.4
    elif amount >= 5_000:
        score += 0.3
    elif amount >= 2_500:
        score += 0.2

    # Occupation bonus
    occ_lower = occupation.lower()
    if any(t in occ_lower for t in ["ceo", "chief executive", "president", "chairman"]):
        score += 0.3
    elif any(t in occ_lower for t in ["cfo", "coo", "cto", "chief", "managing partner"]):
        score += 0.25
    elif any(t in occ_lower for t in ["partner", "principal", "founder", "owner"]):
        score += 0.2
    elif any(t in occ_lower for t in ["vice president", "vp ", "director", "executive"]):
        score += 0.15
    elif any(t in occ_lower for t in ["attorney", "physician", "surgeon", "doctor"]):
        score += 0.15

    # Verified public record baseline
    score += 0.1

    return min(score, 1.0)


def fetch_fec_donors(
    min_donation: float = DEFAULT_MIN_DONATION,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    state: Optional[str] = None,
    max_results: int = 100,
) -> list[Lead]:
    """Query the FEC API for large individual campaign donations and return leads.

    Args:
        min_donation: Minimum contribution amount in USD to qualify as a lead.
        lookback_days: How far back to search from today.
        state: Two-letter state code to restrict results (e.g. "NY", "CA").
               If None, searches nationally.
        max_results: Maximum number of donor records to return.

    Returns:
        List of Lead objects for donors meeting the minimum threshold.
    """
    api_key = _get_api_key()
    min_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    max_date = date.today().isoformat()

    logger.info(
        "Fetching FEC donors | min_donation=$%s | date_range=%s:%s | state=%s",
        f"{min_donation:,.0f}",
        min_date,
        max_date,
        state or "ALL",
    )

    params: dict = {
        "api_key": api_key,
        "min_amount": min_donation,
        "min_date": min_date,
        "max_date": max_date,
        "is_individual": "true",
        "sort": "-contribution_receipt_amount",
        "per_page": min(max_results, MAX_PER_PAGE),
    }
    if state:
        params["contributor_state"] = state.upper()

    try:
        response = httpx.get(
            f"{FEC_API_BASE}/schedules/schedule_a/",
            params=params,
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("FEC API HTTP error: %s", exc)
        return []
    except httpx.RequestError as exc:
        logger.error("FEC API request failed: %s", exc)
        return []

    data = response.json()
    results = data.get("results", [])

    logger.info("FEC API returned %d raw records", len(results))

    leads: list[Lead] = []
    errors = 0

    for record in results[:max_results]:
        try:
            lead = _process_single_record(record)
            if lead is not None:
                leads.append(lead)
        except Exception as exc:
            errors += 1
            logger.warning("Failed to parse FEC record: %s | %s", record.get("contributor_name"), exc)

    logger.info(
        "FEC scan complete | records_processed=%d | leads_found=%d | errors=%d",
        len(results),
        len(leads),
        errors,
    )

    return leads


def _process_single_record(record: dict) -> Optional[Lead]:
    """Parse one FEC Schedule A record and return a Lead.

    Returns None if the record lacks enough data to be useful.
    """
    raw_name = record.get("contributor_name", "")
    amount = record.get("contribution_receipt_amount")
    contribution_date = record.get("contribution_receipt_date", "")
    city = record.get("contributor_city", "")
    state = record.get("contributor_state", "")
    zip_code = record.get("contributor_zip", "")
    employer = (record.get("contributor_employer") or "").strip()
    occupation = (record.get("contributor_occupation") or "").strip()

    # Skip records with no name or no dollar amount
    if not raw_name.strip() or amount is None:
        return None

    amount = float(amount)
    first_name, last_name = _parse_fec_name(raw_name)

    trigger = _build_discovery_trigger(
        donor_name=raw_name.title(),
        amount=amount,
        employer=employer,
        occupation=occupation,
        contribution_date=contribution_date,
    )

    confidence = _calculate_confidence(amount, occupation, employer)

    return Lead(
        first_name=first_name,
        last_name=last_name,
        city=city.title() if city else None,
        state=state.upper() if state else None,
        zip_code=zip_code[:5] if zip_code else None,
        professional_title=occupation or None,
        company=employer or None,
        estimated_wealth=amount,
        discovery_trigger=trigger,
        source=LeadSource.FEC_CAMPAIGN_FINANCE,
        confidence_score=confidence,
        discovered_at=datetime.utcnow(),
    )
