from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()  # assistant messages only
    tool_call_id: str | None = None  # tool messages only
    name: str | None = None  # tool messages only


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    tool_calls: tuple[ToolCall, ...] = ()


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        """Return the model's reply. Must raise ProviderError subclasses only."""
