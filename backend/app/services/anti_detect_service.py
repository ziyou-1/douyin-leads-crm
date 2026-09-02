"""反检测入口：指纹 + 伪装脚本 + 可选代理，接到 Playwright context。"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.advanced_anti_detect import (
    BehaviorSimulator,
    FingerprintManager,
    SessionManager,
    apply_stealth_scripts,
)

logger = logging.getLogger(__name__)

DATA_ROOT = Path("/app/data")
fp_manager = FingerprintManager(storage_dir=DATA_ROOT / "fingerprints")
session_manager = SessionManager(storage_dir=DATA_ROOT / "sessions")


def account_fp_id(cookie_data: str, account_id: int | None = None) -> int:
    if account_id is not None:
        return int(account_id)
    digest = hashlib.sha1(cookie_data.encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) % 2147483647


class AntiDetectService:
    @staticmethod
    async def human_like_click(page, selector: str) -> bool:
        loc = page.locator(selector).first
        box = await loc.bounding_box()
        if box is None:
            raise RuntimeError(f"selector not visible: {selector}")
        sim = BehaviorSimulator(page)
        await sim.bezier_mouse_move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await loc.click()
        return True


async def build_context_kwargs(cookie_data: str, account_id: int | None = None, proxy_url: str = "") -> dict:
    profile = await fp_manager.get_or_create_profile(account_fp_id(cookie_data, account_id))
    kwargs = {
        "viewport": {"width": profile.screen_width, "height": profile.screen_height},
        "user_agent": profile.user_agent,
        "timezone_id": profile.timezone,
        "locale": profile.language,
        "profile": profile,
    }
    if proxy_url:
        kwargs["proxy"] = {"server": proxy_url}
    return kwargs


async def apply_context_stealth(context, profile) -> None:
    await apply_stealth_scripts(context, profile)
