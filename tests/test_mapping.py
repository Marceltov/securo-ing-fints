"""Accounts and transactions in Securo's contract. Every value is invented."""

import datetime as dt
from decimal import Decimal
from unittest import mock

from ing_fints import mapping
from ing_fints.mapping import account_kind, account_row, digest, transaction_rows
from ing_fints.text import Cleaned

SALT = "11" * 32
TODAY = dt.date(2026, 11, 23)
IBAN = "DE12500105170648489890"


def entry(amount="-4.80", day=dt.date(2026, 11, 20), **extra):
    data = {
        "amount": Decimal(amount),
        "currency": "EUR",
        "date": day,
        "entry_date": day,
        "posting_text": "Lastschrifteinzug",
        "transaction_code": "005",
        "prima_nota": "931000",
        "applicant_name": "VISA BAECKEREI MUSTERMANN",
        "purpose": "NR XXXX 1234 MUSTERSTADT DEKAUFUMSATZ20.11 4.80123456ARN12345678901234567890123",
    }
    return data | extra


def test_digest_is_salted_and_prefixed():
    assert digest(SALT, "ing-", IBAN).startswith("ing-")
    assert len(digest(SALT, "ing-", IBAN)) == 44
    assert digest(SALT, "ing-", IBAN) != digest("22" * 32, "ing-", IBAN)
    assert IBAN not in digest(SALT, "ing-", IBAN)


def test_ids_ignore_cleaned_text():
    before = [row["external_id"] for row in transaction_rows([entry()], [], SALT, "acc", TODAY)]
    with mock.patch.object(mapping, "clean", return_value=Cleaned("someone else", "something else")):
        after = [row["external_id"] for row in transaction_rows([entry()], [], SALT, "acc", TODAY)]
    assert before == after


def test_identical_bookings_get_distinct_stable_ids():
    first = transaction_rows([entry(), entry()], [], SALT, "acc", TODAY)
    again = transaction_rows([entry(), entry()][::-1], [], SALT, "acc", TODAY)
    ids = [row["external_id"] for row in first]
    assert len(set(ids)) == 2
    assert ids == [row["external_id"] for row in again]


def test_ids_differ_per_account():
    assert transaction_rows([entry()], [], SALT, "a", TODAY)[0]["external_id"] != transaction_rows([entry()], [], SALT, "b", TODAY)[0]["external_id"]


def test_pending_rows_are_marked_and_prefixed():
    rows = transaction_rows([entry()], [entry(amount="-12.00")], SALT, "acc", TODAY)
    assert [r["status"] for r in rows] == ["posted", "pending"]
    assert rows[0]["external_id"].startswith("tx-")
    assert rows[1]["external_id"].startswith("pend-")


def test_pending_is_never_dated_in_the_future():
    future = entry(day=dt.date(2026, 11, 22), entry_date=dt.date(2026, 11, 25))
    later_value = entry(day=dt.date(2026, 11, 24), entry_date=dt.date(2026, 11, 26))
    rows = transaction_rows([], [future, later_value], SALT, "acc", TODAY)
    assert [r["date"] for r in rows] == ["2026-11-22", "2026-11-23"]


def test_booked_rows_use_the_booking_day():
    rows = transaction_rows([entry(day=dt.date(2026, 11, 19), entry_date=dt.date(2026, 11, 20))], [], SALT, "acc", TODAY)
    assert rows[0]["date"] == "2026-11-20"


def test_amounts_are_strings_and_signed_by_type():
    debit, credit = transaction_rows([entry("-4.80"), entry("1200.00", applicant_name="Muster GmbH", purpose="Gehalt")], [], SALT, "acc", TODAY)
    assert (debit["amount"], debit["type"]) == ("4.80", "debit")
    assert (credit["amount"], credit["type"]) == ("1200.00", "credit")
    assert all(isinstance(r["amount"], str) for r in (debit, credit))


def test_rows_carry_the_cleaned_text():
    row = transaction_rows([entry()], [], SALT, "acc", TODAY)[0]
    assert (row["payee"], row["description"]) == ("BAECKEREI MUSTERMANN", "BAECKEREI MUSTERMANN · Musterstadt")


def test_row_without_payee_leaves_the_field_out():
    row = transaction_rows([entry(applicant_name="   ", purpose="Abschluss")], [], SALT, "acc", TODAY)[0]
    assert "payee" not in row


def test_account_kind():
    assert account_kind("Girokonto") == "checking"
    assert account_kind("Extra-Konto") == "savings"
    assert account_kind("Direkt-Depot") == "investment"


def test_account_name_shows_last_four():
    row = account_row(IBAN, "Girokonto", "EUR", Decimal("12.30"), SALT, [])
    assert row["name"] == "Girokonto …9890"
    assert row["masked_number"] == "9890"
    assert row["type"] == "checking"
    assert row["balance"] == "12.30"
    assert row["external_id"] == row["stable_external_id"] == digest(SALT, "ing-", IBAN)
    assert (row["institution_name"], row["institution_external_id"]) == ("ING Deutschland", "ing-de")
    assert IBAN not in str(row)
