class PIIShieldError(Exception):
    """Base class for all errors raised by pii_shield."""


class DetectionError(PIIShieldError):
    """Raised when PII detection fails on a given input."""
    
class InputBlockedError(PIIShieldError):
    """Input contained a type of PII that must never be processed."""

    def __init__(self, entity_types: list[str]) -> None:
        self.entity_types = tuple(entity_types)
        super().__init__(f"Input blocked: contains {', '.join(entity_types)}")
        
class ProviderError(PIIShieldError):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailableError(ProviderError):
    """Transient failure (rate limit, timeout, 5xx). Safe to fall back."""


class ProviderRequestError(ProviderError):
    """Permanent failure (bad key, bad request). Falling back would hide a bug."""


class AllProvidersFailedError(PIIShieldError):
    def __init__(self, failures: list[ProviderError]) -> None:
        self.failures = tuple(failures)
        super().__init__("All LLM providers failed: " + "; ".join(str(f) for f in failures))