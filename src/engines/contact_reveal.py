"""Contact reveal engine — AtData Email Append.

Think of this module as a concierge lookup service: given a person's name
and postal address, it asks AtData's database for their email address.
Results are charged $0.06 per successful match, so we only call the API
when the user explicitly clicks "Reveal Email," and we cache the result
immediately so the same lead is never billed twice.

Usage:
    result = lookup_contact("John", "Smith", address="123 Main St",
                            city="New York", state="NY", zip_code="10021")
    # {"email": "john.smith@gmail.com", "phone": None}

Note: AtData returns email only. Phone lookup requires a separate service
(Spokeo is the recommended next integration).
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ATDATA_URL = "https://api.atdata.com/v5/eppend"


def lookup_contact(
    first_name: str,
    last_name: str,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> dict:
    """Call AtData Email Append API and return email address.

    AtData matches the person using name + postal address. All six fields
    are technically required for a billable match — the more complete the
    address, the higher the match confidence.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        address: Street address (e.g. "123 Main St").
        city: City name.
        state: Two-letter state abbreviation, e.g. "NY".
        zip_code: 5-digit ZIP code.

    Returns:
        {"email": str|None, "phone": None}
        email is None if AtData has no match. phone is always None —
        AtData does not return phone numbers.

    Raises:
        ValueError: If ATDATA_API_KEY environment variable is not set.
    """
    api_key = os.getenv("ATDATA_API_KEY")
    if not api_key:
        raise ValueError(
            "ATDATA_API_KEY is not set. Add it to your .env file to enable contact reveal."
        )

    params: dict = {
        "api_key": api_key,
        "first": first_name,
        "last": last_name,
    }
    if address:
        # Strip unit/apt suffix (e.g. "511 Broadway, Unit PHW" → "511 Broadway")
        params["street"] = address.split(",")[0].strip()
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if zip_code:
        params["zip"] = zip_code

    try:
        response = httpx.get(ATDATA_URL, params=params, timeout=15.0)
        response.raise_for_status()

        data = response.json()

        # Empty dict means no match — not an error, just no record found
        if not data:
            logger.info("AtData: no match for %s %s", first_name, last_name)
            return {"email": None, "phone": None}

        if "error_code" in data:
            logger.warning(
                "AtData error for %s %s: %s",
                first_name,
                last_name,
                data.get("error_msg", "unknown error"),
            )
            return {"email": None, "phone": None}

        matches = data.get("email_append") or []
        email = matches[0]["email"] if isinstance(matches, list) and matches else None

        logger.info(
            "AtData: %s for %s %s (match_type=%s)",
            "matched" if email else "no match",
            first_name,
            last_name,
            matches[0].get("email_match_type", "—") if matches else "—",
        )
        return {"email": email, "phone": None}

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "AtData HTTP error %s for %s %s: %s",
            exc.response.status_code,
            first_name,
            last_name,
            exc.response.text[:200],
        )
        return {"email": None, "phone": None}
    except httpx.RequestError as exc:
        logger.warning("AtData request failed for %s %s: %s", first_name, last_name, exc)
        return {"email": None, "phone": None}
