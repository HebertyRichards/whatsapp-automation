"""The tests run against a real PostgreSQL. Set TEST_DATABASE_URL to a database whose name contains "test":
its public schema is dropped and rebuilt from the models at the start of the run.

The settings below are forced, so a local .env never points the tests at a real database or Evolution instance.
"""

import os
from collections.abc import AsyncIterator, Iterator

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
os.environ.update(
    DATABASE_URL=TEST_DATABASE_URL or "postgresql://nobody@127.0.0.1:1/unset_test",
    EVOLUTION_API_URL="http://evolution.test",
    EVOLUTION_API_KEY="test-key",
    EVOLUTION_INSTANCE="test",
    WEBHOOK_SECRET="test-secret-0123456789-0123456789-abcd",
    REDIS_ENABLED="false",
    APP_ENV="test",
    LOG_LEVEL="WARNING",
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.modules import import_models  # noqa: E402
from app.utils import rate_limit  # noqa: E402
from app.utils.dependencies import get_inbound_service  # noqa: E402
from tests.fake_flow import BUSINESS_TYPE, FakeFlow  # noqa: E402
from tests.helpers import STAFF, Bot, Database, FakeMessenger  # noqa: E402

import_models()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="set TEST_DATABASE_URL to an empty PostgreSQL database to run this test")
    for item in items:
        if "db" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture(scope="session")
async def schema() -> AsyncIterator[None]:
    if "test" not in (make_url(TEST_DATABASE_URL).database or ""):
        pytest.exit("TEST_DATABASE_URL must name a database containing 'test': the tests wipe it", returncode=2)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture
async def db(schema: None) -> Database:
    """An empty database: every table is truncated before each test."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    rate_limit._recent.clear()
    rate_limit._windows.clear()
    return Database(engine)


@pytest.fixture
def messenger() -> FakeMessenger:
    return FakeMessenger()


@pytest.fixture
def bot(db: Database, messenger: FakeMessenger) -> Bot:
    """The bot with the modules registered in app/utils/dependencies.py."""
    return Bot(messenger)


@pytest.fixture
async def fake_bot(db: Database, messenger: FakeMessenger) -> Bot:
    """The bot running the minimal module in tests/fake_flow.py, for engine tests that must not depend on a real one."""
    await db.execute(
        "INSERT INTO store_settings (id, name, timezone, business_type, staff_jid) "
        "VALUES (1, 'Loja Teste', 'America/Sao_Paulo', :kind, :staff)",
        kind=BUSINESS_TYPE,
        staff=STAFF,
    )
    await db.always_open()
    return Bot(messenger, flows={BUSINESS_TYPE: FakeFlow})


@pytest.fixture
def client(bot: Bot) -> Iterator[httpx.AsyncClient]:
    """HTTP client for the FastAPI app, with the webhook wired to `bot`."""
    app.dependency_overrides[get_inbound_service] = lambda: bot.inbound
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")
    app.dependency_overrides.clear()
