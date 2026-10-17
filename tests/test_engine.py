"""The conversation engine, driven through tests/fake_flow.py: sessions, global commands, hand-off, texts."""

import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services import evolution_service
from tests.fake_flow import CATALOG, FakeStep
from tests.helpers import CUSTOMER, STAFF, Bot, Database


async def test_new_session_greets_with_the_store_name_and_the_main_menu(fake_bot: Bot) -> None:
    replies = await fake_bot.say("oi")
    assert len(replies) == 2
    assert "*Loja Teste*" in replies[0]
    assert replies[1].splitlines()[0] == "Como posso ajudar?"
    assert "1 - Escolher cor" in replies[1] and "3 - Falar com atendente" in replies[1]
    assert [sent.delay_ms for sent in fake_bot.messenger.sent] == [4000, 2000]


async def test_a_full_conversation_ends_and_closes_the_session(fake_bot: Bot, db: Database) -> None:
    replies = await fake_bot.conversation("oi", "1", "2", "  Maria   da Silva ")
    assert replies == ["Confirma Verde para Maria da Silva?\n\n1 - Sim\n2 - Não\n\nV - Voltar\n0 - Falar com atendente"]
    assert await fake_bot.say("1") == ["Feito, Maria da Silva!"]
    assert await db.step_of(CUSTOMER) is None


async def test_catalog_option_answers_and_shows_the_menu_again(fake_bot: Bot) -> None:
    await fake_bot.say("oi")
    replies = await fake_bot.say("2")
    assert replies[0] == CATALOG
    assert replies[1].startswith("Como posso ajudar?")


async def test_invalid_answers_explain_and_offer_the_attendant_on_the_second(fake_bot: Bot) -> None:
    await fake_bot.conversation("oi", "1")
    first = await fake_bot.say("roxo")
    second = await fake_bot.say("9")
    assert first[0].startswith("Não entendi.") and "Qual cor?" in first[0]
    assert "Se preferir, digite *0*" not in first[0]
    assert "Se preferir, digite *0*" in second[0]
    # A valid answer resets the count.
    await fake_bot.say("1")
    await fake_bot.say("V")
    assert "Se preferir" not in (await fake_bot.say("x"))[0]


async def test_media_gets_the_text_only_notice(fake_bot: Bot) -> None:
    await fake_bot.say("oi")
    replies = await fake_bot.say(None)
    assert replies[0].startswith("Por aqui eu só consigo ler mensagens de texto.")
    assert "Como posso ajudar?" in replies[0]


