"""A pending entry's ID, carried over to its booked form.

Securo turns a pending row into a booked one when the booking arrives under the same ID. ING's booked entry has a
different ID (its date and text differ), and Securo deletes a pending row that left the feed only once it is a week
old, so without this both would show for days. The plugin remembers each sync's pending entries. When a booked
entry and a pending one (still listed, or gone since the last sync) have the same amount, the same merchant, and
the booking is on or within ten days after the purchase, and neither has another such partner, the booked entry
takes the pending entry's ID. Anything ambiguous (two equal purchases) is left alone: Securo's own expiry handles it.

The state is `{"pending": {id: facts}, "carried": {booked id: [pending id, day]}}`, one per account.
"""

from __future__ import annotations

import datetime as dt
import re

SETTLE_DAYS = 10
# FinTS reaches back 89 days: a booked entry older than that is never sent again.
FORGET_DAYS = 100
MERCHANT_MIN = 5
FACTS = ("amount", "type", "currency", "date", "merchant")

_NOT_ALNUM = re.compile(r"[^0-9a-z]")


def _merchant(payee: object) -> str:
    return _NOT_ALNUM.sub("", str(payee or "").casefold())


def _facts(row: dict) -> dict:
    return {"amount": row["amount"], "type": row["type"], "currency": row["currency"], "date": row["date"], "merchant": _merchant(row.get("payee"))}


def _same_purchase(pending: dict, booked: dict) -> bool:
    if any(pending[key] != booked[key] for key in ("amount", "type", "currency")):
        return False
    short, long = sorted((pending["merchant"], booked["merchant"]), key=len)
    if len(short) < MERCHANT_MIN or not long.startswith(short):
        return False
    purchase, booking = dt.date.fromisoformat(pending["date"]), dt.date.fromisoformat(booked["date"])
    return purchase <= booking <= purchase + dt.timedelta(days=SETTLE_DAYS)


def _valid(state: object) -> tuple[dict[str, dict], dict[str, list[str]]]:
    if not isinstance(state, dict):
        return {}, {}
    pending = state.get("pending")
    carried = state.get("carried")
    pending = {k: v for k, v in (pending.items() if isinstance(pending, dict) else []) if isinstance(v, dict) and all(isinstance(v.get(f), str) for f in FACTS)}
    carried = {
        k: v for k, v in (carried.items() if isinstance(carried, dict) else []) if isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v)
    }
    return pending, carried


def carry(booked: list[dict], pending: list[dict], state: object, today: dt.date) -> tuple[list[dict], list[dict], dict]:
    """The booked rows (some under a pending entry's ID), the pending rows still to show, and the state to keep."""
    remembered, carried = _valid(state)
    forget = (today - dt.timedelta(days=FORGET_DAYS)).isoformat()
    carried = {booked_id: entry for booked_id, entry in carried.items() if entry[1] >= forget}
    taken = {entry[0] for entry in carried.values()}

    booked = [dict(row) for row in booked]
    for row in booked:
        if row["external_id"] in carried:
            row["external_id"] = carried[row["external_id"]][0]

    candidates = {pid: facts for pid, facts in remembered.items() if pid not in taken}
    candidates |= {row["external_id"]: _facts(row) for row in pending}
    open_booked = [row for row in booked if row["external_id"] not in taken]
    partners = {pid: [b for b in open_booked if _same_purchase(facts, _facts(b))] for pid, facts in candidates.items()}
    booked_partners: dict[int, list[str]] = {}
    for pid, rows in partners.items():
        for b in rows:
            booked_partners.setdefault(id(b), []).append(pid)

    settled = set()
    for pid, rows in partners.items():
        if len(rows) == 1 and booked_partners[id(rows[0])] == [pid]:
            b = rows[0]
            carried[b["external_id"]] = [pid, b["date"]]
            b["external_id"] = pid
            settled.add(pid)

    still_pending = [row for row in pending if row["external_id"] not in settled]
    return booked, still_pending, {"pending": {row["external_id"]: _facts(row) for row in still_pending}, "carried": carried}
