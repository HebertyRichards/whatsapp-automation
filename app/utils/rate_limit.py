import logging

from app.config.redis_client import get_redis

logger = logging.getLogger(__name__)

# Per customer. Replies take 2s+ of typing each, so a real person stays below this; a loop or a flood does not.
MESSAGE_MAX_PER_WINDOW = 30
MESSAGE_WINDOW_SECONDS = 60

DEDUPE_TTL_SECONDS = 600


async def allow_message(jid: str) -> bool:
    """False once the customer exceeds the per-minute budget. Best-effort: allows everything if Redis is down."""
    redis = await get_redis()
    key = f"rl:msg:{jid}"
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, MESSAGE_WINDOW_SECONDS)
    except Exception as e:
        logger.warning("Rate limit failed on %s: %s", key, e)
        return True
    return current <= MESSAGE_MAX_PER_WINDOW


async def first_delivery(message_id: str) -> bool:
    """False when this WhatsApp message id was already seen, i.e. the webhook was delivered twice."""
    redis = await get_redis()
    try:
        return await redis.set_if_absent(f"dedupe:{message_id}", DEDUPE_TTL_SECONDS)
    except Exception as e:
        logger.warning("De-duplication failed for %s: %s", message_id, e)
        return True
