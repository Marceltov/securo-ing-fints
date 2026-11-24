# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

securo-ing-fints: a read-only Securo plugin that syncs ING Germany (Girokonto with pending entries, Extra-Konten, Direkt-Depot positions) over FinTS.

## Commands
- `uv sync`, then `uv run pytest -q` (one test: `uv run pytest -q tests/test_text.py::test_name`).
- `uv run ruff format`, `uv run ruff check --fix`; CI runs `ruff check`, `ruff format --check` and pytest.
- After any change to `uv.lock`: `uv export --frozen --no-dev --no-emit-project --no-header --format requirements-txt > requirements.txt` (a test fails otherwise). Securo's runner installs that file and refuses anything but hash-pinned index packages.
- Release: bump `version` in `pyproject.toml` and `securo-plugin.json`, then `git tag -a vX.Y.Z -m "<headline>" && git push origin vX.Y.Z`.

## Architecture
- `ing_fints/plugin.py`: `plugin.sync(params, context)`, Securo's entrypoint (`ing_fints.plugin:plugin`); reads the settings and orchestrates, nothing else.
- `ing_fints/client.py`: the only module that talks FinTS (python-fints), read calls only. Every use of python-fints internals is in its one subclass; that is why `fints` is pinned.
- `ing_fints/mapping.py` (accounts, transactions, IDs), `ing_fints/text.py` (payee and description clean-up), `ing_fints/depot.py` (MT535 parser, holdings), `ing_fints/pending.py` (a pending entry's ID carried to its booked form, through the connection's state): pure functions.
- `ing_fints/errors.py`: `NeedsAuth`, `RateLimited`, `BankSyncError`.

## Rules
- Follows Marceltov/engineering-conventions; the rules here win where they differ. No docs site: the README is the documentation.
- CodeQL runs from the shared workflow of Marceltov/engineering-conventions (`.github/workflows/codeql.yml` calls it), which leaves out test code; GitHub's default setup stays off. Changes to what it leaves out go there, not here.
- Read-only: no code path may initiate a payment, a transfer or submit a TAN.
- No IBAN, balance, real transaction text, registration number or bank response in git, a test fixture, an error message or a log. Fixtures are invented values in ING's shapes.
- Transaction IDs come from raw bank fields only, never from cleaned text: changing `text.py` must not change an ID.
- An answer that can't be read fails the sync; it never returns an empty list in place of data it couldn't read (`holdings: None` means not read).
- Dependabot auto-merges patch and minor bumps of dev tools and GitHub Actions once CI passes: the one case where a merge happens without the user saying so. Runtime dependencies change by hand.
- Code, errors and docs in English. The manifest's user-facing texts are in English and German: Securo shows a plugin's text in the user's language (falling back to English), and this plugin's users bank in Germany. Other languages only when someone asks for one.
- Architectural decisions go to `docs/adr/NNNN-*.md` (MADR).
