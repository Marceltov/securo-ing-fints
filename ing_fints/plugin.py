"""Securo's entrypoint (`ing_fints.plugin:plugin`): one sync of an ING connection.

Reads the settings, opens one FinTS dialog, and asks the other modules for the records: cash accounts with their
booked and pending entries, and the positions of the selected depots. Nothing here talks to the bank or shapes text.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hmac
import secrets as pysecrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from ing_fints.client import IngSession
from ing_fints.depot import holding_rows, parse_mt535
from ing_fints.errors import BankSyncError, NeedsAuth
from ing_fints.mapping import account_row, digest, transaction_rows
from ing_fints.pending import carry

CONTRACT = 1
BERLIN = ZoneInfo("Europe/Berlin")
DEFAULT_HISTORY_DAYS = 85
MAX_HISTORY_DAYS = 89
YES = {"", "yes", "ja", "true", "1"}
NO = {"no", "nein", "false", "0"}


@dataclass(frozen=True)
class Settings:
    login: str
    pin: str
    product_id: str
    ibans: frozenset[str]
    history_days: int
    holdings: bool
    salt: str
    saved_state: bytes | None


def _identity(salt: str, login: str, product_id: str) -> str:
    """Which login the saved FinTS state belongs to, without the login itself (it is short enough to guess)."""
    return hmac.new(bytes.fromhex(salt), f"{login}\x00{product_id}".encode(), "sha256").hexdigest()


def _ibans(value: object) -> frozenset[str]:
    ibans = frozenset("".join(part.split()).upper() for part in str(value or "").replace(";", ",").split(",") if part.strip())
    if any(not (iban.isascii() and iban.isalnum() and 15 <= len(iban) <= 34) for iban in ibans):
        raise BankSyncError("the account selection must be complete IBANs, separated by commas")
    return ibans


def _history_days(value: object) -> int:
    if value in (None, ""):
        return DEFAULT_HISTORY_DAYS
    try:
        days = int(str(value).strip())
    except ValueError:
        days = 0
    if not 1 <= days <= MAX_HISTORY_DAYS:
        raise BankSyncError(f"days of history must be a whole number from 1 to {MAX_HISTORY_DAYS}")
    return days


def _holdings(value: object) -> bool:
    text = str(value or "").strip().casefold()
    if text in YES:
        return True
    if text in NO:
        return False
    raise BankSyncError("read depot positions must be yes or no")


def _salt(secrets: Mapping[str, Any]) -> str:
    salt = str(secrets.get("id_salt") or pysecrets.token_hex(32))
    try:
        if len(bytes.fromhex(salt)) != 32:
            raise ValueError
    except ValueError:
        raise BankSyncError("the saved ID salt is invalid; do not change it, or every ID changes") from None
    return salt


def _saved_state(secrets: Mapping[str, Any], identity: str) -> bytes | None:
    if secrets.get("fints_identity") != identity or not secrets.get("fints_state"):
        return None
    try:
        return base64.b64decode(str(secrets["fints_state"]), validate=True)
    except binascii.Error, ValueError:
        return None


def _settings(context: Any) -> Settings:
    secrets: Mapping[str, Any] = context.secrets or {}
    config: Mapping[str, Any] = context.config or {}
    login, pin, product_id = (str(secrets.get(key) or "").strip() for key in ("login", "pin", "product_id"))
    if not (login and pin and product_id):
        raise NeedsAuth("enter the ING login, the PIN and the FinTS product registration number")
    salt = _salt(secrets)
    return Settings(
        login=login,
        pin=pin,
        product_id=product_id,
        ibans=_ibans(secrets.get("account_ibans")),
        history_days=_history_days(config.get("history_days")),
        holdings=_holdings(config.get("holdings")),
        salt=salt,
        saved_state=_saved_state(secrets, _identity(salt, login, product_id)),
    )


def _start(params: Mapping[str, Any], days: int, today: dt.date) -> dt.date:
    start = today - dt.timedelta(days=days)
    if since := params.get("since"):
        try:
            start = max(start, dt.date.fromisoformat(str(since)[:10]))
        except ValueError:
            raise BankSyncError("Securo asked for an unreadable sync window") from None
    return min(start, today)


def _iban(account: Any) -> str:
    iban = "".join(str(getattr(account, "iban", "") or "").split()).upper()
    if not iban:
        raise BankSyncError("ING listed an account without an IBAN; nothing was imported")
    return iban


def _selected(bank: IngSession, ibans: frozenset[str]) -> list[tuple[str, Any]]:
    listed = [(_iban(account), account) for account in bank.accounts()]
    if not listed:
        raise BankSyncError("ING listed no accounts; nothing was changed")
    if ibans and not ibans <= {iban for iban, _ in listed}:
        raise BankSyncError("an IBAN in the selection is not one ING lists; nothing was imported")
    return [(iban, account) for iban, account in listed if not ibans or iban in ibans]


def _signed(row: dict) -> Decimal:
    return Decimal(row["amount"]) if row["type"] == "credit" else -Decimal(row["amount"])


def _cash_account(
    bank: IngSession, iban: str, account: Any, product: dict, settings: Settings, start: dt.date, today: dt.date, remembered: object
) -> tuple[dict, dict]:
    """The account row, and what to remember about its pending entries for the next sync."""
    account_id = digest(settings.salt, "ing-", iban)
    rows = transaction_rows(*bank.transactions(account, start, today), settings.salt, account_id, today)
    booked, pending, state = carry([r for r in rows if r["status"] == "posted"], [r for r in rows if r["status"] == "pending"], remembered, today)
    # The balance the ING app shows: booked, plus what is still pending (equal to ING's own pending balance, ADR 0002).
    balance = bank.booked_balance(account) + sum((_signed(row) for row in pending), Decimal(0))
    return account_row(iban, product["product_name"], product["currency"], balance, settings.salt, booked + pending), state


def _depot_holdings(bank: IngSession, depots: list[tuple[str, Any, dict]], salt: str) -> list[dict]:
    holdings = []
    for iban, account, product in depots:
        holdings += holding_rows(parse_mt535(bank.depot_statement(account)), iban, product["product_name"], salt)
    return holdings


def _sync(params: Mapping[str, Any], context: Any, *, session: Callable[..., IngSession] = IngSession, today: dt.date | None = None) -> dict:
    settings = _settings(context)
    today = today or dt.datetime.now(BERLIN).date()
    start = _start(params, settings.history_days, today)
    with session(settings.login, settings.pin, settings.product_id, settings.saved_state) as bank:
        products = bank.products()
        cash, depots = [], []
        for iban, account in _selected(bank, settings.ibans):
            product = products.get(iban) or {"product_name": "ING account", "currency": "EUR", "depot": False}
            (depots if product["depot"] else cash).append((iban, account, product))
        previous = params.get("state") if isinstance(params.get("state"), dict) else {}
        remembered = previous.get("accounts") if isinstance(previous.get("accounts"), dict) else {}
        accounts, pending_state = [], {}
        for iban, account, product in cash:
            row, pending_state[digest(settings.salt, "ing-", iban)] = _cash_account(
                bank, iban, account, product, settings, start, today, remembered.get(digest(settings.salt, "ing-", iban))
            )
            accounts.append(row)
        # None means "not read": Securo then keeps the holdings it has. A depot read and found empty gives [].
        holdings = _depot_holdings(bank, depots, settings.salt) if settings.holdings and depots else None
        state = bank.state()
    return {
        "state": {"last_sync_day": today.isoformat(), "accounts": pending_state},
        "secrets": {
            "id_salt": settings.salt,
            "fints_identity": _identity(settings.salt, settings.login, settings.product_id),
            "fints_state": base64.b64encode(state).decode("ascii"),
        },
        "data": {"contract": CONTRACT, "accounts": accounts, "holdings": holdings},
    }


class Plugin:
    def sync(self, params: dict, context: Any) -> dict:
        return _sync(params or {}, context)


plugin = Plugin()
