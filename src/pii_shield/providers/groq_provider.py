import logging
from collections.abc import Sequence

import groq
from groq import AsyncGroq

from pii_shield.exceptions import ProviderRequestError, ProviderUnavailableError
from pii_shield.providers.base import LLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        # max_retries=0: fail fast so our fallback kicks in, instead of the SDK retrying.
        self._client = AsyncGroq(api_key=api_key, timeout=timeout, max_retries=0)
        self._model = model

    async def generate(self, messages: Sequence[Message]) -> LLMResponse:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except (
            groq.APIConnectionError,  # includes timeouts
            groq.RateLimitError,
            groq.InternalServerError,
        ) as exc:
            raise ProviderUnavailableError(self.name, type(exc).__name__) from exc
        except groq.APIError as exc:
            raise ProviderRequestError(self.name, type(exc).__name__) from exc

        text = resp.choices[0].message.content if resp.choices else None
        if not text:
            raise ProviderUnavailableError(self.name, "empty response")
        return LLMResponse(text=text, provider=self.name, model=self._model)