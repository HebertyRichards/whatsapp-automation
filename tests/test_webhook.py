"""The HTTP surface: webhook authentication, size limit and the health endpoints."""

import httpx

from tests.helpers import CUSTOMER, SECRET, Bot, Database, payload

HEADERS = {"X-Webhook-Secret": SECRET}


async def test_wrong_or_missing_secret_is_rejected(client: httpx.AsyncClient, bot: Bot) -> None:
    body = payload(CUSTOMER, "oi")
    wrong = await client.post("/webhook/evolution", json=body, headers={"X-Webhook-Secret": "nope"})
    missing = await client.post("/webhook/evolution", json=body)
    assert (wrong.status_code, missing.status_code) == (401, 401)
    assert wrong.json()["error"]["code"] == "UNAUTHENTICATED"
    await bot.settle()
    assert bot.messenger.sent == []


async def test_oversized_body_is_refused_without_a_retryable_status(client: httpx.AsyncClient) -> None:
    body = payload(CUSTOMER, "x" * 1_100_000)
    response = await client.post("/webhook/evolution", json=body, headers=HEADERS)
    # 400, not 413: the Evolution API retries a 413 with the same oversized body.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_malformed_events_are_acknowledged_and_ignored(client: httpx.AsyncClient, bot: Bot) -> None:
    odd = {"event": "messages.upsert", "instance": "test", "data": [{"nope": 1}]}
    other = {"event": "connection.update", "instance": "test", "data": {"state": "open"}}
    for body in (odd, other):
        response = await client.post("/webhook/evolution", json=body, headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
    await bot.settle()
    assert bot.messenger.sent == []


async def test_ready_needs_the_store_row(client: httpx.AsyncClient, db: Database) -> None:
    missing = await client.get("/ready")
    assert missing.status_code == 503
    assert missing.json()["dependency"] == "store_settings"
    await db.seed("orders")
    assert (await client.get("/ready")).json() == {"status": "ready"}
    assert (await client.get("/health")).json() == {"status": "ok"}
