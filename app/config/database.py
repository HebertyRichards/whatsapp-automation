from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import get_settings


def _asyncpg_url(raw: str) -> tuple[URL, dict[str, object]]:
    """asyncpg rejects libpq-only query params: `sslmode` moves to connect_args, `channel_binding` is dropped."""
    url = make_url(raw)
    query = dict(url.query)
    connect_args: dict[str, object] = {}
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if isinstance(sslmode, str):
        connect_args["ssl"] = sslmode
    return url.set(query=query), connect_args


_url, _connect_args = _asyncpg_url(get_settings().database_url)

engine = create_async_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
