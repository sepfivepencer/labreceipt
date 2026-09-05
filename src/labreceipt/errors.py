"""Safe, user-facing error types."""


class LabReceiptError(Exception):
    """An expected error whose message contains no untrusted values."""
