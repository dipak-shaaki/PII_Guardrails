import os
import uuid

import pytest
from cryptography.fernet import Fernet
from redis.asyncio import Redis
from redis.exceptions import RedisError

from pii_shield import TokenVault
from pii_shield.exceptions import (
    InvalidSessionIdError,
    SessionBusyError,
    SessionStoreError,
)
from pii_shield.providers.base import Message, ToolCall
from pii_shield.storage import SessionStore

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
SID = "session-abcd1234"


@pytest.fixture
async def redis_client():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except RedisError:
        await client.aclose()
        pytest.skip("Redis is not running")
    yield client
    await client.aclose()


@pytest.fixture
async def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    async for key in redis_client.scan_iter(f"{p}*"):
        await redis_client.delete(key)


@pytest.fixture
def key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def store(redis_client, prefix, key) -> SessionStore:
    return SessionStore(redis_client, key, ttl_seconds=100, prefix=prefix)


def sample_session() -> tuple[TokenVault, list[Message]]:
    vault = TokenVault()
    vault.get_or_create_token("PERSON", "Dipak Shanki")
    vault.get_or_create_token("EMAIL_ADDRESS", "dipak@example.com")
    history = [
        Message("user", "hi <PERSON_1>"),
        Message(
            "assistant",
            "",
            tool_calls=(ToolCall("c1", "send_email", {"to": "<EMAIL_ADDRESS_1>"}),),
        ),
        Message("tool", '{"status": "sent"}', tool_call_id="c1", name="send_email"),
    ]
    return vault, history


async def test_roundtrip_preserves_vault_and_history(store):
    vault, history = sample_session()
    await store.save(SID, vault, history)
    data = await store.load(SID)

    assert data.history == history
    assert data.vault.token_to_value == vault.token_to_value
    # numbering and token reuse survive the round trip
    assert data.vault.get_or_create_token("PERSON", "dipak shanki") == "<PERSON_1>"


async def test_unknown_session_returns_fresh_state(store):
    data = await store.load(SID)
    assert data.history == []
    assert data.vault.token_to_value == {}


async def test_vault_is_encrypted_at_rest(store, redis_client, prefix):
    vault, history = sample_session()
    await store.save(SID, vault, history)
    raw = await redis_client.hgetall(f"{prefix}session:{SID}")

    assert "Dipak" not in raw["vault"]
    assert "dipak@example.com" not in raw["vault"]
    assert "Dipak" not in raw["history"]  # history is tokens only


async def test_ttl_is_set_and_refreshed_on_load(store, redis_client, prefix):
    vault, history = sample_session()
    await store.save(SID, vault, history)
    redis_key = f"{prefix}session:{SID}"
    assert 0 < await redis_client.ttl(redis_key) <= 100

    await redis_client.expire(redis_key, 10)
    await store.load(SID)
    assert await redis_client.ttl(redis_key) > 10


async def test_delete_removes_session(store):
    vault, history = sample_session()
    await store.save(SID, vault, history)
    assert await store.delete(SID) is True
    assert (await store.load(SID)).history == []
    assert await store.delete(SID) is False


async def test_wrong_key_raises_store_error(store, redis_client, prefix):
    vault, history = sample_session()
    await store.save(SID, vault, history)

    other = SessionStore(
        redis_client, Fernet.generate_key().decode(), ttl_seconds=100, prefix=prefix
    )
    with pytest.raises(SessionStoreError):
        await other.load(SID)


async def test_key_rotation(redis_client, prefix):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    vault, history = sample_session()

    await SessionStore(redis_client, old, prefix=prefix).save(SID, vault, history)

    rotating = SessionStore(redis_client, f"{new},{old}", prefix=prefix)
    data = await rotating.load(SID)  # old key still readable
    assert data.vault.token_to_value == vault.token_to_value

    await rotating.save(SID, data.vault, data.history)  # re-encrypted with new key
    new_only = SessionStore(redis_client, new, prefix=prefix)
    assert (await new_only.load(SID)).vault.token_to_value == vault.token_to_value


@pytest.mark.parametrize("bad_id", ["short", "has space here", "../../etc/passwd", "a" * 65, ""])
async def test_unsafe_session_ids_rejected(store, bad_id):
    with pytest.raises(InvalidSessionIdError):
        await store.load(bad_id)


async def test_lock_blocks_concurrent_access(store):
    async with store.lock(SID, wait_seconds=0.2):
        with pytest.raises(SessionBusyError):
            async with store.lock(SID, wait_seconds=0.2):
                pass


async def test_lock_is_released_after_use(store):
    async with store.lock(SID, wait_seconds=0.2):
        pass
    async with store.lock(SID, wait_seconds=0.2):  # would raise if still held
        pass


def test_invalid_encryption_key_fails_at_startup(redis_client):
    with pytest.raises(ValueError):
        SessionStore(redis_client, "not-a-fernet-key")
    with pytest.raises(ValueError):
        SessionStore(redis_client, "  ,  ")