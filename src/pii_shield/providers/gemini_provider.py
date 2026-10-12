import logging
import uuid
from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types

from pii_shield.exceptions import ProviderRequestError, ProviderUnavailableError
from pii_shield.providers.base import (
    LLMProvider,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)


def _to_contents(messages: Sequence[Message]) -> list[types.Content]:
    contents: list[types.Content] = []
    last_was_tool = False
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            part = types.Part.from_function_response(
                name=m.name or "tool", response={"result": m.content}
            )
            # Gemini expects parallel tool results grouped into a single turn.
            if last_was_tool:
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
            last_was_tool = True
            continue

        last_was_tool = False
        if m.role == "assistant":
            parts = [types.Part(text=m.content)] if m.content else []
            parts += [
                types.Part(
                    function_call=types.FunctionCall(name=c.name, args=c.arguments)
                )
                for c in m.tool_calls
            ]
            contents.append(types.Content(role="model", parts=parts))
        else:
            contents.append(
                types.Content(role="user", parts=[types.Part(text=m.content)])
            )
    return contents


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # milliseconds
        )
        self._model = model

    async def generate(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        system = "\n".join(m.content for m in messages if m.role == "system") or None
        gemini_tools = (
            [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.parameters,
                        )
                        for t in tools
                    ]
                )
            ]
            if tools
            else None
        )
        try:
            resp = await self._client.aio.models.generate_content(
                model=self._model,
                contents=_to_contents(messages),
                config=types.GenerateContentConfig(
                    system_instruction=system, tools=gemini_tools
                ),
            )
        except errors.ServerError as exc:
            raise ProviderUnavailableError(
                self.name, f"server error {exc.code}"
            ) from exc
        except errors.ClientError as exc:
            if exc.code == 429:
                raise ProviderUnavailableError(self.name, "rate limited") from exc
            raise ProviderRequestError(self.name, f"client error {exc.code}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, type(exc).__name__) from exc

        candidate = resp.candidates[0] if resp.candidates else None
        parts = (
            (candidate.content.parts or []) if candidate and candidate.content else []
        )

        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = tuple(
            ToolCall(
                id=p.function_call.id or f"call_{uuid.uuid4().hex[:8]}",
                name=p.function_call.name,
                arguments=dict(p.function_call.args or {}),
            )
            for p in parts
            if p.function_call
        )
        if not text and not calls:
            raise ProviderUnavailableError(self.name, "empty response")
        return LLMResponse(
            text=text, provider=self.name, model=self._model, tool_calls=calls
        )
