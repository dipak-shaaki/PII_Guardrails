import logging
from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types

from pii_shield.exceptions import ProviderRequestError, ProviderUnavailableError
from pii_shield.providers.base import LLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # milliseconds
        )
        self._model = model

    async def generate(self, messages: Sequence[Message]) -> LLMResponse:
        system = "\n".join(m.content for m in messages if m.role == "system") or None
        contents = [
            types.Content(
                role="model" if m.role == "assistant" else "user",
                parts=[types.Part(text=m.content)],
            )
            for m in messages
            if m.role != "system"
        ]
        try:
            resp = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system),
            )
        except errors.ServerError as exc:
            raise ProviderUnavailableError(self.name, f"server error {exc.code}") from exc
        except errors.ClientError as exc:
            if exc.code == 429:
                raise ProviderUnavailableError(self.name, "rate limited") from exc
            raise ProviderRequestError(self.name, f"client error {exc.code}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, type(exc).__name__) from exc

        if not resp.text:
            raise ProviderUnavailableError(self.name, "empty response")
        return LLMResponse(text=resp.text, provider=self.name, model=self._model)