---
status: accepted
date: 2026-11-23
decision-makers: Marcel Bruckner
---

# An own ING plugin, written from scratch

## Context and Problem Statement

Securo reaches ING Germany's depot and savings accounts only over FinTS: PSD2 covers payment accounts alone. A catalog plugin for ING over FinTS existed, but it dropped every depot position as soon as one depot was empty, passed ING's raw MT940 text through as payee and description, and its fixes waited on its maintainer. We want ING to sync without manual work, with the depot and readable transactions.

## Considered Options

- Fork the existing plugin and carry fixes on it.
- An own plugin, written from scratch, borrowing ideas but no code.

## Decision Outcome

Chosen option: **an own plugin, written from scratch**, because Securo's catalog lists no forks (its index is built from `topic:securo-plugin fork:false`), and most of the code would change anyway: the ID scheme, the text clean-up, the depot handling and the structure.

Design points:

- One package with one job per module (`client`, `mapping`, `text`, `depot`, `plugin`); only `client.py` talks to the bank, read calls only.
- Transaction IDs are HMACs over raw bank fields with a per-connection salt, so cleaning text never changes an ID and no IBAN appears in one.
- Each depot is read on its own: an empty depot yields no positions for itself and leaves the others alone. Only depots in the IBAN selection are read.
- python-fints 5.0.1 is pinned, because keeping booked and pending entries apart and reading the raw MT535 need its internals; all such uses are in one subclass in `client.py`.
- No documentation site (the conventions' `repo-setup/docs-site.md`): the README is the documentation. Securo's catalog shows a plugin's README, so that is where its users read; a site for about five pages would add a design, a Pages workflow and a domain to maintain. Revisit if the README outgrows one page.
- TLS is verified by `requests` against its bundled certificates (certifi), not the operating system's trust store as the engineering conventions' HTTPS page asks: that page's reason is a server whose certificate chains to a CA the operating system trusts but certifi doesn't (a company root, an internal CA). This plugin talks to one public server, `fints.ing.de`, from Securo's Linux runner only, so the reason doesn't hold here, and `truststore` would add a dependency and the risk of a runner image without a system store.

### Consequences

- Good, because it is ours to fix and release, in the shape of our other Securo plugin.
- Good, because the catalog can list it and Securo installs it pinned to a release.
- Bad, because a connection made with the earlier plugin cannot move over: Securo ties a connection to its plugin's ID, so a switch means a new connection and a fresh fetch of the history FinTS allows (about 85 days).
- Bad, because a python-fints upgrade needs a review of `client.py`'s subclass.
- Bad, because ING offers no depot transactions over FinTS (its bank parameters list `HIWPDS`, not `HIWDUS`): positions carry their buy-in, but no trades, so a position's chart starts on the first sync.
