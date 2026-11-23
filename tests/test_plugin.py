"""The sync against a fake ING session. Every value is invented."""

import base64
import datetime as dt
import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import ClassVar

import pytest

from ing_fints.errors import BankSyncError, NeedsAuth
from ing_fints.plugin import _sync

TODAY = dt.date(2026, 11, 23)
GIRO, EXTRA, DEPOT, OTHER_DEPOT = "DE12500105170648489890", "DE34500105170000123456", "DE56500105170000777777", "DE78500105170000888888"
PRODUCTS = {
    GIRO: {"product_name": "Girokonto", "currency": "EUR", "depot": False},
    EXTRA: {"product_name": "Extra-Konto", "currency": "EUR", "depot": False},
    DEPOT: {"product_name": "Direkt-Depot", "currency": "EUR", "depot": True},
    OTHER_DEPOT: {"product_name": "Direkt-Depot", "currency": "EUR", "depot": True},
}
POSITION = """:16R:GENL
:16S:GENL
:16R:FIN
:35B:ISIN IE00B4L5Y983
ISHSIII-CORE MSCI WLD DLA
:90B::MRKT//ACTU/EUR140,25
:93B::AGGR//UNIT/10,5
:19A::HOLD//EUR1472,63
:70E::HOLD//1STK
120,123456+EUR
:16S:FIN
-"""
EMPTY_DEPOT = ":16R:GENL\n:16S:GENL\n-"
BACKEND = Path("/var/tmp/securo-dev/securo/backend")


def entry(amount, day=dt.date(2026, 11, 20), purpose="Miete"):
    return {"amount": Decimal(amount), "currency": "EUR", "date": day, "entry_date": day, "applicant_name": "Erika Mustermann", "purpose": purpose}


class FakeSession:
    instances: ClassVar[list] = []

    def __init__(self, login, pin, product_id, saved_state):
        self.args = (login, pin, product_id, saved_state)
        self.read = []
        self.windows = []
        FakeSession.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def accounts(self):
        return [SimpleNamespace(iban=iban) for iban in PRODUCTS]

    def products(self):
        return PRODUCTS

    def booked_balance(self, account):
        return Decimal("100.00") if account.iban == GIRO else Decimal("5000.00")

    def transactions(self, account, start, end):
        self.windows.append((start, end))
        if account.iban == GIRO:
            return [entry("-30.00")], [entry("-20.00"), entry("-5.50")]
        return [entry("10.00")], []

    def depot_statement(self, account):
        self.read.append(account.iban)
        return POSITION if account.iban == DEPOT else EMPTY_DEPOT

    def state(self):
        return b"state"


def context(config=None, **secrets):
    base = {"login": "login", "pin": "pin", "product_id": "product"}
    return SimpleNamespace(config=MappingProxyType(config or {}), secrets=MappingProxyType(base | secrets))


def sync(params=None, ctx=None):
    FakeSession.instances = []
    return _sync(params or {}, ctx or context(), session=FakeSession, today=TODAY)


def accounts_by_name(reply):
    return {a["name"]: a for a in reply["data"]["accounts"]}


def test_girokonto_balance_includes_pending():
    giro = accounts_by_name(sync())["Girokonto …9890"]
    assert giro["balance"] == "74.50"
    assert [t["status"] for t in giro["transactions"]] == ["posted", "pending", "pending"]


def test_savings_keeps_its_booked_balance():
    assert accounts_by_name(sync())["Extra-Konto …3456"]["balance"] == "5000.00"


def test_depots_are_holdings_not_accounts():
    reply = sync()
    assert set(accounts_by_name(reply)) == {"Girokonto …9890", "Extra-Konto …3456"}
    assert [(h["isin"], h["account_name"]) for h in reply["data"]["holdings"]] == [("IE00B4L5Y983", "Direkt-Depot …7777")]


def test_only_selected_depots_are_read():
    reply = sync(ctx=context(account_ibans=f"{GIRO}, {OTHER_DEPOT}"))
    assert FakeSession.instances[0].read == [OTHER_DEPOT]
    assert reply["data"]["holdings"] == []
    assert set(accounts_by_name(reply)) == {"Girokonto …9890"}


def test_no_depot_selected_means_holdings_not_read():
    assert sync(ctx=context(account_ibans=GIRO))["data"]["holdings"] is None


