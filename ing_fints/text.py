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

# A pending card payment's name is the merchant, then the town: padded apart by spaces, or (when the merchant
# fills it) a 25-character merchant column directly followed by the town.
CARD_NAME_WIDTH = 25

_SPACES = re.compile(r"\s+")
_LEADING_ACCOUNT = re.compile(r"^(?:DE\d{20}|[A-Z]{2}\d{12,32}|\d{10})(?=\D)")
_VISA = re.compile(r"^VISA\s+")
# A booked card payment's name: VISA and the merchant, sometimes without a space between them.
_CARD_PAYEE = re.compile(r"^VISA\s*")
_CASH_PAYEE = re.compile(r"^Bargeldauszahlung VISA Card\s*")
_NOISE = re.compile(r"ARN\d+|NR XXXX \d{4}|SEQ\d+|Apple Pay$|Google Pay$")

# The place field holds the town, but for an online merchant often a phone number or a code; a foreign currency adds
# its exchange rate (`KURS 1.0850000`) between the country and the kind.
_CARD_BOOKED = re.compile(r"^NR XXXX \d{4} (?P<town>.+?) ?(?P<country>[A-Z]{2})(?:KURS [\d.,]+)?(?P<kind>KAUFUMSATZ|GUTSCHRIFTSBELEG|BARGELDAUSZAHLUNG)")
_PADDED = re.compile(r"^(?P<merchant>.*?\S)\s{2,}(?P<town>\S.*)$")
_CARD_PENDING = re.compile(r"Datum \d\d\.\d\d\. ?\d{4} Zeit \d\d\.\d\d ?Kaufumsatz VISA Card")
_GIROCARD = re.compile(r"^(?P<text>.*?)\s*\d{4}\.\d\d\.\d\dT\d\d\.\d\d\.\d\d Folgenr\.\s*\d+ Verfalld\.\s*\d{4}\.\d\d$")
_ROUND_UP = re.compile(r"Aus Kauf\s*[\d.,]+?\.?\s*bei\s*(?P<merchant>.+?)\s*(?:SEQ\d+)?$")
_FOREIGN_FEE = re.compile(r"AUSLANDSEINSATZENTGELT")
_GIROCARD_FEE = re.compile(r"MONATLICHES ENTGELT\s*GIROCARD")
_RETURN_PARTS = re.compile(r"\.?\s*(Vorgelegt am|Nicht bezahlt|Fehlende Deckung)")
_SECURITY_TRADE = re.compile(r"WP\.ABRECHNUNG \d+\s*(?P<kind>Kauf|Verkauf) ISIN\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*(?P<name>.+)")
_PAYOUT = re.compile(r"Zins/Dividende\s*ISIN\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)\s*(?P<name>.+)")
_PAYPAL = re.compile(r"^\d{10,}/(?:PP\.\d+\.PP/)?\.\s*(?P<merchant>.*?),?\s*Ihr\s*Einkauf\s*bei")
_PAYPAL_OTHER = re.compile(r"^PP\.\d+\.PP/")
_AMAZON = re.compile(r"^(?P<a>\d{3})\.(?P<b>\d{7})\.(?P<c>\d{7})\s+(?P<shop>AMZN Mktp DE|Amazon\.de)")
_ELV = re.compile(r"^ELV\d")
# A card merchant as the terminal reports it: `NAME*REFERENCE` (Amazon's order codes), a payment provider's short
# prefix (`UZR*NAME`), or PayPal's `PAYPAL *NAME`.
_MERCHANT_REF = re.compile(r"^(?P<name>[^*]+?)\s*\*\s*(?P<ref>[A-Z0-9]*\d[A-Z0-9]*)$")
_MERCHANT_PREFIX = re.compile(r"^[A-Z]{2,4}\*(?P<name>\S.*)$")
_PAYPAL_CARD = re.compile(r"^PAYPAL \*(?P<name>.+)$")
_KNOWN_MERCHANTS = {"AMZN MKTP DE": "Amazon Marketplace", "AMAZON": "Amazon"}
_ONLINE_PLACE = re.compile(r"/|\.com", re.IGNORECASE)


@dataclass(frozen=True)
class Cleaned:
    payee: str | None
    description: str


def _squash(value: object) -> str:
    return _SPACES.sub(" ", str(value or "")).strip()


def _payee(name: str) -> str | None:
    name = _VISA.sub("", _LEADING_ACCOUNT.sub("", name.strip()))
    return _squash(name)[:PAYEE_MAX] or None


def _merchant(text: str) -> tuple[str, str | None]:
    """A card merchant's name without terminal references, and the service it was paid through (PayPal), if any."""
    name = _squash(text)
    if match := _PAYPAL_CARD.match(name):
        return _squash(match["name"]), "PayPal"
    if (match := _MERCHANT_REF.match(name)) or (match := _MERCHANT_PREFIX.match(name)):
        name = match["name"]
    return _KNOWN_MERCHANTS.get(name.upper(), name), None


def _joined(*parts: str | None) -> str:
    return " · ".join(p for p in parts if p)


