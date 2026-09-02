"""四档轮询的可运行例子。直接 python -m app.services.test_polling_strategy"""

from app.services.polling_strategy import (
    PollingConfig,
    VideoPollingState,
    VideoTier,
    apply_crawl_result,
    normalize_tier,
)


def _hot_ten_zero_drops_to_normal():
    cfg = PollingConfig()
    state = VideoPollingState(video_id="v1", tier=VideoTier.HOT)
    for _ in range(9):
        apply_crawl_result(state, cfg, 0, 10)
        assert state.tier == VideoTier.HOT
    apply_crawl_result(state, cfg, 0, 10)
    assert state.tier == VideoTier.NORMAL, state.tier


def _normal_plus_three_goes_hot():
    cfg = PollingConfig()
    state = VideoPollingState(video_id="v2", tier=VideoTier.NORMAL)
    apply_crawl_result(state, cfg, 3, 13)
    assert state.tier == VideoTier.HOT


def _normal_twenty_without_upgrade_goes_cold():
    cfg = PollingConfig()
    state = VideoPollingState(video_id="v3", tier=VideoTier.NORMAL)
    for _ in range(19):
        apply_crawl_result(state, cfg, 0, 5)
        assert state.tier == VideoTier.NORMAL
    apply_crawl_result(state, cfg, 0, 5)
    assert state.tier == VideoTier.COLD, state.tier


def _cold_plus_three_goes_normal():
    cfg = PollingConfig()
    state = VideoPollingState(video_id="v4", tier=VideoTier.COLD)
    apply_crawl_result(state, cfg, 3, 8)
    assert state.tier == VideoTier.NORMAL


def _cold_twenty_no_new_goes_paused():
    cfg = PollingConfig()
    state = VideoPollingState(video_id="v5", tier=VideoTier.COLD)
    for _ in range(19):
        apply_crawl_result(state, cfg, 0, 2)
        assert state.tier == VideoTier.COLD
    apply_crawl_result(state, cfg, 0, 2)
    assert state.tier == VideoTier.PAUSED, state.tier


def _paused_delta_over_ten_back_to_cold():
    cfg = PollingConfig()
    state = VideoPollingState(
        video_id="v6", tier=VideoTier.PAUSED, last_known_comment_count=100
    )
    apply_crawl_result(state, cfg, 11, 111)
    assert state.tier == VideoTier.COLD


def _legacy_high_is_hot():
    assert normalize_tier("high") == VideoTier.HOT
    assert normalize_tier("normal") == VideoTier.NORMAL


if __name__ == "__main__":
    _hot_ten_zero_drops_to_normal()
    _normal_plus_three_goes_hot()
    _normal_twenty_without_upgrade_goes_cold()
    _cold_plus_three_goes_normal()
    _cold_twenty_no_new_goes_paused()
    _paused_delta_over_ten_back_to_cold()
    _legacy_high_is_hot()
    print("polling_strategy examples ok")