@pytest.mark.parametrize("value", ["no", "nein", "No ", "false", "0"])
def test_holdings_off_returns_none(value):
    reply = sync(ctx=context({"holdings": value}))
    assert reply["data"]["holdings"] is None
    assert FakeSession.instances[0].read == []


@pytest.mark.parametrize("value", ["", "yes", "ja", "Ja", "true", "1"])
def test_holdings_on(value):
    assert sync(ctx=context({"holdings": value}))["data"]["holdings"]


def test_bad_holdings_value_fails():
    with pytest.raises(BankSyncError):
        sync(ctx=context({"holdings": "maybe"}))


def test_window_starts_at_since_or_history_days():
    sync({"since": "2026-11-01"})
    assert FakeSession.instances[0].windows[0] == (dt.date(2026, 11, 1), TODAY)
    sync({"since": "2026-01-01"}, context({"history_days": "30"}))
    assert FakeSession.instances[0].windows[0] == (dt.date(2026, 10, 24), TODAY)
    sync()
    assert FakeSession.instances[0].windows[0] == (TODAY - dt.timedelta(days=85), TODAY)


@pytest.mark.parametrize("days", ["0", "90", "x"])
def test_bad_history_days_fail(days):
    with pytest.raises(BankSyncError):
        sync(ctx=context({"history_days": days}))


def test_selected_iban_missing_fails_without_import():
    with pytest.raises(BankSyncError) as error:
        sync(ctx=context(account_ibans="DE99500105170000000000"))
    assert "DE99" not in str(error.value)


def test_missing_credentials_need_auth():
    with pytest.raises(NeedsAuth):
        _sync({}, SimpleNamespace(config={}, secrets={"login": "x"}), session=FakeSession, today=TODAY)


def test_salt_is_kept_and_reused():
    first = sync()
    second = sync(ctx=context(**first["secrets"]))
    assert first["secrets"]["id_salt"] == second["secrets"]["id_salt"]
    assert first["data"] == second["data"]


def test_saved_state_is_used_only_for_the_same_login():
    reply = sync()
    sync(ctx=context(**reply["secrets"]))
    assert FakeSession.instances[0].args[3] == b"state"
    sync(ctx=context(**(reply["secrets"] | {"login": "another"})))
    assert FakeSession.instances[0].args[3] is None


def test_secrets_returned_hold_no_credentials():
    secrets = sync()["secrets"]
    assert set(secrets) == {"id_salt", "fints_identity", "fints_state"}
    assert base64.b64decode(secrets["fints_state"]) == b"state"
    assert "login" not in json.dumps(secrets) and "pin" not in json.dumps(secrets)


@pytest.mark.skipif(not (BACKEND / ".venv/bin/python").exists(), reason="needs the Securo fork's backend")
def test_reply_passes_securo_contract(tmp_path):
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(sync()["data"]))
    check = "import sys; from app.plugins.contract import Payload; Payload.model_validate_json(open(sys.argv[1]).read())"
    # Securo's settings want a secret key to import; this one only satisfies the import.
    env = os.environ | {"SECRET_KEY": "test-only-not-a-secret"}
    subprocess.run([str(BACKEND / ".venv/bin/python"), "-c", check, str(payload)], cwd=BACKEND, env=env, check=True, capture_output=True, timeout=60)


def test_a_booked_card_payment_keeps_its_pending_id_across_syncs():
    first = sync()
    giro = accounts_by_name(first)["Girokonto …9890"]
    pending_id = next(t["external_id"] for t in giro["transactions"] if t["status"] == "pending" and t["amount"] == "20.00")

    class Booked(FakeSession):
        def transactions(self, account, start, end):
            if account.iban == GIRO:
                return [entry("-30.00"), entry("-20.00", day=dt.date(2026, 11, 22))], [entry("-5.50")]
            return super().transactions(account, start, end)

    FakeSession.instances = []
    second = _sync({"state": first["state"]}, context(**first["secrets"]), session=Booked, today=TODAY)
    giro = accounts_by_name(second)["Girokonto …9890"]
    assert [(t["external_id"] == pending_id, t["status"]) for t in giro["transactions"] if t["amount"] == "20.00"] == [(True, "posted")]
    assert giro["balance"] == "94.50"  # the fake keeps its booked 100.00; only -5.50 is still pending
