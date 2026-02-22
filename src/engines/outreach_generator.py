"""Outreach Generator — personalized messages via Groq (Llama 3.3 70B).

Takes a Lead (with property details) and a business profile, then uses
Groq's free API to write a short, warm, property-specific outreach message.
Think of it as an AI copywriter that knows about the person's home and
tailors the pitch accordingly.

Uses the Groq REST API directly via httpx — no extra SDK needed.
Free tier: 30 requests/minute, no credit card required.

Graceful fallback: if GROQ_API_KEY is not set, all functions return the
leads unchanged — the app still works for property search, just without
the outreach messages.
"""

import json
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

from src.models.lead import Lead

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _get_llm_key() -> Optional[str]:
    """Read the Groq API key from the environment.

    Returns None (instead of raising) so the app can still work
    for property search even without a Groq key configured.
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return None
    return key


def _get_era_description(year: Optional[int]) -> str:
    """Map a construction year to a human-readable architectural era.

    NYC real estate has strong era associations — "pre-war" means classic
    craftsmanship and detail, "mid-century" means solid postwar construction,
    and "modern" means recent luxury builds. These labels help the LLM write
    more authentic outreach.

    Args:
        year: Year the building was constructed, or None.

    Returns:
        Era label like "pre-war" or "modern", or "unknown era" if no year.
    """
    if year is None:
        return "unknown era"
    if year < 1900:
        return "historic"
    if year < 1940:
        return "pre-war"
    if year < 1960:
        return "mid-century"
    if year < 1980:
        return "post-war"
    if year < 2000:
        return "contemporary"
    return "modern"


def _build_outreach_prompt(
    lead: Lead,
    service_description: str,
    ideal_client_description: str,
) -> str:
    """Construct the prompt sent to the LLM for outreach generation.

    Includes all available property details so the LLM can reference
    specific things about the home (year, size, type, neighborhood).

    Args:
        lead: The Lead with property data.
        service_description: What the business does (from the user).
        ideal_client_description: Who the ideal client is (from the user).

    Returns:
        Complete prompt string for the LLM.
    """
    property_details = []

    if lead.estimated_wealth:
        if lead.estimated_wealth >= 1_000_000:
            property_details.append(
                f"Estimated value: ${lead.estimated_wealth / 1_000_000:.1f}M"
            )
        else:
            property_details.append(
                f"Estimated value: ${lead.estimated_wealth:,.0f}"
            )

    if lead.building_type:
        property_details.append(f"Property type: {lead.building_type}")

    if lead.year_built:
        era = _get_era_description(lead.year_built)
        property_details.append(f"Built: {lead.year_built} ({era})")

    if lead.building_area:
        property_details.append(f"Building size: {lead.building_area:,} sq ft")

    if lead.lot_area:
        property_details.append(f"Lot size: {lead.lot_area:,} sq ft")

    if lead.num_floors:
        property_details.append(f"Floors: {lead.num_floors}")

    if lead.address:
        property_details.append(f"Address: {lead.address}")

    if lead.zip_code:
        from src.engines.real_estate import _zip_to_neighborhood
        neighborhood = _zip_to_neighborhood(lead.zip_code)
        property_details.append(f"Neighborhood: {neighborhood}")

    property_block = "\n".join(f"- {d}" for d in property_details) if property_details else "- No detailed property data available"

    owner_name = lead.full_name.strip()
    if not owner_name:
        owner_name = "the homeowner"

    first_name = lead.first_name.strip() or "there"

    return f"""Write a short, personalized outreach message from a luxury service provider to a property owner.

PROPERTY OWNER: {owner_name}
PROPERTY DETAILS:
{property_block}

SERVICE PROVIDER DESCRIPTION:
{service_description}

IDEAL CLIENT PROFILE:
{ideal_client_description}

FORMAT — follow this exact structure:
1. "Hi {first_name}," — then introduce who you are and reference one specific detail about their property (address, year, style, or neighborhood)
2. One sentence connecting your services to their property, ending with a soft, low-pressure close

RULES:
- EXACTLY 2 sentences total (after "Hi {first_name},"). No more.
- Tone: direct, warm, confident — like a friendly neighbor who happens to be an expert
- Reference at least ONE specific property detail (year, type, address, size, or neighborhood)
- Do NOT use cliches like "I noticed", "I came across", or "I couldn't help but"
- Do NOT use "Dear", "To whom it may concern", or formal greetings
- Do NOT add a subject line or sign-off (no "Best regards", no name at the end)
- Write ONLY the message body, starting with "Hi {first_name},"