async def test_back_command(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1", "1")
    assert await db.step_of(CUSTOMER) == FakeStep.NAME
    # In a free-text step only the one-letter command goes back; "voltar" could be an answer.
    assert (await fake_bot.say("v"))[0].startswith("Qual cor?")
    assert (await fake_bot.say("voltar"))[0].startswith("Como posso ajudar?")


async def test_hand_off_alerts_the_staff_and_menu_gives_the_chat_back(fake_bot: Bot, db: Database) -> None:
    await fake_bot.say("oi")
    replies = await fake_bot.say("3")
    assert "Um atendente vai continuar" in replies[0]
    alert = fake_bot.staff()[-1]
    assert "Cliente pedindo atendimento" in alert and "Nome: Tester" in alert and "wa.me/5511999990001" in alert
    assert await fake_bot.say("quero saber o horário") == []
    assert await db.step_of(CUSTOMER) == "handoff"
    assert (await fake_bot.say("Menu"))[0].startswith("Como posso ajudar?")


async def test_attendant_words_and_zero(fake_bot: Bot) -> None:
    await fake_bot.conversation("oi", "1")
    assert "Um atendente vai continuar" in (await fake_bot.say("quero um atendente"))[0]
    await fake_bot.conversation("menu", "1", "1")
    # Free-text step: the word is an answer, the digit is still the command.
    assert "Um atendente vai continuar" in (await fake_bot.say("0"))[0]


async def test_failed_hand_off_keeps_the_step(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1")
    fake_bot.messenger.failing.add(STAFF)
    replies = await fake_bot.say("0")
    assert replies[0].startswith("Não consegui chamar um atendente") and "Qual cor?" in replies[0]
    assert await db.step_of(CUSTOMER) == FakeStep.COLOR


async def test_session_expires_after_30_quiet_minutes(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1")
    await db.age_conversations(29)
    assert (await fake_bot.say("1"))[0].startswith("Qual é o seu *nome*?")
    await db.age_conversations(31)
    replies = await fake_bot.say("Maria")
    assert len(replies) == 2 and "Bem-vindo" in replies[0]
    assert await db.step_of(CUSTOMER) == "main_menu"


async def test_hand_off_lasts_15_quiet_minutes(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "0")
    await db.age_conversations(14)
    assert await fake_bot.say("alguém aí?") == []
    await db.age_conversations(16)
    assert "Bem-vindo" in (await fake_bot.say("oi"))[0]


async def test_attendant_writing_silences_the_bot(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1")
    assert await fake_bot.send("Deixa que eu atendo", from_me=True)
    await fake_bot.settle()
    assert await db.step_of(CUSTOMER) == "handoff"
    assert fake_bot.staff() == []
    assert await fake_bot.say("1") == []
    assert (await fake_bot.say("menu"))[0].startswith("Como posso ajudar?")


async def test_attendant_writing_first_keeps_the_bot_out(fake_bot: Bot, db: Database) -> None:
    await fake_bot.send("Olá, tudo bem?", from_me=True)
    await fake_bot.settle()
    assert await fake_bot.say("tudo sim") == []
    # The attendant's own messages restart the 15 minutes too.
    await db.age_conversations(14)
    await fake_bot.send("Posso ajudar?", from_me=True)
    await fake_bot.settle()
    await db.age_conversations(14)
    assert await fake_bot.say("pode") == []


async def test_echo_of_the_bots_own_message_is_not_a_takeover(fake_bot: Bot, db: Database) -> None:
    await fake_bot.say("oi")
    evolution_service._sent_ids.append("ECHO1")
    await fake_bot.send("Como posso ajudar?", from_me=True, msg_id="ECHO1")
    await fake_bot.settle()
    assert await db.step_of(CUSTOMER) == "main_menu"


async def test_stale_draft_restarts_from_the_main_menu(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1")
    replies = await fake_bot.say("quebrar")
    assert replies[0].startswith("Precisei reiniciar o atendimento.") and "Como posso ajudar?" in replies[0]
    assert await db.step_of(CUSTOMER) == "main_menu"


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE conversations SET step = 'removed_step'",
        "UPDATE conversations SET draft = '{\"page\": \"not a number\"}'",
    ],
)
async def test_state_from_an_older_version_restarts_the_session(fake_bot: Bot, db: Database, change: str) -> None:
    await fake_bot.conversation("oi", "1")
    await db.execute(change)
    replies = await fake_bot.say("1")
    assert len(replies) == 2 and "Bem-vindo" in replies[0]


async def test_unknown_business_type_keeps_the_bot_silent(
    fake_bot: Bot, db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    await db.execute("UPDATE store_settings SET business_type = 'bakery'")
    with caplog.at_level(logging.ERROR):
        assert await fake_bot.say("oi") == []
    assert "'bakery' is not one of: fake" in caplog.text


async def test_missing_store_row_keeps_the_bot_silent(fake_bot: Bot, db: Database) -> None:
    await db.execute("DELETE FROM store_settings")
    assert await fake_bot.say("oi") == []


async def test_closed_store_says_when_it_opens_and_opens_no_session(fake_bot: Bot, db: Database) -> None:
    await db.execute("DELETE FROM opening_hours")
    replies = await fake_bot.say("oi")
    assert replies == ["Olá! A *Loja Teste* está fechada no momento. 😴"]

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    opens = now + timedelta(hours=2)
    closes = (opens + timedelta(hours=1)).time().replace(minute=0)
    await db.execute(
        "INSERT INTO opening_hours (weekday, opens_at, closes_at) VALUES (:day, :opens, :closes)",
        day=opens.isoweekday(),
        opens=time(opens.hour),
        closes=closes,
    )
    replies = await fake_bot.say("oi")
    day = "hoje" if opens.date() == now.date() else "amanhã"
    assert replies[0].endswith(f"Abrimos {day} às {opens.hour}h.")
    assert await db.step_of(CUSTOMER) is None


async def test_conversation_in_progress_continues_after_closing(fake_bot: Bot, db: Database) -> None:
    await fake_bot.conversation("oi", "1")
    await db.execute("DELETE FROM opening_hours")
    assert (await fake_bot.say("1"))[0].startswith("Qual é o seu *nome*?")


async def test_owner_texts_replace_the_defaults(fake_bot: Bot, db: Database) -> None:
    await db.execute(
        "INSERT INTO texts (key, value) VALUES "
        "('WELCOME', 'Oi! Aqui é a {loja} {desconhecido}.'), "
        "('MAIN_MENU_TITLE', 'O que vai ser?'), "
        "('INVALID', 'Opa, não peguei.'), "
        "('NOT_A_KEY', 'ignored')"
    )
    welcome, menu = await fake_bot.say("oi")
    assert welcome == "Oi! Aqui é a Loja Teste {desconhecido}."
    assert menu.startswith("O que vai ser?")
    assert (await fake_bot.say("9"))[0].startswith("Opa, não peguei.\n\nO que vai ser?")


async def test_customer_jid_is_kept_per_chat(fake_bot: Bot, db: Database) -> None:
    other = "5511999990002@s.whatsapp.net"
    await fake_bot.conversation("oi", "1")
    await fake_bot.say("oi", jid=other)
    assert await db.step_of(CUSTOMER) == FakeStep.COLOR
    assert await db.step_of(other) == "main_menu"
    rows = await db.fetch("SELECT count(*) AS n FROM customers WHERE created_at <= :now", now=datetime.now(UTC))
    assert rows[0]["n"] == 2
