"""Test doubles and drivers: a recording messenger, webhook payloads and a bot driven end to end."""

import asyncio
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.errors import AppException, ErrorCode
from app.schemas.webhook_schemas import WebhookEvent
from app.services.flow import FlowFactory
from app.services.inbound_service import InboundService
from app.services.messenger import Messenger
from app.utils.dependencies import build_conversation_service

ROOT = Path(__file__).resolve().parent.parent
CUSTOMER = "5511999990001@s.whatsapp.net"
STAFF = "120363000000000000@g.us"
INSTANCE = "test"
SECRET = "test-secret-0123456789-0123456789-abcd"


@dataclass(frozen=True)
class Sent:
    jid: str
    text: str
    delay_ms: int


class FakeMessenger(Messenger):
    """Records every message instead of calling the Evolution API."""

    def __init__(self) -> None:
        self.sent: list[Sent] = []
        # JIDs whose sends fail, as if the Evolution API were down.
        self.failing: set[str] = set()
        # Seconds each send takes; the real call returns only after the typing delay.
        self.latency = 0.0

    async def send_text(self, jid: str, text: str, delay_ms: int = 0) -> None:
        if jid in self.failing:
            raise AppException(ErrorCode.EVOLUTION_UNAVAILABLE)
        if self.latency:
            await asyncio.sleep(self.latency)
        self.sent.append(Sent(jid, text, delay_ms))

    def to(self, jid: str) -> list[str]:
        return [sent.text for sent in self.sent if sent.jid == jid]


def payload(
    jid: str,
    text: str | None,
    *,
    msg_id: str | None = None,
    from_me: bool = False,
    instance: str = INSTANCE,
    event: str = "messages.upsert",
    age_seconds: int = 0,
    message_type: str | None = None,
    message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An Evolution webhook body. `text=None` sends an audio message; `message` replaces the content as a whole."""
    if message is None:
        message = {"conversation": text} if text is not None else {"audioMessage": {"url": "x"}}
    return {
        "event": event,
        "instance": instance,
        "data": {
            "key": {"remoteJid": jid, "fromMe": from_me, "id": msg_id or uuid.uuid4().hex},
            "pushName": "Tester",
            "message": message,
            "messageType": message_type or ("conversation" if text is not None else "audioMessage"),
            "messageTimestamp": int(time.time()) - age_seconds,
            "instanceId": "abc",
            "source": "android",
        },
        "destination": "http://bot/webhook/evolution",
        "date_time": "2026-10-08T22:00:00.000Z",
        "sender": "5511000000000@s.whatsapp.net",
        "server_url": "http://evolution.test",
        "apikey": "x",
    }


class Database:
    """Direct SQL against the test database, for seeding and for checking what the bot stored."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def execute(self, sql: str, **params: Any) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def fetch(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            return [dict(row) for row in (await conn.execute(text(sql), params)).mappings()]

    async def run_script(self, path: Path) -> None:
        """Runs a file with several statements, such as the sql/*.example.sql seeds."""
        async with self.engine.connect() as conn:
            raw = await conn.get_raw_connection()
            script = await asyncio.to_thread(path.read_text, encoding="utf-8")
            await raw.driver_connection.execute(script)  # type: ignore[union-attr]

    async def seed(self, name: str) -> None:
        """Loads sql/<name>.example.sql, points staff alerts at STAFF and opens the store around the clock."""
        await self.run_script(ROOT / "sql" / f"{name}.example.sql")
        await self.execute("UPDATE store_settings SET staff_jid = :staff", staff=STAFF)
        await self.always_open()

    async def always_open(self) -> None:
        await self.execute("DELETE FROM opening_hours")
        await self.execute(
            "INSERT INTO opening_hours (weekday, opens_at, closes_at) "
            "SELECT d, '00:00', '00:00' FROM generate_series(1, 7) d"
        )

    async def step_of(self, jid: str) -> str | None:
        """The step the customer's open conversation is on, or None without one."""
        rows = await self.fetch(
            "SELECT c.step FROM conversations c JOIN customers u ON u.id = c.customer_id WHERE u.jid = :jid", jid=jid
        )
        return str(rows[0]["step"]) if rows else None

    async def age_conversations(self, minutes: int) -> None:
        """Moves every open conversation `minutes` into the past, as if the customer had gone quiet."""
        await self.execute(
            "UPDATE conversations SET updated_at = now() - make_interval(mins => :minutes)", minutes=minutes
        )


class Bot:
    """The real inbound pipeline (filters, de-duplication, locks, conversation, replies) with a fake messenger."""

    def __init__(self, messenger: FakeMessenger, flows: Mapping[str, FlowFactory] | None = None) -> None:
        self.messenger = messenger
        kwargs = {} if flows is None else {"flows": flows}
        self.inbound = InboundService(messenger, lambda db: build_conversation_service(db, messenger, **kwargs))

    async def send(self, text: str | None, *, jid: str = CUSTOMER, **options: Any) -> bool:
        """Delivers one webhook without waiting for the replies. False when the bot ignored it."""
        return await self.inbound.accept(WebhookEvent.model_validate(payload(jid, text, **options)))

    async def settle(self) -> None:
        """Waits until every queued message has been answered."""
        await self.inbound.shutdown()

    async def say(self, text: str | None, *, jid: str = CUSTOMER, **options: Any) -> list[str]:
        """Sends one message as the customer and returns the replies they got."""
        before = len(self.messenger.sent)
        await self.send(text, jid=jid, **options)
        await self.settle()
        return [sent.text for sent in self.messenger.sent[before:] if sent.jid == jid]

    async def conversation(self, *messages: str, jid: str = CUSTOMER) -> list[str]:
        """Sends several messages one after the other and returns the replies to the last one."""
        replies: list[str] = []
        for message in messages:
            replies = await self.say(message, jid=jid)
        return replies

    def staff(self) -> list[str]:
        return self.messenger.to(STAFF)
