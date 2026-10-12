import logging
from collections.abc import Sequence

from pii_shield.exceptions import AllProvidersFailedError, ProviderUnavailableError
from pii_shield.providers.base import LLMProvider, LLMResponse, Message, ToolSpec

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Tries providers in order. Falls through only on transient failures."""

    name = "fallback"

    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        self._providers = tuple(providers)

    async def generate(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        failures: list[ProviderUnavailableError] = []
        for provider in self._providers:
            try:
                response = await provider.generate(messages, tools)
            except ProviderUnavailableError as exc:
                logger.warning("Provider unavailable (%s); trying next", exc)
                failures.append(exc)
                continue
            if failures:
                logger.info("Served by fallback provider: %s", provider.name)
            return response
        raise AllProvidersFailedError(failures)