"""Tests for pulling a person's name out of a trust owner name."""

import pytest

from src.engines.trust_names import parse_trust_name


@pytest.mark.parametrize(
    ("raw", "full_name", "surname"),
    [
        ("GREG POLLACK LIVING TRUST, DATED MAY 3,  2013", "Greg Pollack", "Pollack"),
        ("POWERS, AS TRUSTEE, CHARLES M", "Charles M Powers", "Powers"),
        ("GLOCKNER, JR., TRUSTEE, DONALD J JR", "Donald J Glockner", "Glockner"),
        ("STANLEY KARP, AS TRUSTEE", "Stanley Karp", "Karp"),
        ("RUSSO, THOMAS A. ASTRUSTEE", "Thomas A Russo", "Russo"),
        ("MICHELLE MIN RONG (TRUSTEE)", "Michelle Min Rong", "Rong"),
        ("REVOCABLE TRUST OF LADA EMELIANOVA DATED  9-30-21", "Lada Emelianova", "Emelianova"),
        ("REVOCABLE TRUST OF PAVAN, GATTANI", "Gattani Pavan", "Pavan"),
        ("THE ROMANA KOLODZIEJCZYK 2018 REVOCABLE  TRUST", "Romana Kolodziejczyk", "Kolodziejczyk"),
        ("PALVI PATEL FAMILY REALTY TRUST", "Palvi Patel", "Patel"),
        ("DONALD DUGGAN JR. AND ELISA LUNDY LIVING  TRUST", "Donald Duggan", "Duggan"),
        ("HENRIETTA CARPENTIERFAMILY TRUST", "Henrietta Carpentier", "Carpentier"),
        ("THE O'BRIEN FAMILY IRREVOCABLE TRUST", None, "O'Brien"),
        ("D & G JOVANOVIC TRUST", None, "Jovanovic"),
        ("JM LINDENBLATT IRREVOCABLE TRUST", None, "Lindenblatt"),
        ("REGINA NOELLE COURTNEY MOERDYK, AS TRUST EE", "Regina Noelle Courtney Moerdyk", "Moerdyk"),
        ("YELENA YUSUPOVA AS JOINT TRUSTEE", "Yelena Yusupova", "Yusupova"),
        ("STERLING NATIONAL BANK AS SUCC TRUST TO  HUD VAL BA", None, None),
        ("216 EAST 78TH STREET TRUST", None, None),
        ("M&L FAMILY TRUST", None, None),
        ("J AND F FAMILY TRUST", None, None),
    ],
)
def test_parse_trust_name(raw: str, full_name: str, surname: str) -> None:
    parsed = parse_trust_name(raw)
    assert parsed.full_name == full_name
    assert parsed.surname == surname
