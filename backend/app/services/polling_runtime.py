"""轮询配置持久化 + 分档调用计数。"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.polling_strategy import PollingConfig, VideoTier
from app.services.system_config_service import SystemConfigService

logger = logging.getLogger(__name__)

POLLING_CONFIG_KEY = "polling_strategy_json"
POLL_CALL_HASH = "polling:call_count"


async def load_polling_config(db: AsyncSession) -> PollingConfig:
    raw = await SystemConfigService.get_config(db, POLLING_CONFIG_KEY)
    if raw is None:
        raise RuntimeError("system_config missing polling_strategy_json")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise RuntimeError(f"polling_strategy_json type error: {type(raw)}")
    return PollingConfig.from_frontend_dict(raw)


async def save_polling_config(db: AsyncSession, config: PollingConfig, username: str) -> None:
    payload = json.dumps(config.to_frontend_dict(), ensure_ascii=False)
    await SystemConfigService.update_config(db, POLLING_CONFIG_KEY, payload, username)


async def incr_poll_call(tier: VideoTier) -> None:
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.hincrby(POLL_CALL_HASH, tier.value, 1)
    finally:
        await client.close()


async def get_poll_call_counts() -> dict:
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        raw = await client.hgetall(POLL_CALL_HASH)
    finally:
        await client.close()
    return {
        "hot": int(raw.get("hot", 0)),
        "normal": int(raw.get("normal", 0)),
        "cold": int(raw.get("cold", 0)),
        "paused": int(raw.get("paused", 0)),
    }
