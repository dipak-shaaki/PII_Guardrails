from pii_shield.config import Settings
from pii_shield.providers.base import LLMProvider, LLMResponse, Message
from pii_shield.providers.fallback import FallbackProvider
from pii_shield.providers.gemini_provider import GeminiProvider
from pii_shield.providers.groq_provider import GroqProvider


def build_provider(settings: Settings) -> LLMProvider:
    """Groq first, Gemini as fallback."""
    return FallbackProvider(
        [
            GroqProvider(settings.groq_api_key, settings.groq_model),
            GeminiProvider(settings.gemini_api_key, settings.gemini_model),
        ]
    )


__all__ = [
    "FallbackProvider",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "build_provider",
]
