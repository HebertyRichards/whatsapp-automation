import logging
import time
from collections import OrderedDict

from app.config.redis_client import get_redis

logger = logging.getLogger(__name__)

# Per customer. Replies take 2s+ of typing each, so a real person stays below this; a loop or a flood does not.
MESSAGE_MAX_PER_WINDOW = 30
MESSAGE_WINDOW_SECONDS = 60

DEDUPE_TTL_SECONDS = 600
# Bounds for the in-process records, far above what one store receives in their time windows.
_RECENT_MAX = 10_000
_recent: OrderedDict[str, float] = OrderedDict()
_WINDOWS_MAX = 10_000
# Customer -> (window start, messages in it).
_windows: dict[str, tuple[float, int]] = {}


def _seen_recently(message_id: str) -> bool:
    """In-process record of the latest ids. With a single replica it alone catches every repeated delivery."""
    now = time.monotonic()
    while _recent and (len(_recent) >= _RECENT_MAX or now - next(iter(_recent.values())) > DEDUPE_TTL_SECONDS):
        _recent.popitem(last=False)
    if message_id in _recent:
        return True
    _recent[message_id] = now
    return False


def allow_message(jid: str) -> bool:
    """False once the customer exceeds the per-minute budget.

    Counted in process: the bot runs as a single replica, so this is exact and needs no Redis.
    """
    now = time.monotonic()
    started, count = _windows.get(jid, (now, 0))
    if now - started >= MESSAGE_WINDOW_SECONDS:
        started, count = now, 0
    _windows[jid] = (started, count + 1)
    if len(_windows) > _WINDOWS_MAX:
        for key in [key for key, (start, _) in _windows.items() if now - start >= MESSAGE_WINDOW_SECONDS]:
            del _windows[key]
    return count + 1 <= MESSAGE_MAX_PER_WINDOW


async def first_delivery(message_id: str) -> bool:
    """False when this WhatsApp message id was already seen, i.e. the webhook was delivered twice.

    Redis, when configured, also catches a delivery repeated across a restart.
    """
    if _seen_recently(message_id):
        return False
    redis = await get_redis()
    try:
        return await redis.set_if_absent(f"dedupe:{message_id}", DEDUPE_TTL_SECONDS)
    except Exception as e:
        logger.warning("De-duplication failed for %s: %s", message_id, e)
        return True
