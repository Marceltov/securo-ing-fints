"""ING accounts and their MT940 entries as Securo contract 1 records.

IDs are HMACs over raw bank fields with the connection's salt: stable across syncs, independent of the text
clean-up, and free of IBANs. Entries that are identical in every field (two equal purchases on one day) are told
apart by their order among equals, after sorting, so the order ING lists them in doesn't matter.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
from collections import Counter
from decimal import Decimal
from typing import Literal

from ing_fints.text import clean

AccountKind = Literal["checking", "savings", "investment"]

# The raw fields that identify an entry. Text fields are taken as ING sent them, never cleaned.
BOOKED_ID_FIELDS = (
    "entry_date",
    "date",
    "amount",
    "currency",
    "transaction_code",
    "posting_text",
    "prima_nota",
    "applicant_name",
    "purpose",
    "end_to_end_reference",
    "customer_reference",
)
# A pending entry's booking day can move until it is booked, so it is not part of the ID.
PENDING_ID_FIELDS = ("date", "amount", "currency", "transaction_code", "applicant_name", "purpose")


def digest(salt: str, prefix: str, *values: object) -> str:
    content = "\x1f".join(str(v) for v in values).encode()
    return prefix + hmac.new(bytes.fromhex(salt), content, hashlib.sha256).hexdigest()[:40]


def account_name(product_name: str, iban: str) -> str:
    """How an account or depot is named in Securo: ING's product name and the IBAN's last four digits."""
    return f"{product_name} …{iban[-4:]}"


def account_kind(product_name: str) -> AccountKind:
    name = product_name.casefold()
    if "depot" in name:
        return "investment"
    if "extra" in name or "spar" in name or "tagesgeld" in name:
        return "savings"
    return "checking"


def _fingerprint(account_id: str, data: dict, fields: tuple[str, ...]) -> tuple[str, ...]:
    return (account_id, *(str(data.get(field) or "") for field in fields))


def _rows(entries: list[dict], salt: str, account_id: str, today: dt.date, *, pending: bool) -> list[dict]:
    fields, prefix, status = (PENDING_ID_FIELDS, "pend-", "pending") if pending else (BOOKED_ID_FIELDS, "tx-", "posted")
    keyed = sorted(((_fingerprint(account_id, data, fields), data) for data in entries), key=lambda pair: pair[0])
    seen: Counter[tuple[str, ...]] = Counter()
    rows = []
    for fingerprint, data in keyed:
        occurrence = seen[fingerprint]
        seen[fingerprint] += 1
        amount: Decimal = data["amount"]
        day: dt.date = min(data["date"], today) if pending else data.get("entry_date") or data["date"]
        cleaned = clean(data)
        row = {
            "external_id": digest(salt, prefix, *fingerprint, occurrence),
            "description": cleaned.description,
            "amount": format(abs(amount), "f"),
            "date": day.isoformat(),
            "type": "credit" if amount >= 0 else "debit",
            "currency": data.get("currency") or "EUR",
            "status": status,
        }
        if cleaned.payee:
            row["payee"] = cleaned.payee
        rows.append(row)
    return rows


def transaction_rows(booked: list[dict], pending: list[dict], salt: str, account_id: str, today: dt.date) -> list[dict]:
    """Booked entries, then pending ones; `account_id` is the account's external ID."""
    return _rows(booked, salt, account_id, today, pending=False) + _rows(pending, salt, account_id, today, pending=True)


def account_row(iban: str, product_name: str, currency: str, balance: Decimal, salt: str, transactions: list[dict] | None) -> dict:
    account_id = digest(salt, "ing-", iban)
    return {
        "external_id": account_id,
        "stable_external_id": account_id,
        "name": account_name(product_name, iban),
        "type": account_kind(product_name),
        "balance": format(balance, "f"),
        "currency": currency,
        "masked_number": iban[-4:],
        "institution_name": "ING Deutschland",
        "institution_external_id": "ing-de",
        "transactions": transactions,
    }
