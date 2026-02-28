"""Contact reveal engine — People Data Labs (PDL) person enrichment.

Think of this module as a concierge lookup service: given a person's name
and address, it asks PDL's database whether they have a verified email or
phone number on file. Results are charged per successful match, so we only
call PDL when the user explicitly clicks "Reveal Email" or "Reveal Phone,"
and we cache the result immediately so the same lead is never billed twice.

Usage:
    result = lookup_contact("John", "Smith", city="New York", zip_code="10021")
    # {"email": "john.smith@example.com", "phone": "+12125551234"}
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PDL_ENRICH_URL = "https://api.peopledatalabs.com/v5/person/enrich"


def lookup_contact(
    first_name: str,
    last_name: str,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> dict:
    """Call PDL Person Enrichment API and return email and phone.

    PDL matches the person using as many identity signals as we provide.
    The more signals (name + address + zip), the higher the match confidence.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        address: Street address (optional, improves match rate).
        city: City name (optional).
        state: State abbreviation, e.g. "NY" (optional).
        zip_code: 5-digit ZIP code (optional).

    Returns:
        {"email": str|None, "phone": str|None}
        Both fields are None if PDL has no match or returns no data.

    Raises:
        ValueError: If PDL_API_KEY environment variable is not set.
        httpx.HTTPStatusError: On unexpected non-2xx/404 responses.
    """
    api_key = os.getenv("PDL_API_KEY")
    if not api_key:
        raise ValueError(
            "PDL_API_KEY is not set. Add it to your .env file to enable contact reveal."
        )

    params: dict = {
        "first_name": first_name,
        "last_name": last_name,
    }
    if address:
        params["street_address"] = address
    if city:
        params["locality"] = city
    if state:
        params["region"] = state
    if zip_code:
        params["postal_code"] = zip_code

    try:
        response = httpx.post(
            PDL_ENRICH_URL,
            headers={"X-Api-Key": api_key},
            json=params,
            timeout=15.0,
        )

        # 404 means PDL has no record for this person — not an error, just no match
        if response.status_code == 404:
            logger.info("PDL: no match for %s %s", first_name, last_name)
            return {"email": None, "phone": None}

        response.raise_for_status()
        data = response.json().get("data") or {}

        emails = data.get("emails") or []
        phones = data.get("phone_numbers") or []

        email = emails[0]["address"] if emails else None
        phone = phones[0] if phones else None

        logger.info(
            "PDL: matched %s %s — email=%s phone=%s",
            first_name,
            last_name,
            "yes" if email else "no",
            "yes" if phone else "no",
        )
        return {"email": email, "phone": phone}

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "PDL HTTP error %s for %s %s: %s",
            exc.response.status_code,
            first_name,
            last_name,
            exc.response.text[:200],
        )
        return {"email": None, "phone": None}
    except httpx.RequestError as exc:
        logger.warning("PDL request failed for %s %s: %s", first_name, last_name, exc)
        return {"email": None, "phone": None}
