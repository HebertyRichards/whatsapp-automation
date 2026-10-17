import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from typing import Protocol

import redis.asyncio

from app.config.settings import get_settings
from app.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

SUPERVISOR_INTERVAL = 15.0
# Redis answers in milliseconds and every caller fails open, so a stuck connection must give up fast:
# the webhook waits on these calls before it is acknowledged.
_TIMEOUT_SECONDS = 1.0


class RedisLike(Protocol):
    async def set_if_absent(self, key: str, ttl_seconds: int) -> bool: ...


class NullRedis:
    """Stand-in while Redis is disabled or down: every caller fails open."""

    async def set_if_absent(self, key: str, ttl_seconds: int) -> bool:
        return True


class _BreakerRedis:
    """Runs each command through the circuit breaker: a success closes it, an exception counts as a failure."""

    def __init__(self, client: redis.asyncio.Redis, breaker: CircuitBreaker) -> None:
        self._client = client
        self._breaker = breaker

    async def _run[T](self, command: Awaitable[T]) -> T:
        try:
            result = await command
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return result

    async def set_if_absent(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self._run(self._client.set(key, "1", ex=ttl_seconds, nx=True)))


_client: redis.asyncio.Redis | None = None
_guarded: _BreakerRedis | None = None
_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="redis")
_null_redis = NullRedis()
_supervisor_task: asyncio.Task[None] | None = None


def _is_disabled() -> bool:
    settings = get_settings()
    return not settings.redis_enabled or not settings.redis_url


async def _connect_once() -> bool:
    global _client, _guarded
    try:
        client = redis.asyncio.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=_TIMEOUT_SECONDS,
            socket_connect_timeout=_TIMEOUT_SECONDS,
        )
        await client.ping()
    except Exception as e:
        logger.warning("Redis unavailable: %s", e)
        return False

    previous = _client
    _client = client
    _guarded = _BreakerRedis(client, _breaker)
    _breaker.reset()
    if previous is not None:
        # Swapping clients must not leak the previous connection pool.
        with contextlib.suppress(Exception):
            await previous.aclose()
    return True


async def _supervisor() -> None:
    """Reconnects on its own, both when Redis was down at boot and when the breaker stays open.

    The breaker only probes a client that once worked; if its pool is stuck the probe
    would fail forever, so a fresh client is built instead.
    """
    while True:
        try:
            await asyncio.sleep(SUPERVISOR_INTERVAL)
            if _guarded is not None and not _breaker.is_tripped():
                continue
            if await _connect_once():
                logger.info("Redis reconnected by the supervisor.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Redis supervisor cycle failed: %s", e)


async def init_redis() -> None:
    global _supervisor_task
    if _is_disabled():
        logger.warning("Redis disabled (REDIS_ENABLED=false or empty REDIS_URL): de-duplication runs in memory only.")
        return
    if await _connect_once():
        logger.info("Redis connected.")
    _supervisor_task = asyncio.create_task(_supervisor())


async def get_redis() -> RedisLike:
    # Open circuit: short-circuit to the null client without touching the connection.
    if _guarded is None or not _breaker.allow():
        return _null_redis
    return _guarded


async def close_redis() -> None:
    global _client, _guarded, _supervisor_task
    if _supervisor_task is not None:
        _supervisor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _supervisor_task
        _supervisor_task = None
    if _client is not None:
        await _client.aclose()
        _client = None
        _guarded = None
