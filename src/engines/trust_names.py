"""Trust name parser — pull the human name out of a trust's owner name.

Unlike LLCs, most trusts are named after the person who created them, so the
owner's name is usually sitting right in the PLUTO owner field:

    "GREG POLLACK LIVING TRUST, DATED MAY 3, 2013"  -> Greg Pollack
    "POWERS, AS TRUSTEE, CHARLES M"                  -> Charles M Powers
    "REVOCABLE TRUST OF LADA EMELIANOVA DATED 9-30-21" -> Lada Emelianova
    "THE O'BRIEN FAMILY IRREVOCABLE TRUST"           -> surname only: O'Brien
    "216 EAST 78TH STREET TRUST"                      -> no name

When only a family surname is available, the resolver tries to complete it from
permits/registrations at the same address.
"""

import re
from dataclasses import dataclass
from typing import Optional

# Words that describe the trust rather than name a person. Everything from the
# first of these onward is dropped.
_TRUST_DESCRIPTORS = (
    r"REVOCABLE|IRREVOCABLE|IRREV|LIVING|FAMILY|RESIDENCE|RESIDENTIAL|QUALIFIED|"
    r"PERSONAL|PROTECTIVE|REALTY|RESTATED|GIFT|MARITAL|INDENTURE|SUPPLEMENTAL|"
    r"GRANTOR|DYNASTY|CHILDRENS|CHILDREN'S|DESCENDANTS|LEGACY|HOUSE|HOME|"
    r"PROPERTY|NOMINEE|LAND|QPRT|GST|JOINT|CREDIT|BYPASS|EXEMPTION|SURVIVORS|"
    r"ASSET|ESTATE|MANAGEMENT|INVESTMENT|TRUST"
)

# Trailing clauses like "DATED MAY 3, 2013", "DTD 02/24/2025", "U/A 7-20-17"
_DATE_CLAUSE = re.compile(r",?\s*\b(DATED|DTD|UAD|U/A|UA|U/T/A|UTA|U/D/T|UDT)\b.*$")
_TRAILING_YEAR = re.compile(r"\s*-?\s*\b(19|20)\d{2}\b\s*$")
# Also catches the typo "ASTRUSTEE" (no space) that appears in PLUTO
_TRUSTEE_TOKEN = re.compile(r",?\s*\(?\b(?:AS\s*)?(?:JOINT\s+)?(?:CO-?\s?)?(?:SUCCESSOR\s+)?TRUSTEES?\b\)?,?")
_SUFFIX = re.compile(r"\b(JR|SR|II|III|IV|MD|DR|ESQ)\b\.?")
_NOT_A_NAME = re.compile(r"\d|&|\bAND\b|\bSTREET\b|\bST\b|\bAVE\b|\bAVENUE\b|\bPLACE\b|\bTHE\b|\bOF\b|\bNYC\b")
_NAME_TOKEN = re.compile(r"^[A-Z][A-Z'\-]*\.?$")
# Leftover words that mean the parse went wrong — better no name than a wrong one
_LEFTOVER_WORDS = re.compile(r"\b(AS|TRUSTEES?|TRUST|JOINT|BANK|NATIONAL|SUCC|SUCCESSOR|EXECUTORS?|ESTATE|OF)\b")


@dataclass
class TrustName:
    """A person name extracted from a trust owner field."""

    full_name: Optional[str]
    surname: Optional[str]


def _tidy(text: str) -> str:
    """Collapse whitespace and stray punctuation."""
    return re.sub(r"\s+", " ", text).strip(" ,.-()")


def _title(text: str) -> str:
    """Title-case a name, keeping O'Brien / Dayton-Johnson readable."""
    return " ".join(
        "-".join(p.capitalize() for p in word.split("-")) for word in text.lower().split()
    ).replace("O'b", "O'B")


def _as_person(tokens_text: str) -> TrustName:
    """Turn a cleaned name fragment into a full name, surname-only, or nothing."""
    text = _tidy(_SUFFIX.sub(" ", tokens_text))
    if _LEFTOVER_WORDS.search(text):
        return TrustName(None, None)
    if not text or _NOT_A_NAME.search(text):
        # "D & G JOVANOVIC" still tells us the family surname
        surname_match = re.search(r"&\s*[A-Z]\.?\s+([A-Z][A-Z'\-]+)$", text)
        return TrustName(None, _title(surname_match.group(1)) if surname_match else None)

    tokens = text.split()
    if not all(_NAME_TOKEN.match(t) for t in tokens):
        return TrustName(None, None)
    if len(tokens) == 1:
        return TrustName(None, _title(tokens[0]) if len(tokens[0]) > 2 else None)
    # "JM LINDENBLATT" / "BT" — initials instead of a first name
    first = tokens[0].rstrip(".")
    if len(first) <= 2 and not re.search(r"[AEIOUY]", first):
        return TrustName(None, _title(tokens[-1]))
    return TrustName(_title(" ".join(tokens)), _title(tokens[-1]))


def _flip_if_last_first(fragment: str) -> str:
    """'PAVAN, GATTANI' (LAST, FIRST) -> 'GATTANI PAVAN'."""
    if "," in fragment:
        last, _, first = fragment.partition(",")
        return f"{first.strip()} {last.strip()}"
    return fragment


def parse_trust_name(raw_owner: str) -> TrustName:
    """Extract the person behind a trust from its PLUTO owner name.

    Args:
        raw_owner: Owner name as recorded in PLUTO.

    Returns:
        TrustName with a full name, a surname only, or neither.
    """
    text = _tidy(raw_owner.upper())
    text = re.sub(r"\bTRUST\s+EES?\b", "TRUSTEE", text)  # PLUTO line-wrap: "AS TRUST EE"
    text = _DATE_CLAUSE.sub("", text)
    text = _tidy(_TRAILING_YEAR.sub("", text))

    # --- "X, AS TRUSTEE" / "LAST, TRUSTEE, FIRST" forms ---
    if _TRUSTEE_TOKEN.search(text) and "TRUST " not in text + " ":
        before, after = [_tidy(p) for p in _TRUSTEE_TOKEN.split(text, maxsplit=1)]
        before = _tidy(_SUFFIX.sub(" ", before))
        after = _tidy(_SUFFIX.sub(" ", after))
        if after:  # PLUTO's "LAST, TRUSTEE, FIRST M"
            return _as_person(f"{after} {before}")
        return _as_person(_flip_if_last_first(before))  # "RUSSO, THOMAS A. ASTRUSTEE"

    # --- "REVOCABLE TRUST OF LADA EMELIANOVA" ---
    of_match = re.search(r"\bTRUST\s+(?:AGREEMENT\s+)?OF\s+(.+)$", text)
    if of_match:
        return _as_person(_flip_if_last_first(of_match.group(1)))

    # --- "GREG POLLACK LIVING TRUST", "THE O'BRIEN FAMILY TRUST" ---
    text = re.sub(r"^THE\s+", "", text)
    text = re.sub(r"(?<=[A-Z])FAMILY\b", " FAMILY", text)  # "CARPENTIERFAMILY"
    head = re.split(rf"\b(?:{_TRUST_DESCRIPTORS})\b", text, maxsplit=1)[0]
    head = _tidy(re.sub(r"\b(19|20)\d{2}\b", "", head))
    # "DONALD DUGGAN JR. AND ELISA LUNDY" — keep the first named person
    first_person = re.split(r"\s+(?:AND|&)\s+", head, maxsplit=1)[0]
    if first_person != head and len(first_person.split()) >= 2:
        head = first_person
    return _as_person(_flip_if_last_first(head))
