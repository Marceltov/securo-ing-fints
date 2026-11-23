"""The three ways a sync can fail, as Securo's plugin contract names them.

Messages are fixed English text. They never carry bank answers, IBANs, amounts or credentials.
"""


class NeedsAuth(Exception):
    """Securo pauses the connection until the credentials or an approval are renewed."""


class RateLimited(Exception):
    """Securo retries at the next scheduled sync."""


class BankSyncError(Exception):
    """The bank's answer could not be used; nothing was imported."""
