---
status: accepted
date: 2026-11-24
decision-makers: Marcel Bruckner
---

# Names as the ING app lists them, the purpose in the notes

## Context and Problem Statement

Version 0.1 cleaned ING's MT940 text into descriptions of its own ("merchant · town", "Aufrundung: <merchant>", "Kauf <security>"), one rule per shape. Every live sync turned up shapes the rules didn't know, and the result still didn't look like the ING app, which is what people compare Securo with. The app's list shows one name per entry; the purpose text appears only when an entry is opened. Search and filters in Securo still need that text.

## Considered Options

- Keep cleaning ING's text, rule by rule, into descriptions of our own.
- The app's name as the description, nothing else.
- The app's name as the description, the payee one per merchant, the whole purpose text in the notes.

## Decision Outcome

Chosen option: **the app's name as the description, one payee per merchant, the purpose in the notes**, because it reads like the app at a glance and loses nothing: Securo searches notes and its rules match on them.

- Description: the counterparty as ING names it, without an IBAN or account number glued to it and without `VISA`; a pending card payment as `merchant · town`. `VISA` goes, unlike the app, because Securo's own category rules match the start of a description ("starts with SPOTIFY").
- Payee: the same name without a card terminal's order reference (`NAME*REF`) or a payment provider's prefix (`XYZ*`, `PAYPAL *`), so one merchant is one payee.
- Notes: the purpose text as ING sends it, whitespace collapsed only.
- Released Securo (0.21.0) refuses a field it doesn't know, and `notes` came with [securo#1833](https://github.com/securo-finance/securo/pull/1833). So a setting, **Purpose text in notes** (default `no`), switches it on; with `no` the purpose follows the name in the description. Once a Securo release has #1833, the plugin requires it and the setting goes.

### Consequences

- Good, because the list looks like the app, and every piece of ING's text is still searchable.
- Good, because there is far less code: three shapes (glued account, `VISA`, the pending columns) instead of a rule per merchant type.
- Bad, because terminal names stay as terminals write them in the description (`AMZN MKTP DE*AB12CD34E`, truncated merchants), as in the app.
- Bad, because with the setting off (released Securo) the description carries the purpose text and reads less like the app.
