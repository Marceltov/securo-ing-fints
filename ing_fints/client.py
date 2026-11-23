"""The only code that talks to ING: a FinTS 3.0 PIN/TAN session with read calls only.

Every answer python-fints gives is checked for a TAN request (ING wants an approval in its app): that pauses the
connection instead of being taken as data. Every error becomes one of ours, with a fixed message: bank answers can
carry IBANs, names and amounts, so none of their text is passed on, and the original exception is not chained.

python-fints logs every bank answer with its text. Its loggers are silenced here, so nothing reaches stderr (which
Securo's runner keeps); a session keeps only the four-digit response codes, to name them in an error.
"""

from __future__ import annotations

import datetime as dt
import logging
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
# ING wants a strong customer authentication. python-fints, still in its start-up mode, only closes the dialog on
# it instead of raising FinTSSCARequiredError, so the code is what tells.
SCA_REQUIRED = "9075"

for _name in ("fints", "mt940"):
    _logger = logging.getLogger(_name)
    _logger.addHandler(logging.NullHandler())
    _logger.propagate = False


class _ResponseCodes(logging.Handler):
    """Collects the FinTS response codes python-fints logs, and nothing else of the record."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.codes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        code = getattr(record, "fints_response_code", None)
        if isinstance(code, str) and len(code) == 4 and code.isdigit():
            self.codes.append(code)

    def errors(self) -> str:
        found = sorted({code for code in self.codes if code[0] == "9"})
        return f"; FinTS codes {', '.join(found)}" if found else ""


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
def _translated(codes: _ResponseCodes) -> Iterator[None]:
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
        if SCA_REQUIRED in codes.codes:
            raise NeedsAuth("ING wants a strong customer authentication (9075), which a sync cannot give") from None
        raise BankSyncError(f"the FinTS sync failed ({type(error).__name__}{codes.errors()}); nothing was changed") from None


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
        self._codes = _ResponseCodes()

    def __enter__(self) -> IngSession:
        logging.getLogger("fints").addHandler(self._codes)
        logging.getLogger("fints").setLevel(logging.DEBUG)
        try:
            with _translated(self._codes):
                self._client = self._factory(**self._kwargs)
                self._client.__enter__()
        except BaseException:
            logging.getLogger("fints").removeHandler(self._codes)
            raise
        try:
            self._call(lambda: self._client.init_tan_response)
        except BaseException as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            with _translated(self._codes):
                self._client.__exit__(*exc)
        finally:
            logging.getLogger("fints").removeHandler(self._codes)

    def _call[T](self, read: Callable[[], T]) -> T:
        with _translated(self._codes):
            return _checked(read())

    def accounts(self) -> list[Any]:
        return list(self._call(self._client.get_sepa_accounts) or [])

    def products(self) -> dict[str, dict]:
        """IBAN → product name, currency, and whether it is a depot (it offers holdings and no balance)."""
        info = self._call(self._client.get_information) or {}
        products = {}
        for a in info.get("accounts", []):
            if not (isinstance(a, dict) and a.get("iban")):
                continue
            operations = {getattr(op, "name", str(op)) for op, offered in (a.get("supported_operations") or {}).items() if offered}
            name = str(a.get("product_name") or "")
            products[str(a["iban"]).replace(" ", "").upper()] = {
                "product_name": name,
                "currency": str(a.get("currency") or "EUR"),
                "depot": "depot" in name.casefold() or ("GET_HOLDINGS" in operations and "GET_BALANCE" not in operations),
            }
        return products

    def booked_balance(self, account: Any) -> Decimal:
        balance = self._call(lambda: self._client.get_balance(account))
        amount = getattr(getattr(balance, "amount", None), "amount", None)
        if amount is None:
            raise BankSyncError("ING sent no balance for an account; nothing was imported")
        return Decimal(str(amount))

    def transactions(self, account: Any, start: dt.date, end: dt.date) -> tuple[list[dict], list[dict]]:
        """Booked and pending entries, apart, each as a plain dict."""
        booked, pending = self._call(lambda: self._client.read_transactions(account, start, end))
        with _translated(self._codes):
            return [_entry(t) for t in booked], [_entry(t) for t in pending]

    def depot_statement(self, account: Any) -> str:
        return self._call(lambda: self._client.read_depot(account))

    def state(self) -> bytes:
        """The dialog state to reuse next time, without the PIN."""
        with _translated(self._codes):
            return self._client.deconstruct()
