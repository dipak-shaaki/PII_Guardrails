class PIIShieldError(Exception):
    """Base class for all errors raised by pii_shield."""


class DetectionError(PIIShieldError):
    """Raised when PII detection fails on a given input."""
    
class InputBlockedError(PIIShieldError):
    """Input contained a type of PII that must never be processed."""

    def __init__(self, entity_types: list[str]) -> None:
        self.entity_types = tuple(entity_types)
        super().__init__(f"Input blocked: contains {', '.join(entity_types)}")