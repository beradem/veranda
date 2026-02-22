"""SEC EDGAR Form 4 Engine — monitors insider stock sales to find HNW leads.

Form 4 filings are submitted by corporate insiders (CEOs, VPs, board members)
within 2 business days of buying or selling company stock. This engine queries
those filings, filters for large sales, and returns standardized Lead objects.

Someone who just cashed out millions in stock has fresh liquidity — making them
a prime prospect for luxury services.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from edgar import Company, get_filings, set_identity

from src.models.lead import Lead, LeadSource

logger = logging.getLogger(__name__)

# SEC requires a user-agent identity for all EDGAR requests
DEFAULT_IDENTITY = "Veranda App contact@veranda.com"

# Default: only surface sales above this dollar amount
DEFAULT_MIN_SALE_VALUE = 1_000_000.0

# Default lookback window in days
DEFAULT_LOOKBACK_DAYS = 30


def configure_edgar(identity: str = DEFAULT_IDENTITY) -> None:
    """Set the SEC-required user-agent identity.

    The SEC wants to know who is making requests to their API. This is
    like signing the guest book at a library — required but not restrictive.
    """
    set_identity(identity)
    logger.info("EDGAR identity set to: %s", identity)


def _parse_insider_name(raw_name: str) -> tuple[str, str]:
    """Split an insider name into (first_name, last_name).

    EDGAR names often come in 'LAST FIRST' or 'Last First Middle' format.
    We do our best to parse them cleanly.
    """
    parts = raw_name.strip().split()
    if len(parts) == 0:
        return ("Unknown", "Unknown")
    if len(parts) == 1:
        return (parts[0], "")
    # Assume first token is last name if all-caps (EDGAR convention)
    if parts[0].isupper() and len(parts) >= 2:
        return (parts[1].title(), parts[0].title())
    return (parts[0].title(), parts[-1].title())


def _build_discovery_trigger(
    insider_name: str,
    company_name: str,
    ticker: str,
    total_value: float,
    filing_date: date,
) -> str:
    """Create a human-readable discovery trigger string."""
    return (
        f"{insider_name} sold ${total_value:,.0f} in {company_name} "
        f"({ticker}) stock on {filing_date.isoformat()}"
    )


def fetch_insider_sales(
    min_sale_value: float = DEFAULT_MIN_SALE_VALUE,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ticker: Optional[str] = None,
    max_filings: int = 100,
) -> list[Lead]:
    """Query SEC EDGAR for Form 4 insider sales and return qualified leads.

    Args:
        min_sale_value: Minimum total sale value in USD to qualify as a lead.
        lookback_days: How many days back to search from today.
        ticker: If provided, only search filings for this company ticker.
                If None, searches across all companies (broader but slower).
        max_filings: Maximum number of raw filings to process. Controls
                     API load and runtime.

    Returns:
        List of Lead objects for insiders whose sales exceed the threshold.
    """
    configure_edgar()

    start_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    end_date = date.today().isoformat()
    date_range = f"{start_date}:{end_date}"

    logger.info(
        "Searching Form 4 filings | date_range=%s | ticker=%s | min_value=$%s",
        date_range,
        ticker or "ALL",
        f"{min_sale_value:,.0f}",
    )

    # Fetch filings — either for a specific company or globally
    if ticker:
        company = Company(ticker)
        filings = company.get_filings(form="4", filing_date=date_range)
    else:
        filings = get_filings(form="4", filing_date=date_range)

    leads: list[Lead] = []
    errors = 0

    for filing in filings.head(max_filings):
        try:
            lead = _process_single_filing(filing, min_sale_value)
            if lead is not None:
                leads.append(lead)
        except Exception as exc:
            errors += 1
            logger.warning(
                "Failed to parse filing %s: %s", filing.accession_no, exc
            )

    logger.info(
        "EDGAR scan complete | filings_scanned=%d | leads_found=%d | errors=%d",
        min(max_filings, len(filings) if hasattr(filings, '__len__') else max_filings),
        len(leads),
        errors,
    )

    return leads


def _process_single_filing(filing, min_sale_value: float) -> Optional[Lead]:
    """Parse one Form 4 filing and return a Lead if it meets our threshold.

    Returns None if the filing doesn't contain qualifying sales.
    """
    form4 = filing.obj()
    summary = form4.get_ownership_summary()

    # We only care about sales — skip pure purchases, grants, and exercises
    activities = form4.get_transaction_activities()
    sales = [t for t in activities if t.code == "S"]

    if not sales:
        return None

    # Sum up total sale value across all sale transactions in this filing
    total_sale_value = 0.0
    total_shares = 0

    for sale in sales:
        value = sale.value_numeric
        shares = sale.shares_numeric
        if value is not None:
            total_sale_value += float(value)
        if shares is not None:
            total_shares += int(shares)

    if total_sale_value < min_sale_value:
        return None

    # Extract insider identity
    insider_name = summary.insider_name or "Unknown"
    first_name, last_name = _parse_insider_name(insider_name)
    position = summary.position or form4.position or ""
    company_name = summary.issuer_name or ""
    ticker = summary.issuer_ticker or ""
    filing_date = filing.filing_date

    trigger = _build_discovery_trigger(
        insider_name, company_name, ticker, total_sale_value, filing_date
    )

    # Confidence scoring: higher value and officer status = higher confidence
    confidence = _calculate_confidence(total_sale_value, position)

    return Lead(
        first_name=first_name,
        last_name=last_name,
        professional_title=position,
        company=company_name,
        estimated_wealth=total_sale_value,
        discovery_trigger=trigger,
        source=LeadSource.SEC_EDGAR,
        confidence_score=confidence,
        discovered_at=datetime.utcnow(),
    )


def _calculate_confidence(total_sale_value: float, position: str) -> float:
    """Score lead confidence from 0.0 to 1.0 based on available signals.

    Higher sale amounts and C-suite titles get higher scores because they
    indicate both wealth and decision-making authority.
    """
    score = 0.0

    # Sale value tiers
    if total_sale_value >= 10_000_000:
        score += 0.5
    elif total_sale_value >= 5_000_000:
        score += 0.4
    elif total_sale_value >= 1_000_000:
        score += 0.3

    # Position bonus
    position_lower = position.lower()
    if any(title in position_lower for title in ["ceo", "chief executive", "president"]):
        score += 0.3
    elif any(title in position_lower for title in ["cfo", "coo", "cto", "chief"]):
        score += 0.25
    elif any(title in position_lower for title in ["vp", "vice president", "svp", "evp"]):
        score += 0.2
    elif "director" in position_lower:
        score += 0.15
    elif "officer" in position_lower:
        score += 0.1

    # We have verified financial data, so minimum baseline
    score += 0.1

    return min(score, 1.0)
