"""Readable payees and descriptions from ING's MT940 text.

ING sends the counterparty and the purpose as fixed-width fields joined without separators: an IBAN glued to the
front of a name, card payments as `VISA <merchant>` with the town and a card reference in the purpose, securities
as `WP.ABRECHNUNG <number>Kauf ISIN<isin><name>`. Each shape gets one rule; the first that matches wins, and text no
rule knows is only trimmed. The result is for display only: transaction IDs never depend on it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

PAYEE_MAX = 200
DESCRIPTION_MAX = 500
FALLBACK = "ING"

# A card merchant field is 25 characters of name, then the town.
CARD_NAME_WIDTH = 25

_SPACES = re.compile(r"\s+")
_LEADING_ACCOUNT = re.compile(r"^(?:DE\d{20}|[A-Z]{2}\d{12,32}|\d{10})(?=\D)")
_VISA = re.compile(r"^VISA\s+")
_NOISE = re.compile(r"ARN\d+|NR XXXX \d{4}|SEQ\d+|Apple Pay$|Google Pay$")

_CARD_BOOKED = re.compile(r"^NR XXXX \d{4} (?P<town>.+?) ?(?P<country>[A-Z]{2})(?P<kind>KAUFUMSATZ|GUTSCHRIFTSBELEG)")
_CARD_PENDING = re.compile(r"Datum \d\d\.\d\d\. ?\d{4} Zeit \d\d\.\d\d ?Kaufumsatz VISA Card")
_GIROCARD = re.compile(r"^(?P<text>.*?)\s*\d{4}\.\d\d\.\d\dT\d\d\.\d\d\.\d\d Folgenr\.\s*\d+ Verfalld\.\s*\d{4}\.\d\d$")
_ROUND_UP = re.compile(r"Aus Kauf\s*[\d.,]+?\.?\s*bei\s*(?P<merchant>.+?)\s*(?:SEQ\d+)?$")
_FOREIGN_FEE = re.compile(r"AUSLANDSEINSATZENTGELT")
_GIROCARD_FEE = re.compile(r"MONATLICHES ENTGELT\s*GIROCARD")
_RETURN_PARTS = re.compile(r"\.?\s*(Vorgelegt am|Nicht bezahlt|Fehlende Deckung)")
_SECURITY_TRADE = re.compile(r"WP\.ABRECHNUNG \d+\s*(?P<kind>Kauf|Verkauf) ISIN\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*(?P<name>.+)")
_PAYOUT = re.compile(r"Zins/Dividende\s*ISIN\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*(?P<name>.+)")


@dataclass(frozen=True)
class Cleaned:
    payee: str | None
    description: str


def _squash(value: object) -> str:
    return _SPACES.sub(" ", str(value or "")).strip()


def _payee(name: str) -> str | None:
    name = _VISA.sub("", _LEADING_ACCOUNT.sub("", name.strip()))
    return _squash(name)[:PAYEE_MAX] or None


def _joined(*parts: str | None) -> str:
    return " · ".join(p for p in parts if p)


def _card_booked(name: str, purpose: str) -> Cleaned | None:
    match = _CARD_BOOKED.match(purpose)
    if not match or not _VISA.match(name):
        return None
    payee = _payee(name)
    town = match["town"].title()
    if match["country"] != "DE":
        town = f"{town}, {match['country']}"
    description = _joined(payee, town)
    return Cleaned(payee, f"Erstattung: {description}" if match["kind"] == "GUTSCHRIFTSBELEG" else description)


def _card_pending(name: str, purpose: str) -> Cleaned | None:
    if not _CARD_PENDING.search(purpose):
        return None
    merchant = _squash(name[:CARD_NAME_WIDTH]) or None
    return Cleaned(merchant, _joined(merchant, _squash(name[CARD_NAME_WIDTH:])))


def _girocard(name: str, purpose: str) -> Cleaned | None:
    match = _GIROCARD.match(purpose)
    if not match:
        return None
    parts = [_squash(p) for p in match["text"].split("/")]
    town = parts[-2] if len(parts) >= 3 else None
    payee = _payee(name)
    return Cleaned(payee, _joined(payee or parts[0], town))


def _round_up(name: str, purpose: str) -> Cleaned | None:
    match = _ROUND_UP.search(purpose)
    return Cleaned(_payee(name), f"Aufrundung: {_squash(match['merchant'])}") if match else None


def _fee(name: str, purpose: str) -> Cleaned | None:
    if _FOREIGN_FEE.search(purpose):
        return Cleaned(_payee(name), "Auslandseinsatzentgelt Visa")
    if _GIROCARD_FEE.search(purpose):
        return Cleaned(_payee(name), "Monatliches Entgelt Girocard")
    return None


def _returned_debit(name: str, purpose: str) -> Cleaned | None:
    if "Vorgelegt am" not in purpose:
        return None
    text = _RETURN_PARTS.sub(lambda m: ", " + m[1][0].lower() + m[1][1:] if m[1] != "Vorgelegt am" else ", vorgelegt am", purpose)
    return Cleaned(_payee(name), _squash(text).rstrip("."))


def _security(name: str, purpose: str) -> Cleaned | None:
    if match := _SECURITY_TRADE.search(purpose):
        return Cleaned(_payee(name), f"{match['kind']} {_squash(match['name'])} ({match['isin']})")
    if match := _PAYOUT.search(purpose):
        return Cleaned(_payee(name), f"Ausschüttung {_squash(match['name'])} ({match['isin']})")
    return None


_RULES: tuple[Callable[[str, str], Cleaned | None], ...] = (
    _security,
    _fee,
    _card_booked,
    _card_pending,
    _girocard,
    _round_up,
    _returned_debit,
)


def clean(raw: dict) -> Cleaned:
    """Payee and description for one MT940 entry (`raw` is python-fints' transaction data)."""
    name = str(raw.get("applicant_name") or "")
    purpose = _squash(raw.get("purpose"))
    for rule in _RULES:
        if cleaned := rule(name, purpose):
            return Cleaned(cleaned.payee, cleaned.description[:DESCRIPTION_MAX] or FALLBACK)
    description = _squash(_NOISE.sub(" ", purpose)) or _squash(raw.get("posting_text")) or FALLBACK
    return Cleaned(_payee(name), description[:DESCRIPTION_MAX])
