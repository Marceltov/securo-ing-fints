"""Direkt-Depot positions from ING's MT535 statement.

One statement per depot. Each position is a `:16R:FIN` … `:16S:FIN` section; a depot without positions sends the
general section only. A position missing its ISIN, units, price or value fails the whole statement: positions are
never guessed, and an incomplete answer must not replace what Securo already holds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ing_fints.errors import BankSyncError
from ing_fints.mapping import digest

CENT = Decimal("0.01")

_ISIN = re.compile(r"^:35B:ISIN ([A-Z]{2}[A-Z0-9]{9}\d)$")
_PRICE = re.compile(r"^:90B::MRKT//ACTU/([A-Z]{3})(\d+,\d*)$")
_UNITS = re.compile(r"^:93B::AGGR//UNIT/(N?)(\d+,\d*)$")
_VALUE = re.compile(r"^:19A::HOLD//(N?)([A-Z]{3})(\d+,\d*)$")
_BUY_IN_TAG = ":70E::HOLD//"
_BUY_IN = re.compile(r"^(\d+,\d*)\+([A-Z]{3})")


@dataclass(frozen=True)
class Position:
    isin: str
    name: str
    quantity: Decimal
    price: Decimal
    value: Decimal
    currency: str
    buy_in: Decimal | None


def _number(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def _sections(lines: list[str]) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line == ":16R:FIN":
            if current is not None:
                raise BankSyncError("ING sent an unreadable depot statement; holdings were not changed")
            current = []
        elif line == ":16S:FIN":
            if current is None:
                raise BankSyncError("ING sent an unreadable depot statement; holdings were not changed")
            sections.append(current)
            current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        raise BankSyncError("ING sent an unreadable depot statement; holdings were not changed")
    return sections


def _name(section: list[str], start: int) -> str:
    parts = []
    for line in section[start + 1 :]:
        if line.startswith(":"):
            break
        if not re.match(r"^/[A-Z]{2}/", line):
            parts.append(line)
    return " ".join(parts).strip()


def _position(section: list[str]) -> Position:
    isin = name = currency = None
    quantity = price = value = buy_in = None
    for index, line in enumerate(section):
        if match := _ISIN.match(line):
            isin, name = match[1], _name(section, index)
        elif match := _PRICE.match(line):
            price = _number(match[2])
        elif match := _UNITS.match(line):
            if match[1]:
                raise BankSyncError("ING reported a negative depot position; holdings were not changed")
            quantity = _number(match[2])
        elif match := _VALUE.match(line):
            if match[1]:
                raise BankSyncError("ING reported a negative depot value; holdings were not changed")
            currency, value = match[2], _number(match[3])
        elif line.startswith(_BUY_IN_TAG) and index + 1 < len(section) and (match := _BUY_IN.match(section[index + 1])):
            buy_in = _number(match[1])
    if not (isin and name and currency) or quantity is None or price is None or value is None:
        raise BankSyncError("ING sent an incomplete depot position; holdings were not changed")
    return Position(isin=isin, name=name, quantity=quantity, price=price, value=value, currency=currency, buy_in=buy_in)


def parse_mt535(text: str) -> list[Position]:
    """Every position of one depot statement; `[]` for a depot without positions."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [_position(section) for section in _sections(lines)]


def holding_rows(positions: list[Position], depot_iban: str, product_name: str, salt: str) -> list[dict]:
    account_id = digest(salt, "ing-", depot_iban)
    rows = []
    for p in positions:
        row = {
            "external_id": digest(salt, "hold-", depot_iban, p.isin),
            "name": p.name[:255],
            "type": "etf" if re.search(r"\b(ETF|UCITS)\b", p.name) else "investment",
            "currency": p.currency,
            "quantity": format(p.quantity, "f"),
            "unit_price": format(p.price, "f"),
            "current_value": format(p.value, "f"),
            "isin": p.isin,
            "account_external_id": account_id,
            "account_name": f"{product_name} …{depot_iban[-4:]}",
        }
        if p.buy_in is not None:
            row["purchase_price"] = format((p.quantity * p.buy_in).quantize(CENT, rounding=ROUND_HALF_UP), "f")
        rows.append(row)
    return rows