def _card_booked(name: str, purpose: str) -> Cleaned | None:
    match = _CARD_BOOKED.match(purpose)
    if not match:
        return None
    cash = match["kind"] == "BARGELDAUSZAHLUNG"
    if not (_CASH_PAYEE.match(name) if cash else _CARD_PAYEE.match(name)):
        return None
    payee, via = _merchant((_CASH_PAYEE if cash else _CARD_PAYEE).sub("", name.strip()))
    payee = payee[:PAYEE_MAX] or None
    town = match["town"].title() if not (re.search(r"\d", match["town"]) or _ONLINE_PLACE.search(match["town"])) else None
    country = match["country"] if match["country"] != "DE" else None
    place = ", ".join(p for p in (town, country) if p) or None
    if cash:
        return Cleaned(payee, _joined("Bargeldauszahlung", place))
    description = _joined(payee, place, via)
    return Cleaned(payee, f"Erstattung: {description}" if match["kind"] == "GUTSCHRIFTSBELEG" else description)


def _card_pending(name: str, purpose: str) -> Cleaned | None:
    if not _CARD_PENDING.search(purpose):
        return None
    padded = _PADDED.match(name.strip())
    if padded and len(padded["merchant"]) <= CARD_NAME_WIDTH:
        merchant, town = _squash(padded["merchant"]), _squash(padded["town"])
    else:
        merchant, town = _squash(name[:CARD_NAME_WIDTH]), _squash(name[CARD_NAME_WIDTH:])
    return Cleaned(merchant or None, _joined(merchant or None, town or None))


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
    return Cleaned(_payee(name), f"Aufrundung: {_merchant(match['merchant'])[0]}") if match else None


def _fee(name: str, purpose: str) -> Cleaned | None:
    if _FOREIGN_FEE.search(purpose):
        return Cleaned(_payee(name), "Auslandseinsatzentgelt Visa")
    if _GIROCARD_FEE.search(purpose):
        return Cleaned(_payee(name), "Monatliches Entgelt Girocard")
    return None


def _returned_debit(name: str, purpose: str) -> Cleaned | None:
    if "Vorgelegt am" not in purpose:
        return None
    payee = _payee(name)
    if (amazon := _amazon(name, purpose)) is not None:
        # The order, then what happened to the debit; the order's own reference before it is noise.
        payee, purpose = amazon.payee, amazon.description + purpose[purpose.index("Vorgelegt am") :]
    text = _RETURN_PARTS.sub(lambda m: ", " + m[1][0].lower() + m[1][1:] if m[1] != "Vorgelegt am" else ", vorgelegt am", purpose)
    return Cleaned(payee, _squash(text).rstrip("."))


def _security(name: str, purpose: str) -> Cleaned | None:
    if match := _SECURITY_TRADE.search(purpose):
        return Cleaned(_payee(name), f"{match['kind']} {_squash(match['name'])} ({match['isin']})")
    if match := _PAYOUT.search(purpose):
        return Cleaned(_payee(name), f"Ausschüttung {_squash(match['name'])} ({match['isin']})")
    return None


def _paypal(name: str, purpose: str) -> Cleaned | None:
    if "paypal" not in name.casefold():
        return None
    if match := _PAYPAL.match(purpose):
        merchant = _squash(match["merchant"]).strip(" ,")[:PAYEE_MAX] or None
        return Cleaned(merchant or "PayPal", _joined(merchant, "PayPal"))
    return Cleaned("PayPal", "PayPal") if _PAYPAL_OTHER.match(purpose) else None


def _amazon(name: str, purpose: str) -> Cleaned | None:
    match = _AMAZON.match(purpose)
    if not match or "amazon" not in name.casefold():
        return None
    shop = "Amazon Marketplace" if match["shop"].startswith("AMZN") else "Amazon.de"
    return Cleaned("Amazon", f"{shop} · Bestellung {match['a']}-{match['b']}-{match['c']}")


def _girocard_debit(name: str, purpose: str) -> Cleaned | None:
    if not _ELV.match(purpose):
        return None
    payee = _payee(name)
    return Cleaned(payee, _joined(payee, "girocard"))


_RULES: tuple[Callable[[str, str], Cleaned | None], ...] = (
    _security,
    _fee,
    _returned_debit,
    _card_booked,
    _card_pending,
    _girocard,
    _round_up,
    _paypal,
    _amazon,
    _girocard_debit,
)


def clean(raw: dict) -> Cleaned:
    """Payee and description for one MT940 entry (`raw` is python-fints' transaction data)."""
    name = str(raw.get("applicant_name") or "")
    purpose = _squash(raw.get("purpose"))
    for rule in _RULES:
        if cleaned := rule(name, purpose):
            return Cleaned(cleaned.payee, cleaned.description[:DESCRIPTION_MAX] or FALLBACK)
    payee = _payee(name)
    # A transfer without a purpose: its booking type and who it was with.
    description = _squash(_NOISE.sub(" ", purpose)) or _joined(_squash(raw.get("posting_text")) or None, payee) or FALLBACK
    return Cleaned(payee, description[:DESCRIPTION_MAX])
