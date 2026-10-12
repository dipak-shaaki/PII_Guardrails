import re
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from pii_shield import PIIShield, TokenVault
from pii_shield.agent import PIIAgent, ToolRegistry
from pii_shield.api.main import create_app
from pii_shield.config import Settings
from pii_shield.exceptions import (
    AllProvidersFailedError,
    InvalidSessionIdError,
    ProviderUnavailableError,
    SessionBusyError,
    SessionStoreError,
)
from pii_shield.providers.base import LLMProvider, LLMResponse
from pii_shield.storage.redis_store import SESSION_ID_PATTERN, SessionData
from tests.helpers import StubDetector

CARD = "4111 1111 1111 1111"
KNOWN = {"Dipak": "PERSON", CARD: "CREDIT_CARD"}


def reply(text: str) -> LLMResponse:
    return LLMResponse(text=text, provider="scripted", model="fake")


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, items):
        self.items = list(items)
        self.seen = []

    async def generate(self, messages, tools=None):
        self.seen.append(list(messages))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeStore:
    """In-memory stand-in with the same interface as SessionStore."""

    def __init__(self):
        self.sessions = {}  # id -> (vault dict, history)
        self.busy = False
        self.down = False

    def _check(self, sid):
        if not SESSION_ID_PATTERN.fullmatch(sid):
            raise InvalidSessionIdError("bad id")
        if self.down:
            raise SessionStoreError("down")

    async def load(self, sid):
        self._check(sid)
        if sid not in self.sessions:
            return SessionData(TokenVault(), [])
        vault, history = self.sessions[sid]
        return SessionData(TokenVault.from_dict(vault), list(history))

    async def save(self, sid, vault, history):
        self._check(sid)
        self.sessions[sid] = (vault.to_dict(), list(history))

    async def delete(self, sid):
        self._check(sid)
        return self.sessions.pop(sid, None) is not None

    @asynccontextmanager
    async def lock(self, sid, **kwargs):
        self._check(sid)
        if self.busy:
            raise SessionBusyError("busy")
        yield

    async def ping(self):
        return not self.down


@asynccontextmanager
async def api(items, expose_token_map=True):
    app = create_app(use_lifespan=False)
    store, provider = FakeStore(), ScriptedProvider(items)
    app.state.settings = Settings(
        groq_api_key="t", gemini_api_key="t", encryption_key="t",
        expose_token_map=expose_token_map,
    )
    app.state.store = store
    app.state.agent = PIIAgent(
        PIIShield(StubDetector(KNOWN)), provider, ToolRegistry(), max_tool_rounds=3
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, store, provider


async def test_chat_returns_all_three_views_and_stores_tokens_only():
    async with api([reply("Hello <PERSON_1>!")]) as (client, store, _):
        r = await client.post("/chat", json={"message": "I'm Dipak"})
        body = r.json()

        assert r.status_code == 200
        assert body["llm_query"] == "I'm <PERSON_1>"
        assert body["llm_reply"] == "Hello <PERSON_1>!"
        assert body["reply"] == "Hello Dipak!"
        assert body["token_map"] == {"<PERSON_1>": "Dipak"}

        _, history = store.sessions[body["session_id"]]
        assert all("Dipak" not in m.content for m in history)


async def test_session_continues_across_turns():
    async with api([reply("Hello <PERSON_1>!"), reply("Welcome back")]) as (client, _, provider):
        first = (await client.post("/chat", json={"message": "I'm Dipak"})).json()
        second = (
            await client.post(
                "/chat", json={"message": "Dipak again", "session_id": first["session_id"]}
            )
        ).json()

        assert second["llm_query"] == "<PERSON_1> again"  # token reused
        assert any(m.content == "I'm <PERSON_1>" for m in provider.seen[1])  # history sent


async def test_server_generates_a_valid_session_id():
    async with api([reply("hi")]) as (client, _, _):
        body = (await client.post("/chat", json={"message": "hello"})).json()
        assert SESSION_ID_PATTERN.fullmatch(body["session_id"])


async def test_credit_card_is_blocked_and_nothing_is_stored_or_sent():
    async with api([]) as (client, store, provider):
        r = await client.post("/chat", json={"message": f"my card is {CARD}"})
        assert r.status_code == 200
        assert r.json()["blocked"] is True
        assert CARD not in r.text
        assert store.sessions == {}
        assert provider.seen == []


async def test_all_providers_failing_returns_503_and_saves_nothing():
    failure = AllProvidersFailedError([ProviderUnavailableError("groq", "timeout")])
    async with api([failure]) as (client, store, _):
        r = await client.post("/chat", json={"message": "hello"})
        assert r.status_code == 503
        assert "error" in r.json()
        assert store.sessions == {}


async def test_busy_session_returns_409():
    async with api([]) as (client, store, _):
        store.busy = True
        r = await client.post("/chat", json={"message": "hello"})
        assert r.status_code == 409


async def test_store_outage_returns_503():
    async with api([]) as (client, store, _):
        store.down = True
        r = await client.post("/chat", json={"message": "hello"})
        assert r.status_code == 503


async def test_message_validation():
    async with api([]) as (client, _, _):
        assert (await client.post("/chat", json={"message": ""})).status_code == 422
        assert (await client.post("/chat", json={"message": "   "})).status_code == 422
        assert (await client.post("/chat", json={"message": "x" * 4001})).status_code == 422


async def test_invalid_session_id_returns_422():
    async with api([]) as (client, _, _):
        r = await client.post("/chat", json={"message": "hi", "session_id": "bad id!"})
        assert r.status_code == 422


async def test_get_session_view_and_404():
    async with api([reply("Hello <PERSON_1>!")]) as (client, _, _):
        sid = (await client.post("/chat", json={"message": "I'm Dipak"})).json()["session_id"]
        r = await client.get(f"/sessions/{sid}")
        body = r.json()
        assert r.status_code == 200
        assert [m["role"] for m in body["history"]] == ["user", "assistant"]
        assert "Dipak" not in str(body["history"])

        assert (await client.get("/sessions/unknown-session-id")).status_code == 404


async def test_token_map_hidden_unless_enabled():
    async with api([reply("hi")], expose_token_map=False) as (client, _, _):
        body = (await client.post("/chat", json={"message": "I'm Dipak"})).json()
        assert body["token_map"] is None
        assert "Dipak" not in str(body["llm_query"])


async def test_delete_session():
    async with api([reply("hi")]) as (client, store, _):
        sid = (await client.post("/chat", json={"message": "hello"})).json()["session_id"]
        assert (await client.delete(f"/sessions/{sid}")).json() == {"deleted": True}
        assert (await client.delete(f"/sessions/{sid}")).json() == {"deleted": False}
        assert store.sessions == {}


async def test_health_reports_redis_state():
    async with api([]) as (client, store, _):
        assert (await client.get("/health")).json() == {"status": "ok", "redis": True}
        store.down = True
        r = await client.get("/health")
        assert r.status_code == 503
        assert r.json()["redis"] is False