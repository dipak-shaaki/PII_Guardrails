class PIIShieldError(Exception):
    """Base class for all errors raised by pii_shield."""


class DetectionError(PIIShieldError):
    """Raised when PII detection fails on a given input."""