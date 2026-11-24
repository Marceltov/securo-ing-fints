"""Throwaway: a deliberate clear-text leak, to prove CodeQL still scans the package. Removed before merging."""

import logging


def probe(password: str) -> None:
    logging.getLogger(__name__).warning("password is %s", password)
