---
status: accepted
date: 2026-11-23
decision-makers: Marcel Bruckner
---

# Pending entries, expired through a complete feed

## Context and Problem Statement

ING's app shows the Girokonto balance including pending (vorgemerkte) entries, and lists them. Securo should show the same. A pending card payment later arrives booked, with a different date and text and no reference shared with its pending form, so matching the two by content is guesswork (two equal purchases on one day are two purchases).

## Considered Options

* Booked entries only, booked balance.
* Pending entries matched to their booked form by amount, date and text.
* Pending entries under their own IDs, the plugin declaring a complete feed.

## Decision Outcome

Chosen option: **pending entries under their own IDs, with a complete feed**. Every sync returns everything ING lists for the window: the booked entries from Securo's `since` on and all current pending entries. Securo (with complete-feed support for plugins) then deletes a pending row that is no longer in the feed; the booked entry arrives as a new row in the same sync.

* The Girokonto balance is the booked balance plus the pending amounts. Sampled on 2026-11-23, this equals ING's own pending balance (HISAL) on both Girokonten. Extra-Konten have no pending entries and keep their booked balance.
* A pending entry is dated by its value date, never later than today: ING's entry date for a pending card payment lies in the future.

### Consequences

* Good, because Securo shows the balance and the entries the ING app shows, without guessing which booking settles which pending entry.
* Bad, because it needs a Securo that expires pending rows of plugin feeds, and an operator who vouches for this plugin (`PLUGINS_COMPLETE_FEED`) until a Securo release reads `complete_feed` from the manifest.
* Bad, because a pending entry gets its booked form as a new row: anything set on the pending row by hand (a category, a note) does not carry over.
* Neutral: if ING lists a booking and its pending form in the same answer for a while, both show until the next sync.
