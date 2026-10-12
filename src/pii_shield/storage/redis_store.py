import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from redis.asyncio import Redis
from redis.exceptions import LockError, RedisError

from pii_shield.config import Settings
from pii_shield.core.vault import TokenVault
from pii_shield.exceptions import (
    InvalidSessionIdError,
    SessionBusyError,
    SessionStoreError,
)
from pii_shield.providers.base import Message
from pii_shield.storage.serialization import message_from_dict, message_to_dict

logger = logging.getLogger(__name__)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(slots=True)
class SessionData:
    vault: TokenVault
    history: list[Message]


class SessionStore:
    """Redis-backed sessions.

    Layout: one hash per session, `<prefix>session:<id>`, with two fields:
      vault   - token -> real value map, Fernet-encrypted (the only sensitive part)
      history - tokenized messages as JSON (tokens only, by design)
    """

    def __init__(
        self,
        client: Redis,
        encryption_key: str,
        *,
        ttl_seconds: int = 3600,
        prefix: str = "pii_shield:",
    ) -> None:
        keys = [k.strip() for k in encryption_key.split(",") if k.strip()]
        if not keys:
            raise ValueError("encryption_key must contain at least one Fernet key")
        # First key encrypts, all keys can decrypt: that is what makes rotation possible.
        self._fernet = MultiFernet([Fernet(k) for k in keys])
        self._client = client
        self._ttl = ttl_seconds
        self._prefix = prefix

    @classmethod
    def from_settings(cls, settings: Settings) -> SessionStore:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(
            client, settings.encryption_key, ttl_seconds=settings.session_ttl_seconds
        )

    def _key(self, session_id: str) -> str:
        # Strict allow-list: the id ends up inside a Redis key.
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise InvalidSessionIdError(
                "session id must be 8-64 chars of A-Z a-z 0-9 _ -"
            )
        return f"{self._prefix}session:{session_id}"

    async def load(self, session_id: str) -> SessionData:
        """Return the session, or a fresh empty one. Each load refreshes the TTL."""
        key = self._key(session_id)
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.hgetall(key)
                pipe.expire(key, self._ttl)
                raw, _ = await pipe.execute()
        except RedisError as exc:
            logger.error("Redis load failed: %s", type(exc).__name__)
            raise SessionStoreError("could not load session") from exc

        if not raw:
            return SessionData(vault=TokenVault(), history=[])

        try:
            vault = TokenVault.from_dict(json.loads(self._fernet.decrypt(raw["vault"])))
            history = [message_from_dict(m) for m in json.loads(raw["history"])]
        except (InvalidToken, KeyError, TypeError, ValueError) as exc:
            # Log the type only: never include payloads.
            logger.error("Session data unreadable: %s", type(exc).__name__)
            raise SessionStoreError("session data is unreadable") from exc
        return SessionData(vault=vault, history=history)

    async def save(
        self, session_id: str, vault: TokenVault, history: list[Message]
    ) -> None:
        key = self._key(session_id)
        payload = {
            "vault": self._fernet.encrypt(
                json.dumps(vault.to_dict()).encode()
            ).decode(),
            "history": json.dumps([message_to_dict(m) for m in history]),
        }
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.hset(key, mapping=payload)
                pipe.expire(key, self._ttl)
                await pipe.execute()
        except RedisError as exc:
            logger.error("Redis save failed: %s", type(exc).__name__)
            raise SessionStoreError("could not save session") from exc

    async def delete(self, session_id: str) -> bool:
        key = self._key(session_id)
        try:
            return bool(await self._client.delete(key))
        except RedisError as exc:
            logger.error("Redis delete failed: %s", type(exc).__name__)
            raise SessionStoreError("could not delete session") from exc

    @asynccontextmanager
    async def lock(
        self,
        session_id: str,
        *,
        hold_seconds: float = 60.0,
        wait_seconds: float = 10.0,
    ) -> AsyncIterator[None]:
        """Serialize work on one session, so two requests can't overwrite each other.

        hold_seconds is a safety expiry in case the process dies while holding it.
        """
        self._key(session_id)  # validate
        lock = self._client.lock(
            f"{self._prefix}lock:{session_id}",
            timeout=hold_seconds,
            blocking_timeout=wait_seconds,
        )
        try:
            acquired = await lock.acquire()
        except RedisError as exc:
            raise SessionStoreError("could not acquire session lock") from exc
        if not acquired:
            raise SessionBusyError("session is busy, try again shortly")
        try:
            yield
        finally:
            try:
                await lock.release()
            except LockError:
                logger.warning("Session lock expired before release")
            except RedisError as exc:
                logger.error("Lock release failed: %s", type(exc).__name__)

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