EXAMPLE (for reference only — do NOT copy this):
Hi John, I'm with [studio name] — we do interior renovations for pre-war homes like your 1920s brownstone on W 10th St. We've helped several West Village homeowners modernize while keeping the original character, and I'd love to share some ideas if you're ever curious."""


PARSE_CRITERIA_DEFAULTS: dict = {
    "neighborhoods": ["West Village", "Tribeca", "Park Slope"],
    "min_value": 2_000_000,
    "residential_only": True,
    "individuals_only": True,
    "include_condos": True,
}


def parse_lead_criteria(user_description: str) -> dict:
    """Ask Groq to extract search parameters from the user's description.

    Think of this as giving your business pitch to a smart assistant who
    figures out which NYC neighborhoods to search, what property values to
    target, and whether to look for houses, condos, or both — all from a
    single paragraph.

    If no GROQ_API_KEY is set or the API call fails, returns sensible
    defaults so the app still works.

    Args:
        user_description: Free-text description of the business and ideal
            customer (e.g. "We are a high-end kitchen remodeling company
            targeting wealthy homeowners in Brooklyn and Manhattan").

    Returns:
        Dict with keys: neighborhoods (list[str]), min_value (int),
        residential_only (bool), individuals_only (bool), include_condos (bool).
    """
    api_key = _get_llm_key()
    if api_key is None:
        logger.info("No GROQ_API_KEY — using default lead criteria")
        return dict(PARSE_CRITERIA_DEFAULTS)

    if not user_description.strip():
        return dict(PARSE_CRITERIA_DEFAULTS)

    from src.engines.real_estate import NEIGHBORHOOD_ZIP_CODES
    neighborhood_names = list(NEIGHBORHOOD_ZIP_CODES.keys())

    prompt = f"""You are a lead-generation assistant for luxury services in NYC.

Given the business description below, pick the best neighborhoods and search settings.

AVAILABLE NEIGHBORHOODS (you MUST only pick from this list):
{json.dumps(neighborhood_names)}

BUSINESS DESCRIPTION:
{user_description}

Return ONLY valid JSON with these fields:
- "neighborhoods": list of neighborhood names from the list above (pick 3-10 that best match)
- "min_value": integer property value threshold in dollars (e.g. 2000000, 5000000)
- "residential_only": true if they want houses/brownstones/townhouses, false if commercial too
- "individuals_only": true to hide LLCs/corporations, false to include them
- "include_condos": true if condo/co-op owners are relevant, false if only houses

JSON only, no explanation:"""

    try:
        response = httpx.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 512,
            },
            timeout=30.0,
        )
        response.raise_for_status()

        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        parsed = json.loads(text)

        # Validate neighborhoods are from the allowed list
        valid_neighborhoods = [
            n for n in parsed.get("neighborhoods", [])
            if n in neighborhood_names
        ]
        if not valid_neighborhoods:
            valid_neighborhoods = PARSE_CRITERIA_DEFAULTS["neighborhoods"]

        return {
            "neighborhoods": valid_neighborhoods,
            "min_value": int(parsed.get("min_value", PARSE_CRITERIA_DEFAULTS["min_value"])),
            "residential_only": bool(parsed.get("residential_only", PARSE_CRITERIA_DEFAULTS["residential_only"])),
            "individuals_only": bool(parsed.get("individuals_only", PARSE_CRITERIA_DEFAULTS["individuals_only"])),
            "include_condos": bool(parsed.get("include_condos", PARSE_CRITERIA_DEFAULTS["include_condos"])),
        }

    except Exception as exc:
        logger.warning("Failed to parse lead criteria via Groq: %s", exc)
        return dict(PARSE_CRITERIA_DEFAULTS)


def generate_outreach_for_lead(
    lead: Lead,
    service_description: str,
    ideal_client_description: str,
) -> Lead:
    """Generate an outreach message for a single lead using Groq.

    Calls the Groq REST API (OpenAI-compatible) with httpx — no SDK needed.

    If no API key is configured or the API call fails, the lead is returned
    unchanged (outreach_draft stays None). This makes the function safe to
    call regardless of configuration.

    Args:
        lead: A Lead object with property details.
        service_description: What the business does.
        ideal_client_description: Who the ideal client is.

    Returns:
        The same Lead, with outreach_draft populated on success.
    """
    api_key = _get_llm_key()
    if api_key is None:
        logger.info("No GROQ_API_KEY set — skipping outreach generation")
        return lead

    prompt = _build_outreach_prompt(lead, service_description, ideal_client_description)

    try:
        response = httpx.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 256,
            },
            timeout=30.0,
        )
        response.raise_for_status()

        data = response.json()
        text = data["choices"][0]["message"]["content"]
        lead.outreach_draft = text.strip()
        logger.info("Generated outreach for %s", lead.full_name)
    except Exception as exc:
        logger.warning("Groq API error for %s: %s", lead.full_name, exc)

    return lead
