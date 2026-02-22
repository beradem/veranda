"""Professional Mapping Engine — find contact info for leads.

This engine takes a lead with a name and city (from our Real Estate or SEC
EDGAR engines) and helps you identify them and find their email address.

Think of it as a two-step process:
  1. IDENTIFY (free, no API) — generates Google and LinkedIn search links
     so you can quickly find who this person is, where they work, and their
     company website. You do a quick manual check to vet the lead.
  2. FIND EMAIL (1 Hunter.io credit) — once you know the company domain
     (e.g. "goldmansachs.com"), Hunter.io finds their email address.
     25 free lookups/month on Hunter's free plan.

This approach conserves credits — you only spend them on leads you've
personally vetted and decided are worth contacting.
"""

import logging
import os
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv

from src.models.lead import Lead

load_dotenv()

logger = logging.getLogger(__name__)

# Hunter.io API
HUNTER_API_URL = "https://api.hunter.io/v2"
HUNTER_EMAIL_FINDER_URL = f"{HUNTER_API_URL}/email-finder"
HUNTER_EMAIL_VERIFIER_URL = f"{HUNTER_API_URL}/email-verifier"


def _get_hunter_key() -> str:
    """Read the Hunter.io API key from the environment.

    Raises:
        ValueError: If the key is not set.
    """
    key = os.environ.get("HUNTER_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "HUNTER_API_KEY is not set. Add it to your .env file. "
            "Sign up free at https://hunter.io (25 searches/month)"
        )
    return key


# =========================================================================
# Step 1: FREE search link generation (no API, no credits)
# =========================================================================

def generate_search_links(
    first_name: str,
    last_name: str,
    city: str = "New York",
    address: str = "",
) -> dict[str, str]:
    """Generate Google and LinkedIn search URLs for a lead. FREE, no API.

    These links open in the user's browser so they can quickly research
    who this person is, where they work, and what company domain to use
    for the email lookup.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        city: City for search context (default "New York").
        address: Property address for additional Google context.

    Returns:
        Dict with "google" and "linkedin" URLs ready to open in a browser.
    """
    full_name = f"{first_name} {last_name}".strip()
    google_query = quote_plus(full_name)
    linkedin_query = quote_plus(full_name)

    maps_query = quote_plus(f"{address} {city}".strip()) if address and address.strip() else ""

    return {
        "google": f"https://www.google.com/search?q={google_query}",
        "linkedin": f"https://www.linkedin.com/search/results/people/?keywords={linkedin_query}",
        "maps": f"https://www.google.com/maps/search/?api=1&query={maps_query}" if maps_query else "",
    }


# =========================================================================
# Step 2: Hunter.io email finder (1 credit per lookup)
# =========================================================================

def find_email(
    first_name: str,
    last_name: str,
    domain: str,
) -> dict:
    """Find someone's email address via Hunter.io. COSTS 1 CREDIT.

    Hunter.io looks at a company domain (e.g., "goldmansachs.com") and
    figures out the email pattern used there, then generates the most
    likely email for this person. It also checks if that email is real.

    Only call this when the user clicks "Find Email" — each call uses
    one of your 25 free monthly credits.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        domain: Company website domain (e.g., "goldmansachs.com").

    Returns:
        Dict containing:
        - email: The found email address (or None)
        - confidence: How confident Hunter is (0-100)
        - position: Job title if known
        - linkedin_url: LinkedIn URL if known
        - sources: Number of public sources where this email was found

    Raises:
        ValueError: If domain is empty.
    """
    if not domain or not domain.strip():
        raise ValueError(
            "Company domain is required (e.g., 'goldmansachs.com'). "
            "Use the Google/LinkedIn links to find the person's company first."
        )

    api_key = _get_hunter_key()

    logger.info(
        "Hunter email finder | name=%s %s | domain=%s (1 credit)",
        first_name, last_name, domain,
    )

    response = httpx.get(
        HUNTER_EMAIL_FINDER_URL,
        params={
            "domain": domain.strip(),
            "first_name": first_name,
            "last_name": last_name,
            "api_key": api_key,
        },
        timeout=15.0,
    )
    response.raise_for_status()

    data = response.json().get("data", {})
    return _extract_email_result(data)


def verify_email(email: str) -> dict:
    """Verify if an email address is deliverable. COSTS 0.5 CREDITS.

    Checks if the email actually exists and can receive mail. Useful
    before sending outreach to avoid bounces.

    Args:
        email: Email address to verify.

    Returns:
        Dict with "status" (deliverable/undeliverable/risky/unknown)
        and "score" (0-100).
    """
    api_key = _get_hunter_key()

    logger.info("Hunter email verify | email=%s (0.5 credits)", email)

    response = httpx.get(
        HUNTER_EMAIL_VERIFIER_URL,
        params={"email": email, "api_key": api_key},
        timeout=15.0,
    )
    response.raise_for_status()

    data = response.json().get("data", {})
    return {
        "email": data.get("email", email),
        "status": data.get("status", "unknown"),
        "score": data.get("score", 0),
        "regexp": data.get("regexp", False),
        "smtp_server": data.get("smtp_server", False),
    }


def enrich_lead_with_email(lead: Lead, email: str) -> Lead:
    """Update a Lead with a discovered email address.

    Args:
        lead: The Lead to update.
        email: The email address found via Hunter.io.

    Returns:
        Updated Lead with email populated.
    """
    if email:
        lead.email = email
    return lead


def _extract_email_result(data: dict) -> dict:
    """Pull the fields we care about from a Hunter email finder result."""
    return {
        "email": data.get("email"),
        "confidence": data.get("confidence", 0),
        "position": data.get("position", ""),
        "linkedin_url": data.get("linkedin", ""),
        "first_name": data.get("first_name", ""),
        "last_name": data.get("last_name", ""),
        "sources": len(data.get("sources", [])),
    }
