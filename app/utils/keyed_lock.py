import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class KeyedLock:
    """Serializes work per key. An entry is dropped once nobody holds or awaits it."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._users: dict[str, int] = {}

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._users[key] = self._users.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._users[key] -= 1
            if not self._users[key]:
                del self._users[key], self._locks[key]
