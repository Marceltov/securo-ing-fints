# ING Germany (FinTS) for Securo

A read-only [Securo](https://github.com/securo-finance/securo) plugin (Securo 0.20.0 or later) for ING Germany, over FinTS:

- **Girokonto** with its booked and **pending** (vorgemerkte) entries, and the balance the ING app shows: booked plus pending.
- **Extra-Konten** with their balance and entries.
- **Direkt-Depot positions** as holdings: ISIN, name, units, ING's current price and value, and the amount invested (units × ING's average buy-in).
- **Readable payees and descriptions**: no IBANs or account numbers glued to names, no card references; a card payment reads as "merchant · town", a securities trade as "Kauf <security> (<ISIN>)".

It talks only to `fints.ing.de`, through Securo's egress proxy. It cannot make payments or transfers: the code has no call for them.

## Before you start

### A FinTS product registration

Every program that uses FinTS must be registered with the Deutsche Kreditwirtschaft, a script for yourself included. The registration is free, and you need your own: this plugin ships none.

1. Download the registration form from [fints.org → Produktregistrierung](https://www.fints.org/de/hersteller/produktregistrierung).
2. Fill it in as the owner yourself, as a private person. For the product's category, choose **Web-Server**: the plugin runs unattended on your Securo server. The vendor mailing list on page 2 can be declined.
3. Send it by e-mail to the address the form names (`registrierung@hbci-zka.de` at the time of writing).
4. You get a **product registration number** by e-mail. It can take from a few days to several weeks. Keep it with your ING credentials, in a password manager.

### ING

- Your ING login (Zugangsnummer) and internet banking PIN.
- A login in ING's own online banking within the last 90 days: ING requires it for FinTS access.
- Securo with plugins enabled, including the plugin runner and egress proxy ([Securo's bank provider guide](https://github.com/securo-finance/securo/blob/main/docs/plugins/bank-provider-plugins.md)).

## Setting it up

1. In Securo, open **Plugins → Catalog**, find **ING Germany (FinTS)**, review the network access it asks for, and install it.
2. Create a connection with your login, PIN and product registration number.
3. Optionally enter the IBANs to sync, separated by commas; empty means every account ING lists. Depots are read only if they are in that list (or the list is empty).
4. Turn on **Import pending transactions** in the connection's settings to see pending entries (see below).
5. Run the first sync and compare balances, a few entries and the depot positions with the ING app.

### Settings

| Setting | Default | |
|---|---|---|
| IBANs to sync | all | Complete IBANs, comma-separated. An IBAN ING doesn't list fails the sync. |
| Days of history | 85 | 1 to 89. FinTS reaches back about 90 days; later syncs start where Securo asks. |
| Read depot positions | yes | `no` leaves the holdings Securo has untouched. |

## Pending entries

A pending entry is imported under its own ID. Once ING books it, ING stops listing it as pending, and the booked entry arrives as a new one. Securo removes the pending one when the plugin's feed is **complete**, which this plugin's is: every sync returns all booked entries of the window and all current pending ones.

That needs a Securo whose sync expires pending rows of a plugin with a complete feed. Until a Securo release reads that from the plugin's manifest, the operator vouches for the plugin with `PLUGINS_COMPLETE_FEED=marceltov/securo-ing-fints`. Without it, turn **Import pending transactions** off: a booked entry would otherwise appear next to its pending form.

Anything you set by hand on a pending entry (a category, a note) does not carry over to its booked form.

## What it doesn't do

- **No depot history.** ING offers no depot transactions over FinTS, so positions come without their trades, and a position's chart starts on the first sync.
- **No app approval inside a sync.** If ING asks for an approval in its app, the connection pauses ("needs attention") until you reconnect it.
- **No Rahmenkredit, no loans:** ING doesn't offer them over FinTS.

## Safety

- **Read-only by construction**: the only calls are the account list, bank information, balances, statements and depot statements (`ing_fints/client.py`).
- **Fails closed**: an answer the plugin can't read fails the sync; a depot it couldn't read is reported as "not read", never as empty, so Securo keeps what it has.
- **Nothing of yours in messages**: error messages are fixed texts; they never carry IBANs, names, amounts or bank answers. Login, PIN, registration number and IBAN selection are Securo plugin secrets.
- IDs are salted hashes per connection: no IBAN appears in an account or transaction ID. Don't delete and recreate a connection without need: a new one gets new IDs.

## Development

```sh
uv sync
uv run pytest -q
uv run ruff check && uv run ruff format --check
```

`requirements.txt` is what Securo's runner installs; after a change to `uv.lock`, regenerate it with `uv export --frozen --no-dev --no-emit-project --no-header --format requirements-txt > requirements.txt`. Decisions are in [`docs/adr/`](docs/adr/).

## License

[MIT](LICENSE). The `fints` library it uses is LGPL-3.0-or-later.
