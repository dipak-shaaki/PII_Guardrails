import json
import logging
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from pii_shield.core.vault import TOKEN_PATTERN
from pii_shield.exceptions import ToolError
from pii_shield.providers.base import ToolSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]  # validates arguments and generates the JSON schema
    handler: Callable[[Any], Awaitable[Any]]  # receives a validated args_model instance

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            self.name, self.description, self.args_model.model_json_schema()
        )


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool] = ()) -> None:
        self._tools = {t.name: t for t in tools}

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool with REAL values. Returns a JSON string.

        Error messages must never include argument values: they go back to the LLM.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name}")
        try:
            args = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                for e in exc.errors(include_input=False)
            )
            raise ToolError(f"invalid arguments ({problems})") from exc
        try:
            result = await tool.handler(args)
        except ToolError:
            raise
        except Exception as exc:
            # Log the type only: exception messages can contain real PII.
            logger.error("Tool %s failed: %s", name, type(exc).__name__)
            raise ToolError("tool execution failed") from exc
        return json.dumps(result, default=str)


def map_strings(value: Any, fn: Callable[[str], str]) -> Any:
    """Apply fn to every string inside a nested dict/list structure."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [map_strings(v, fn) for v in value]
    return value


def _iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)


def has_unresolved_token(value: Any) -> bool:
    """True if a token survived restore(), e.g. the LLM invented <EMAIL_ADDRESS_9>."""
    return any(TOKEN_PATTERN.search(s) for s in _iter_strings(value))
