"""The Evolution API client: request shape, error mapping, circuit breaker and the ids it remembers."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.errors import AppException, ErrorCode
from app.services import evolution_service
from app.services.evolution_service import EvolutionService


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 201

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"key": {"id": f"BOT{len(self.requests)}"}})


@pytest.fixture
async def recorder() -> AsyncIterator[Recorder]:
    recorder = Recorder()
    evolution_service._client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    evolution_service._breaker.reset()
    yield recorder
    evolution_service._breaker.reset()
    await evolution_service.close_evolution_client()


async def test_send_text_request(recorder: Recorder) -> None:
    await EvolutionService().send_text("5511999990001@s.whatsapp.net", "olá", 2000)
    request = recorder.requests[-1]
    assert str(request.url) == "http://evolution.test/message/sendText/test"
    assert request.headers["apikey"] == "test-key"
    assert json.loads(request.content) == {
        "number": "5511999990001@s.whatsapp.net",
        "text": "olá",
        "delay": 2000,
        "linkPreview": False,
    }
    assert evolution_service.sent_by_bot("BOT1")


async def test_client_errors_are_rejections_and_leave_the_breaker_closed(recorder: Recorder) -> None:
    recorder.status = 400
    for _ in range(6):
        with pytest.raises(AppException) as error:
            await EvolutionService().send_text("x@s.whatsapp.net", "x")
        assert error.value.code is ErrorCode.EVOLUTION_REJECTED
    assert len(recorder.requests) == 6


async def test_server_errors_open_the_breaker_after_five(recorder: Recorder) -> None:
    recorder.status = 500
    codes = []
    for _ in range(7):
        with pytest.raises(AppException) as error:
            await EvolutionService().send_text("x@s.whatsapp.net", "x")
        codes.append(error.value.code)
    assert len(recorder.requests) == 5
    assert set(codes) == {ErrorCode.EVOLUTION_UNAVAILABLE}
