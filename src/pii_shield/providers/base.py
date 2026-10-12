from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate(self, messages: Sequence[Message]) -> LLMResponse:
        """Return the model's reply. Must raise ProviderError subclasses only."""