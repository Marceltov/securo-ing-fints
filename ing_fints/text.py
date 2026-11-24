"""Payee, description and notes from ING's MT940 text, the way ING's own app lists an entry.

The app's list shows one name per entry: the counterparty (`HORNBACH`, `Kleingeld Plus - Sparen`,
`PayPal Europe S.a.r.l. et Cie S.C.A`) and, for a pending card payment, the merchant and its town. Everything else
ING sends, the purpose text, is shown only when an entry is opened. So:

- the description is that name, without what ING glues in front of it (an IBAN or account number, `VISA`);
- the payee is the same name, without what a card terminal adds to it (an order reference after `*`, a payment
  provider's prefix), so that one merchant is one payee; for a pending card payment, the merchant alone;
- the notes are the whole purpose text, only whitespace collapsed: Securo searches them and its rules read them.

An entry without a name (a securities trade, the account statement's closing) is described by its own words. The
result is for display only: transaction IDs never depend on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PAYEE_MAX = 200
DESCRIPTION_MAX = 500
NOTES_MAX = 1000
FALLBACK = "ING"

# A pending card payment's name is the merchant, then the town: padded apart by spaces, or (when the merchant
# fills it) a 25-character merchant column directly followed by the town.
CARD_NAME_WIDTH = 25

_SPACES = re.compile(r"\s+")
_LEADING_ACCOUNT = re.compile(r"^(?:DE\d{20}|[A-Z]{2}\d{12,32}|\d{10})(?=\D)")
# A booked card payment's name starts with VISA, sometimes without a space before the merchant.
_CARD = re.compile(r"^VISA\s*(?=\S)")
_CARD_PENDING = re.compile(r"Datum \d\d\.\d\d\. ?\d{4} Zeit \d\d\.\d\d ?Kaufumsatz VISA Card")
_PADDED = re.compile(r"^(?P<merchant>.*?\S)\s{2,}(?P<town>\S.*)$")
# What a card terminal adds to a merchant: `NAME*REFERENCE` (an order code), a provider's prefix (`XYZ*NAME`),
# PayPal's `PAYPAL *NAME`.
_MERCHANT_REF = re.compile(r"^(?P<name>[^*]+?)\s*\*\s*[A-Z0-9]*\d[A-Z0-9]*$")
_MERCHANT_PREFIX = re.compile(r"^(?:[A-Z]{2,4}|PAYPAL) ?\*(?P<name>\S.*)$")
_SECURITY_TRADE = re.compile(r"WP\.ABRECHNUNG \d+\s*(?P<kind>Kauf|Verkauf) ISIN\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*(?P<name>.+)")
_PAYOUT = re.compile(r"Zins/Dividende\s*ISIN\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*(?P<name>.+)")


@dataclass(frozen=True)
class Cleaned:
    payee: str | None
    description: str
    notes: str | None = None


def _squash(value: object) -> str:
    return _SPACES.sub(" ", str(value or "")).strip()


def _name(raw_name: str) -> str:
    """The name the app lists: without a glued IBAN or account number, and without a card payment's VISA."""
    return _squash(_CARD.sub("", _LEADING_ACCOUNT.sub("", raw_name.strip())))


def _payee(name: str) -> str:
    """One merchant, one payee: the name without a terminal's order reference or a payment provider's prefix."""
    if (match := _MERCHANT_REF.match(name)) or (match := _MERCHANT_PREFIX.match(name)):
        return _squash(match["name"])
    return name


def _pending_card(raw_name: str) -> tuple[str, str]:
    """A pending card payment's merchant and town."""
    padded = _PADDED.match(raw_name.strip())
    if padded and len(padded["merchant"]) <= CARD_NAME_WIDTH:
        return _squash(padded["merchant"]), _squash(padded["town"])
    return _squash(raw_name[:CARD_NAME_WIDTH]), _squash(raw_name[CARD_NAME_WIDTH:])


def _without_name(purpose: str, posting_text: str) -> str:
    """Words for an entry ING lists without a counterparty."""
    if match := _SECURITY_TRADE.search(purpose):
        return f"{match['kind']} {_squash(match['name'])} ({match['isin']})"
    if match := _PAYOUT.search(purpose):
        return f"Ausschüttung {_squash(match['name'])} ({match['isin']})"
    return posting_text or FALLBACK


def clean(raw: dict) -> Cleaned:
    """Payee, description and notes for one MT940 entry (`raw` is python-fints' transaction data)."""
    raw_name = str(raw.get("applicant_name") or "")
    purpose = _squash(raw.get("purpose"))
    notes = purpose[:NOTES_MAX] or None
    if _CARD_PENDING.search(purpose):
        merchant, town = _pending_card(raw_name)
        description = " · ".join(part for part in (merchant, town) if part)
        return Cleaned(merchant[:PAYEE_MAX] or None, description[:DESCRIPTION_MAX] or FALLBACK, notes)
    name = _name(raw_name)
    if not name:
        return Cleaned(None, _without_name(purpose, _squash(raw.get("posting_text")))[:DESCRIPTION_MAX], notes)
    return Cleaned(_payee(name)[:PAYEE_MAX], name[:DESCRIPTION_MAX], notes)
