"""The only code that talks to ING: a FinTS 3.0 PIN/TAN session with read calls only.

Every answer python-fints gives is checked for a TAN request (ING wants an approval in its app): that pauses the
connection instead of being taken as data. Every error becomes one of ours, with a fixed message: bank answers can
carry IBANs, names and amounts, so none of their text is passed on, and the original exception is not chained.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from fints.client import FinTS3PinTanClient, NeedRetryResponse, NeedTANResponse
from fints.exceptions import FinTSClientPINError, FinTSClientTemporaryAuthError, FinTSConnectionError, FinTSSCARequiredError
from fints.segments.depot import HKWPD5, HKWPD6
from fints.segments.statement import HKKAZ5, HKKAZ6, HKKAZ7
from fints.utils import mt940_to_array

from ing_fints.errors import BankSyncError, NeedsAuth, RateLimited

ING_BANK_CODE = "50010517"
ING_SERVER = "https://fints.ing.de/fints/"


class _Client(FinTS3PinTanClient):
    """python-fints with the two reads it has no public call for.

    Booked and pending entries must stay apart (python-fints' `get_transactions` joins them), and the depot is
    needed as the raw MT535 text (its own parser drops fields). Both use python-fints internals, which is why
    `fints` is pinned: check these two methods on every upgrade.
    """

    def read_transactions(self, account: Any, start: dt.date, end: dt.date) -> Any:
        with self._get_dialog() as dialog:
            command = self._find_highest_supported_command(HKKAZ5, HKKAZ6, HKKAZ7)
            segments = self._fetch_with_touchdowns(
                dialog,
                lambda point: command(
                    account=command._fields["account"].type.from_sepa_account(account),
                    all_accounts=False,
                    date_start=start,
                    date_end=end,
                    touchdown_point=point,
                ),
                lambda responses: responses,
                "HIKAZ",
            )
        if isinstance(segments, NeedTANResponse):
            return segments
        booked = "".join(s.statement_booked.decode("iso-8859-1") for s in segments if s.statement_booked)
        pending = "".join(s.statement_pending.decode("iso-8859-1") for s in segments if s.statement_pending)
        return mt940_to_array(booked) if booked else [], mt940_to_array(pending) if pending else []

    def read_depot(self, account: Any) -> Any:
        with self._get_dialog() as dialog:
            command = self._find_highest_supported_command(HKWPD5, HKWPD6)
            segments = self._fetch_with_touchdowns(
                dialog,
                lambda point: command(account=command._fields["account"].type.from_sepa_account(account), touchdown_point=point),
                lambda responses: responses,
                "HIWPD",
            )
        if isinstance(segments, NeedTANResponse):
            return segments
        parts = [s.holdings.decode("iso-8859-1") if isinstance(s.holdings, bytes) else str(s.holdings or "") for s in segments]
        return "\n".join(parts)


def _entry(transaction: Any) -> dict:
    """An MT940 entry as a plain dict, the amount as a signed Decimal."""
    data = dict(transaction.data)
    amount = data.get("amount")
    data["amount"] = Decimal(str(getattr(amount, "amount", amount)))
    data["currency"] = getattr(amount, "currency", None) or data.get("currency") or "EUR"
    return data


@contextmanager
def _translated() -> Iterator[None]:
    try:
        yield
    except NeedsAuth, RateLimited, BankSyncError:
        raise
    except FinTSClientPINError:
        raise NeedsAuth("ING refused the login; check the login and PIN (or ING may want a new approval)") from None
    except FinTSClientTemporaryAuthError:
        raise NeedsAuth("ING has locked FinTS access for now (3938); contact ING before trying again") from None
    except FinTSSCARequiredError:
        raise NeedsAuth("ING wants a strong customer authentication (9075), which a sync cannot give") from None
    except FinTSConnectionError, TimeoutError, ConnectionError:
        raise RateLimited("could not reach ING's FinTS server; trying again at the next sync") from None
    except Exception as error:
        raise BankSyncError(f"the FinTS sync failed ({type(error).__name__}); nothing was changed") from None


def _checked[T](value: T) -> T:
    if isinstance(value, NeedTANResponse | NeedRetryResponse):
        raise NeedsAuth("ING wants an approval in its app; the connection pauses until it is renewed")
    return value


class IngSession:
    """One FinTS dialog with ING, as a context manager. Read calls only."""

    def __init__(self, login: str, pin: str, product_id: str, saved_state: bytes | None, factory: Callable[..., Any] = _Client):
        self._factory = factory
        self._kwargs: dict[str, Any] = {
            "bank_identifier": ING_BANK_CODE,
            "user_id": login,
            "pin": pin,
            "server": ING_SERVER,
            "product_id": product_id,
        }
        if saved_state:
            self._kwargs["from_data"] = saved_state
        self._client: Any = None

    def __enter__(self) -> IngSession:
        with _translated():
            self._client = self._factory(**self._kwargs)
            self._client.__enter__()
            _checked(self._client.init_tan_response)
        return self

    def __exit__(self, *exc: object) -> None:
        with _translated():
            self._client.__exit__(*exc)

    def _call[T](self, read: Callable[[], T]) -> T:
        with _translated():
            return _checked(read())

    def accounts(self) -> list[Any]:
        return list(self._call(self._client.get_sepa_accounts) or [])

    def products(self) -> dict[str, dict]:
        """IBAN → product name and currency, as ING names its accounts."""
        info = self._call(self._client.get_information) or {}
        return {
            str(a["iban"]).replace(" ", "").upper(): {"product_name": str(a.get("product_name") or ""), "currency": str(a.get("currency") or "EUR")}
            for a in info.get("accounts", [])
            if isinstance(a, dict) and a.get("iban")
        }

    def booked_balance(self, account: Any) -> Decimal:
        balance = self._call(lambda: self._client.get_balance(account))
        amount = getattr(getattr(balance, "amount", None), "amount", None)
        if amount is None:
            raise BankSyncError("ING sent no balance for an account; nothing was imported")
        return Decimal(str(amount))

    def transactions(self, account: Any, start: dt.date, end: dt.date) -> tuple[list[dict], list[dict]]:
        """Booked and pending entries, apart, each as a plain dict."""
        booked, pending = self._call(lambda: self._client.read_transactions(account, start, end))
        with _translated():
            return [_entry(t) for t in booked], [_entry(t) for t in pending]

    def depot_statement(self, account: Any) -> str:
        return self._call(lambda: self._client.read_depot(account))

    def state(self) -> bytes:
        """The dialog state to reuse next time, without the PIN."""
        with _translated():
            return self._client.deconstruct()
