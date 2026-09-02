"""正式号日常伪装：发私信前先刷一小段推荐+点赞。"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.auto_nurture_v2 import NurtureBehaviors

logger = logging.getLogger(__name__)

_WARMED: set[str] = set()


async def warmup_before_dm(page, account_key: str) -> None:
    """每个进程每个账号当天第一次发信前执行一次。"""
    if account_key in _WARMED:
        return
    if settings.DOUYIN_AUTOMATION_MODE != "playwright":
        raise RuntimeError("daily_warmup requires DOUYIN_AUTOMATION_MODE=playwright")
    behaviors = NurtureBehaviors()
    await behaviors.browse_feed(page)
    await behaviors.like_videos(page, video_count=5)
    _WARMED.add(account_key)
    logger.info("daily_warmup done account_key=%s", account_key)
