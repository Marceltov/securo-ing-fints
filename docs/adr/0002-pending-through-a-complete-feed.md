---
status: accepted
date: 2026-11-23
decision-makers: Marcel Bruckner
---

# Pending entries, expired through a complete feed

## Context and Problem Statement

ING's app shows the Girokonto balance including pending (vorgemerkte) entries, and lists them. Securo should show the same. A pending card payment later arrives booked, with a different date and text and no reference shared with its pending form, so matching the two by content is guesswork (two equal purchases on one day are two purchases).

## Considered Options

- Booked entries only, booked balance.
- Pending entries matched to their booked form by amount, date and text.
- Pending entries under their own IDs, the plugin declaring a complete feed.
- As the last, plus the plugin carrying a pending entry's ID over to its booked form when exactly one pair matches.

## Decision Outcome

Chosen option: **pending entries under their own IDs, a complete feed, and the ID carried over when the match is unique** (decided after a review on 2026-11-23 found the gap below).

- Every sync returns everything ING lists for the window: the booked entries from Securo's `since` on and all current pending entries. Securo (with complete-feed support for plugins) deletes a pending row that is no longer in the feed, but only once the row is at least seven days old (`_EB_CANCELLED_HOLD_DAYS`), a margin it keeps for every provider.
- So that a booking doesn't show next to its pending form for those days, the plugin remembers each sync's pending entries (in the connection's state, which Securo hands back on the next sync). A booked entry with the same amount, currency and merchant as exactly one pending entry, booked on or within ten days after the purchase, takes that pending entry's ID; Securo then turns the row into a booked one in place. Two equal purchases at one shop match nothing and fall back to the expiry. A carried ID is kept for 100 days, longer than FinTS reaches back.

- The Girokonto balance is the booked balance plus the pending amounts. Sampled on 2026-11-23, this equals ING's own pending balance (HISAL) on both Girokonten. Extra-Konten have no pending entries and keep their booked balance.
- A pending entry is dated by its value date, never later than today: ING's entry date for a pending card payment lies in the future.

### Consequences

- Good, because Securo shows the balance and the entries the ING app shows, without guessing which booking settles which pending entry.
- Bad, because it needs a Securo that expires pending rows of plugin feeds, and an operator who vouches for this plugin (`PLUGINS_COMPLETE_FEED`) until a Securo release reads `complete_feed` from the manifest.
- Good, because in the usual case (one purchase per shop and amount) the row simply turns booked, with what was set on it by hand.
- Bad, because a carried row keeps the pending entry's text and date: Securo refreshes those on a known ID only from a provider's raw data, which a plugin doesn't send.
- Bad, because an unmatched booking shows next to its pending form until that row is a week old.
- Bad, because the match is by content (amount and merchant), not by a reference ING doesn't send: a wrong match is possible when a pending entry and an unrelated booking agree in both; it swaps two rows' IDs, it doesn't lose or double one.
- Bad, because losing the connection's state (a new connection) forgets the carried IDs: booked entries then arrive under their own IDs.
