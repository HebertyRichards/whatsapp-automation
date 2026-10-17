"""The inbound pipeline: which webhooks are answered, bursts, repeated deliveries, rate limit, ordering, logs."""

import asyncio
import logging
from typing import Any

import pytest

from app.utils import rate_limit
from tests.helpers import CUSTOMER, STAFF, Bot, Database

GROUP = "120363111111111111@g.us"


@pytest.mark.parametrize(
    ("jid", "options"),
    [
        (GROUP, {}),
        ("status@broadcast", {}),
        (CUSTOMER, {"instance": "other"}),
        (CUSTOMER, {"age_seconds": 3600}),
        (CUSTOMER, {"message_type": "reactionMessage", "message": {"reactionMessage": {"text": "👍"}}}),
        (GROUP, {"from_me": True}),
        (CUSTOMER, {"from_me": True, "age_seconds": 3600}),
        (CUSTOMER, {"from_me": True, "message_type": "reactionMessage", "message": {"reactionMessage": {}}}),
    ],
    ids=["group", "broadcast", "other-instance", "stale", "reaction", "own-in-group", "old-own", "own-reaction"],
)
async def test_ignored_messages(fake_bot: Bot, db: Database, jid: str, options: dict[str, Any]) -> None:
    assert not await fake_bot.send("oi", jid=jid, **options)
    await fake_bot.settle()
    assert fake_bot.messenger.sent == []
    assert await db.step_of(CUSTOMER) is None


@pytest.mark.parametrize(
    "message",
    [{"extendedTextMessage": {"text": "oi"}}, {"ephemeralMessage": {"message": {"conversation": "oi"}}}],
    ids=["extended-text", "ephemeral"],
)
async def test_wrapped_texts_are_read(fake_bot: Bot, message: dict[str, Any]) -> None:
    replies = await fake_bot.say(None, message=message, message_type=next(iter(message)))
    assert len(replies) == 2


async def test_lid_chats_are_answered_without_a_phone_link(fake_bot: Bot) -> None:
    lid = "123456789012345@lid"
    assert len(await fake_bot.say("oi", jid=lid)) == 2
    await fake_bot.say("0", jid=lid)
    assert "wa.me" not in fake_bot.staff()[-1]


async def test_repeated_delivery_is_answered_once(fake_bot: Bot, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.services.inbound_service"):
        assert await fake_bot.send("oi", msg_id="DUP1")
        await fake_bot.settle()
        assert not await fake_bot.send("oi", msg_id="DUP1")
        await fake_bot.settle()
    assert len(fake_bot.messenger.sent) == 2
    assert "repeated delivery of DUP1" in caplog.records[-1].getMessage()


async def test_messages_over_the_per_minute_budget_are_dropped(
    fake_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit, "MESSAGE_MAX_PER_WINDOW", 3)
    accepted = [await fake_bot.send(str(n)) for n in range(5)]
    await fake_bot.settle()
    assert accepted == [True, True, True, False, False]
    # A new window starts once the minute is over.
    started, count = rate_limit._windows[CUSTOMER]
    rate_limit._windows[CUSTOMER] = (started - rate_limit.MESSAGE_WINDOW_SECONDS, count)
    assert await fake_bot.send("de novo")
    await fake_bot.settle()


async def test_concurrent_messages_are_answered_in_order(fake_bot: Bot) -> None:
    await fake_bot.say("oi")
    await asyncio.gather(fake_bot.send("1"), fake_bot.send("2"))
    await fake_bot.settle()
    replies = fake_bot.messenger.to(CUSTOMER)[2:]
    assert replies[0].startswith("Qual cor?") and replies[1].startswith("Qual é o seu *nome*?")
    assert fake_bot.inbound._locks._locks == {}
    assert not fake_bot.inbound._answering


async def burst(bot: Bot, *texts: str | None) -> list[str]:
    """Messages sent back to back while the bot is still typing its replies."""
    bot.messenger.latency = 0.2
    before = len(bot.messenger.to(CUSTOMER))
    for text in texts:
        await bot.send(text)
    await bot.settle()
    bot.messenger.latency = 0.0
    return bot.messenger.to(CUSTOMER)[before:]


async def test_greeting_burst_gets_one_welcome_and_no_invalid_notice(
    fake_bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.services.inbound_service"):
        replies = await burst(fake_bot, "oi", "boa noite", "quero comprar")
    assert len(replies) == 2 and "Bem-vindo" in replies[0] and replies[1].startswith("Como posso ajudar?")
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Webhook")]
    assert len(lines) == 3
    assert sum("sent during a reply" in line for line in lines) == 2
    assert all("s after it was sent" in line for line in lines)
    # Sent after the question arrived, the same text is an answer and gets the notice, with no attendant tip.
    replies = await fake_bot.say("quero comprar")
    assert replies[0].startswith("Não entendi.") and "Se preferir" not in replies[0]


async def test_valid_answer_sent_during_a_reply_is_acted_on(fake_bot: Bot) -> None:
    replies = await burst(fake_bot, "oi", "1")
    assert len(replies) == 3 and replies[2].startswith("Qual cor?")


async def test_media_sent_during_a_reply_gets_no_notice(fake_bot: Bot) -> None:
    replies = await burst(fake_bot, "oi", None)
    assert len(replies) == 2


async def test_closed_store_answers_a_burst_once(fake_bot: Bot, db: Database) -> None:
    await db.execute("DELETE FROM opening_hours")
    replies = await burst(fake_bot, "oi", "oi", "alguém aí?")
    assert len(replies) == 1 and "fechada no momento" in replies[0]


async def test_thanks_sent_during_the_confirmation_does_not_reopen_the_chat(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1", "1", "Maria")
    replies = await burst(fake_bot, "1", "obrigado")
    assert replies == ["Feito, Maria!"]
    assert await db.step_of(CUSTOMER) is None


async def test_staff_messages_never_reach_the_customer(fake_bot: Bot) -> None:
    await fake_bot.conversation("oi", "3")
    assert len(fake_bot.messenger.to(STAFF)) == 1
    assert all(STAFF not in text for text in fake_bot.messenger.to(CUSTOMER))
