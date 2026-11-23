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
        assert s.products() == {ACCOUNT.iban: {"product_name": "Girokonto", "currency": "EUR", "depot": False}}
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


def test_no_write_operations():
    source = Path(client_module.__file__).read_text().lower()
    for word in ("transfer", "send_tan", "hkccs", "hkccm", "hkdse", "hkdme", "simple_sepa"):
        assert word not in source


def _log_bank_answer(code, text=SECRET_TEXT):
    """What python-fints does for every answer: a log record with the bank's text."""
    import logging

    logging.getLogger("fints.client").warning("Dialog response: %s - %s", code, text, extra={"fints_response_code": code, "fints_response_text": text})


def test_bank_answers_never_reach_stderr(capfd):
    with session() as s:
        _log_bank_answer("3060")
        s.accounts()
    captured = capfd.readouterr()
    assert "Erika" not in captured.err + captured.out


def test_sca_demand_pauses_even_when_python_fints_only_closes_the_dialog():
    class Closed(Exception):
        pass

    def accounts():
        _log_bank_answer("9075")
        raise Closed

    FakeClient.answers = {}
    with pytest.raises(NeedsAuth) as raised, IngSession("login", "pin", "product", None, factory=FakeClient) as s:
        s._client.get_sepa_accounts = accounts
        s.accounts()
    assert "9075" in str(raised.value)


def test_unknown_failure_names_the_codes_only():
    def accounts():
        _log_bank_answer("9050")
        raise RuntimeError(SECRET_TEXT)

    FakeClient.answers = {}
    with pytest.raises(BankSyncError) as raised, IngSession("login", "pin", "product", None, factory=FakeClient) as s:
        s._client.get_sepa_accounts = accounts
        s.accounts()
    assert str(raised.value) == "the FinTS sync failed (RuntimeError; FinTS codes 9050); nothing was changed"


def test_tan_at_start_closes_the_dialog():
    exited = []
    FakeClient.answers = {"init": tan()}
    original = FakeClient.__exit__
    FakeClient.__exit__ = lambda self, *exc: exited.append(True)
    try:
        with pytest.raises(NeedsAuth), IngSession("login", "pin", "product", None, factory=FakeClient):
            pass
    finally:
        FakeClient.__exit__ = original
    assert exited == [True]


def test_a_depot_is_told_by_its_operations():
    from fints.client import FinTSOperations

    info = {
        "accounts": [
            {"iban": ACCOUNT.iban, "product_name": "", "supported_operations": {FinTSOperations.GET_HOLDINGS: True, FinTSOperations.GET_BALANCE: False}}
        ]
    }
    with session(information=info) as s:
        assert s.products()[ACCOUNT.iban]["depot"] is True


MT940_BOOKED = (
    ":20:STARTUMSE\r\n:25:50010517/0648489890\r\n:28C:00000/001\r\n:60F:C261120EUR100,00\r\n"
    ":61:2611201120DR4,80NDDTNONREF\r\n:86:005?00Lastschrifteinzug?20Baeckerei Mustermann?32Baeckerei Mustermann\r\n"
    ":62F:C261120EUR95,20\r\n-"
)
MT942_PENDING = (
    ":20:STARTUMSE\r\n:25:50010517/0648489890\r\n:28C:00000/001\r\n:34F:EUR0,\r\n:13D:2611230800+0100\r\n"
    ":61:2611221125DR12,00NDDTNONREF\r\n:86:005?00Lastschrifteinzug?20Muster Markt?32Muster Markt\r\n:90D:1EUR12,00\r\n:90C:0EUR0,\r\n-"
)


def test_real_client_keeps_booked_and_pending_apart(monkeypatch):
    """client._Client against canned HIKAZ and HIWPD segments: python-fints' internals, without a bank."""
    from contextlib import nullcontext

    real = object.__new__(client_module._Client)
    segment = SimpleNamespace(statement_booked=MT940_BOOKED.encode("iso-8859-1"), statement_pending=MT942_PENDING.encode("iso-8859-1"))
    depot_segment = SimpleNamespace(holdings=b":16R:GENL\r\n:16S:GENL\r\n-")
    monkeypatch.setattr(real, "_get_dialog", lambda: nullcontext(None), raising=False)
    monkeypatch.setattr(real, "_find_highest_supported_command", lambda *classes: classes[-1], raising=False)
    answers = iter([[segment], [depot_segment]])
    monkeypatch.setattr(real, "_fetch_with_touchdowns", lambda dialog, make, handle, kind: handle(next(answers)), raising=False)

    booked, pending = real.read_transactions(ACCOUNT, dt.date(2026, 11, 1), dt.date(2026, 11, 23))
    assert [client_module._entry(t)["amount"] for t in booked] == [Decimal("-4.80")]
    assert [client_module._entry(t)["amount"] for t in pending] == [Decimal("-12.00")]
    assert real.read_depot(ACCOUNT).startswith(":16R:GENL")
