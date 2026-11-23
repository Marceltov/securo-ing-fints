"""The FinTS session against a fake python-fints client. Every value is invented."""

import datetime as dt
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from fints.client import NeedTANResponse
from fints.exceptions import FinTSClientPINError, FinTSClientTemporaryAuthError, FinTSConnectionError, FinTSDialogError, FinTSSCARequiredError

from ing_fints import client as client_module
from ing_fints.client import IngSession
from ing_fints.errors import BankSyncError, NeedsAuth, RateLimited

SECRET_TEXT = "DE12500105170648489890 Erika Mustermann"
ACCOUNT = SimpleNamespace(iban="DE12500105170648489890")


def tan():
    return NeedTANResponse.__new__(NeedTANResponse)


class FakeClient:
    """Stands in for client._Client; `answers` overrides what a method returns or raises."""

    answers: ClassVar[dict] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.init_tan_response = self.answers.get("init")
        mounted = {}
        self.connection = SimpleNamespace(session=SimpleNamespace(mounted=mounted, mount=mounted.__setitem__))

    def __enter__(self):
        if isinstance(self.answers.get("enter"), Exception):
            raise self.answers["enter"]
        return self

    def __exit__(self, *exc):
        return False

    def _answer(self, name, default):
        value = self.answers.get(name, default)
        if isinstance(value, Exception):
            raise value
        return value

    def get_sepa_accounts(self):
        return self._answer("accounts", [ACCOUNT])

    def get_information(self):
        return self._answer("information", {"accounts": [{"iban": ACCOUNT.iban, "product_name": "Girokonto", "currency": "EUR"}]})

    def get_balance(self, account):
        return self._answer("balance", SimpleNamespace(amount=SimpleNamespace(amount=Decimal("12.30"), currency="EUR")))

    def read_transactions(self, account, start, end):
        return self._answer("transactions", ([], []))

    def read_depot(self, account):
        return self._answer("depot", ":16R:GENL\n:16S:GENL\n-")

    def deconstruct(self):
        return b"state"


def session(**answers):
    FakeClient.answers = answers
    return IngSession("login", "pin", "product", None, factory=FakeClient)


STEPS = {
    "accounts": lambda s: s.accounts(),
    "information": lambda s: s.products(),
    "balance": lambda s: s.booked_balance(ACCOUNT),
    "transactions": lambda s: s.transactions(ACCOUNT, dt.date(2026, 9, 1), dt.date(2026, 11, 23)),
    "depot": lambda s: s.depot_statement(ACCOUNT),
}


def test_reads_through_the_client():
    with session() as s:
        assert s.accounts() == [ACCOUNT]
        assert s.products() == {ACCOUNT.iban: {"product_name": "Girokonto", "currency": "EUR"}}
        assert s.booked_balance(ACCOUNT) == Decimal("12.30")
        assert s.transactions(ACCOUNT, dt.date(2026, 9, 1), dt.date(2026, 11, 23)) == ([], [])
        assert s.depot_statement(ACCOUNT).startswith(":16R:GENL")
        assert s.state() == b"state"


def test_client_gets_ing_and_the_saved_state():
    FakeClient.answers = {}
    with IngSession("login", "pin", "product", b"saved", factory=FakeClient) as s:
        assert s._client.kwargs == {
            "bank_identifier": "50010517",
            "user_id": "login",
            "pin": "pin",
            "server": "https://fints.ing.de/fints/",
            "product_id": "product",
            "from_data": b"saved",
        }


def test_tan_request_at_any_step_pauses():
    with pytest.raises(NeedsAuth), session(init=tan()):
        pass
    for step, call in STEPS.items():
        with pytest.raises(NeedsAuth), session(**{step: tan()}) as s:
            call(s)


@pytest.mark.parametrize(
    ("error", "expected", "named"),
    [
        (FinTSClientPINError(SECRET_TEXT), NeedsAuth, "login"),
        (FinTSClientTemporaryAuthError(SECRET_TEXT), NeedsAuth, "3938"),
        (FinTSSCARequiredError(SECRET_TEXT), NeedsAuth, "9075"),
        (FinTSConnectionError(SECRET_TEXT), RateLimited, "reach"),
        (TimeoutError(SECRET_TEXT), RateLimited, "reach"),
        (FinTSDialogError(SECRET_TEXT), BankSyncError, "FinTSDialogError"),
        (ValueError(SECRET_TEXT), BankSyncError, "ValueError"),
    ],
)
def test_errors_are_mapped_without_bank_text(error, expected, named):
    for answers in ({"enter": error}, {"accounts": error}):
        with pytest.raises(expected) as raised, session(**answers) as s:
            s.accounts()
        message = str(raised.value)
        assert named in message
        assert "DE12" not in message and "Erika" not in message
        assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_missing_balance_fails():
    with pytest.raises(BankSyncError), session(balance=None) as s:
        s.booked_balance(ACCOUNT)


def test_tls_uses_the_system_trust_store():
    with session() as s:
        adapter = s._client.connection.session.mounted["https://"]
    assert isinstance(adapter, client_module.TrustStoreAdapter)


def test_no_write_operations():
    source = Path(client_module.__file__).read_text().lower()
    for word in ("transfer", "send_tan", "hkccs", "hkccm", "hkdse", "hkdme", "simple_sepa"):
        assert word not in source
