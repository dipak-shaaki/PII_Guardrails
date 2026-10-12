import pytest

from pii_shield.exceptions import (
    AllProvidersFailedError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from pii_shield.providers import FallbackProvider, LLMProvider, LLMResponse, Message

MSGS = [Message("user", "hi <PERSON_1>")]


class FakeProvider(LLMProvider):
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0

    async def generate(self, messages, tools=None):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResponse(text="ok", provider=self.name, model="fake")


async def test_first_provider_wins_when_healthy():
    a, b = FakeProvider("a"), FakeProvider("b")
    result = await FallbackProvider([a, b]).generate(MSGS)
    assert result.provider == "a"
    assert b.calls == 0


async def test_falls_back_on_unavailable():
    a = FakeProvider("a", ProviderUnavailableError("a", "rate limited"))
    b = FakeProvider("b")
    result = await FallbackProvider([a, b]).generate(MSGS)
    assert result.provider == "b"
    assert a.calls == 1


async def test_all_failing_raises_aggregate_error():
    a = FakeProvider("a", ProviderUnavailableError("a", "timeout"))
    b = FakeProvider("b", ProviderUnavailableError("b", "500"))
    with pytest.raises(AllProvidersFailedError) as exc:
        await FallbackProvider([a, b]).generate(MSGS)
    assert len(exc.value.failures) == 2


async def test_permanent_error_does_not_fall_back():
    a = FakeProvider("a", ProviderRequestError("a", "bad key"))
    b = FakeProvider("b")
    with pytest.raises(ProviderRequestError):
        await FallbackProvider([a, b]).generate(MSGS)
    assert b.calls == 0


def test_empty_provider_list_rejected():
    with pytest.raises(ValueError):
        FallbackProvider([])
