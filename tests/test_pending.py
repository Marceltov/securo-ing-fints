"""Carrying a pending entry's ID over to its booked form. Rows as mapping.transaction_rows makes them."""

import datetime as dt

from ing_fints.pending import carry

TODAY = dt.date(2026, 11, 23)


def row(external_id, amount="4.80", day="2026-11-20", payee="BAECKEREI MUSTERMANN", status="posted", kind="debit"):
    return {"external_id": external_id, "amount": amount, "type": kind, "currency": "EUR", "date": day, "payee": payee, "status": status, "description": "x"}


def pending(external_id, **kw):
    return row(external_id, status="pending", payee=kw.pop("payee", "Baeckerei Mustermann Ober"), **kw)


def remembered_from(*rows):
    """The state one sync leaves for the next."""
    _, _, state = carry([], list(rows), {}, TODAY)
    return state


def test_booked_entry_takes_the_id_of_the_pending_one_that_left():
    state = remembered_from(pending("pend-a", day="2026-11-20"))
    booked, still_pending, state = carry([row("tx-1", day="2026-11-22")], [], state, TODAY)
    assert [r["external_id"] for r in booked] == ["pend-a"]
    assert still_pending == []
    assert state["carried"] == {"tx-1": ["pend-a", "2026-11-22"]}


def test_the_carried_id_stays_on_later_syncs():
    state = remembered_from(pending("pend-a"))
    _, _, state = carry([row("tx-1", day="2026-11-22")], [], state, TODAY)
    booked, _, _ = carry([row("tx-1", day="2026-11-22")], [], state, TODAY + dt.timedelta(days=30))
    assert booked[0]["external_id"] == "pend-a"


def test_booked_while_still_listed_as_pending_drops_the_pending_row():
    booked, still_pending, state = carry([row("tx-1", day="2026-11-22")], [pending("pend-a")], remembered_from(pending("pend-a")), TODAY)
    assert [r["external_id"] for r in booked] == ["pend-a"]
    assert still_pending == []
    assert state["pending"] == {}


def test_two_equal_purchases_are_not_guessed():
    state = remembered_from(pending("pend-a"), pending("pend-b"))
    booked, _, _ = carry([row("tx-1", day="2026-11-21"), row("tx-2", day="2026-11-21")], [], state, TODAY)
    assert sorted(r["external_id"] for r in booked) == ["tx-1", "tx-2"]


def test_a_booking_before_the_purchase_is_not_its_booking():
    state = remembered_from(pending("pend-a", day="2026-11-20"))
    booked, _, _ = carry([row("tx-1", day="2026-11-19")], [], state, TODAY)
    assert booked[0]["external_id"] == "tx-1"


def test_amount_and_merchant_must_match():
    state = remembered_from(pending("pend-a"))
    other_amount, _, _ = carry([row("tx-1", amount="4.90", day="2026-11-21")], [], state, TODAY)
    other_merchant, _, _ = carry([row("tx-1", payee="CAFE CENTRAL", day="2026-11-21")], [], state, TODAY)
    assert other_amount[0]["external_id"] == other_merchant[0]["external_id"] == "tx-1"


def test_a_pending_entry_still_listed_and_not_booked_stays():
    booked, still_pending, state = carry([], [pending("pend-a")], {}, TODAY)
    assert (booked, [r["external_id"] for r in still_pending]) == ([], ["pend-a"])
    assert set(state["pending"]) == {"pend-a"}


def test_carried_ids_are_forgotten_after_the_history_window():
    state = {"pending": {}, "carried": {"tx-1": ["pend-a", "2026-07-01"], "tx-2": ["pend-b", "2026-11-01"]}}
    _, _, state = carry([], [], state, TODAY)
    assert state["carried"] == {"tx-2": ["pend-b", "2026-11-01"]}


def test_unreadable_state_is_ignored():
    for state in (None, "x", {"pending": "x", "carried": [1]}, {"pending": {"p": {"amount": 1}}, "carried": {"t": "x"}}):
        booked, _, new_state = carry([row("tx-1")], [], state, TODAY)
        assert booked[0]["external_id"] == "tx-1"
        assert new_state == {"pending": {}, "carried": {}}
