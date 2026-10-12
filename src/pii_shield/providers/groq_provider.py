import json
import logging
from collections.abc import Sequence

import groq
from groq import AsyncGroq

from pii_shield.exceptions import ProviderRequestError, ProviderUnavailableError
from pii_shield.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)


def _to_messages(messages: Sequence[Message]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "content": m.content,
                    "tool_call_id": m.tool_call_id,
                }
            )
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.arguments),
                            },
                        }
                        for c in m.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        # max_retries=0: fail fast so our fallback kicks in, instead of the SDK retrying.
        self._client = AsyncGroq(api_key=api_key, timeout=timeout, max_retries=0)
        self._model = model

    async def generate(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        groq_tools = (
            [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            if tools
            else None
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=_to_messages(messages),
                tools=groq_tools,
            )
        except (
            groq.APIConnectionError,  # includes timeouts
            groq.RateLimitError,
            groq.InternalServerError,
        ) as exc:
            raise ProviderUnavailableError(self.name, type(exc).__name__) from exc
        except groq.APIError as exc:
            raise ProviderRequestError(self.name, type(exc).__name__) from exc

        message = resp.choices[0].message if resp.choices else None
        text = message.content if message else None
        calls = (
            tuple(
                ToolCall(
                    id=c.id,
                    name=c.function.name,
                    arguments=json.loads(c.function.arguments or "{}"),
                )
                for c in (message.tool_calls or ())
            )
            if message
            else ()
        )
        if not text and not calls:
            raise ProviderUnavailableError(self.name, "empty response")
        return LLMResponse(
            text=text or "", provider=self.name, model=self._model, tool_calls=calls
        )
