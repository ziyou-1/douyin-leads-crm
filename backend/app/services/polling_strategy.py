"""视频评论四档轮询：热门 → 普通 → 冷门 → 暂停。参数由配置中心提供，改完立即用于下一次 Celery 扫描。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class VideoTier(str, Enum):
    HOT = "hot"
    NORMAL = "normal"
    COLD = "cold"
    PAUSED = "paused"


@dataclass
class PollingConfig:
    hot_interval: int = 3
    normal_interval: int = 8
    cold_interval: int = 20
    paused_interval: int = 120
    to_hot_threshold: int = 3
    to_normal_from_cold_threshold: int = 3
    to_cold_from_paused_threshold: int = 10
    hot_to_normal_consecutive: int = 10
    normal_max_polls: int = 20
    cold_max_polls: int = 20

    def interval_minutes(self, tier: VideoTier) -> int:
        return {
            VideoTier.HOT: self.hot_interval,
            VideoTier.NORMAL: self.normal_interval,
            VideoTier.COLD: self.cold_interval,
            VideoTier.PAUSED: self.paused_interval,
        }[tier]

    def to_frontend_dict(self) -> dict:
        return {
            "intervals": {
                "hot": self.hot_interval,
                "normal": self.normal_interval,
                "cold": self.cold_interval,
                "paused": self.paused_interval,
            },
            "upgrade_conditions": {
                "to_hot": self.to_hot_threshold,
                "to_normal_from_cold": self.to_normal_from_cold_threshold,
                "to_cold_from_paused": self.to_cold_from_paused_threshold,
            },
            "downgrade_conditions": {
                "hot_to_normal": self.hot_to_normal_consecutive,
                "normal_max_polls": self.normal_max_polls,
                "cold_max_polls": self.cold_max_polls,
            },
        }

    @classmethod
    def from_frontend_dict(cls, data: dict) -> "PollingConfig":
        intervals = data.get("intervals") or {}
        upgrade = data.get("upgrade_conditions") or {}
        downgrade = data.get("downgrade_conditions") or {}
        return cls(
            hot_interval=int(intervals.get("hot", 3)),
            normal_interval=int(intervals.get("normal", 8)),
            cold_interval=int(intervals.get("cold", 20)),
            paused_interval=int(intervals.get("paused", 120)),
            to_hot_threshold=int(upgrade.get("to_hot", 3)),
            to_normal_from_cold_threshold=int(upgrade.get("to_normal_from_cold", 3)),
            to_cold_from_paused_threshold=int(upgrade.get("to_cold_from_paused", 10)),
            hot_to_normal_consecutive=int(downgrade.get("hot_to_normal", 10)),
            normal_max_polls=int(downgrade.get("normal_max_polls", 20)),
            cold_max_polls=int(downgrade.get("cold_max_polls", 20)),
        )


@dataclass
class VideoPollingState:
    video_id: str
    tier: VideoTier = VideoTier.NORMAL
    consecutive_no_new: int = 0
    poll_count: int = 0
    last_known_comment_count: int = 0

    def reset_counters(self) -> None:
        self.consecutive_no_new = 0
        self.poll_count = 0


_LEGACY_TIER = {
    "hot": VideoTier.HOT,
    "high": VideoTier.HOT,
    "normal": VideoTier.NORMAL,
    "cold": VideoTier.COLD,
    "paused": VideoTier.PAUSED,
}


def normalize_tier(raw: Optional[str]) -> VideoTier:
    if not raw:
        return VideoTier.NORMAL
    key = raw.strip().lower()
    if key in _LEGACY_TIER:
        return _LEGACY_TIER[key]
    raise ValueError(f"unknown video tier: {raw!r}")


def apply_crawl_result(
    state: VideoPollingState,
    config: PollingConfig,
    new_comments: int,
    total_comments: int,
) -> VideoPollingState:
    """按当前档位消化一次爬取结果，写回档位和计数。"""
    state.poll_count += 1
    if state.tier == VideoTier.HOT:
        _process_hot(state, config, new_comments)
    elif state.tier == VideoTier.NORMAL:
        _process_normal(state, config, new_comments)
    elif state.tier == VideoTier.COLD:
        _process_cold(state, config, new_comments)
    elif state.tier == VideoTier.PAUSED:
        _process_paused(state, config, total_comments)
    else:
        raise ValueError(f"unhandled tier {state.tier}")
    state.last_known_comment_count = total_comments
    return state


def _change_tier(state: VideoPollingState, new_tier: VideoTier) -> None:
    state.tier = new_tier
    state.reset_counters()


def _process_hot(state: VideoPollingState, config: PollingConfig, new_comments: int) -> None:
    if new_comments > 0:
        state.consecutive_no_new = 0
        return
    state.consecutive_no_new += 1
    if state.consecutive_no_new >= config.hot_to_normal_consecutive:
        _change_tier(state, VideoTier.NORMAL)


def _process_normal(state: VideoPollingState, config: PollingConfig, new_comments: int) -> None:
    if new_comments >= config.to_hot_threshold:
        _change_tier(state, VideoTier.HOT)
        return
    if state.poll_count >= config.normal_max_polls:
        _change_tier(state, VideoTier.COLD)


def _process_cold(state: VideoPollingState, config: PollingConfig, new_comments: int) -> None:
    if new_comments >= config.to_normal_from_cold_threshold:
        _change_tier(state, VideoTier.NORMAL)
        return
    if state.poll_count >= config.cold_max_polls:
        _change_tier(state, VideoTier.PAUSED)


def _process_paused(state: VideoPollingState, config: PollingConfig, total_comments: int) -> None:
    delta = total_comments - state.last_known_comment_count
    if delta > config.to_cold_from_paused_threshold:
        _change_tier(state, VideoTier.COLD)
