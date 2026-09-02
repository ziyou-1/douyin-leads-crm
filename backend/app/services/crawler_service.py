import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_sentiment_adapter
from app.adapters.base import CommentDTO
from app.core.config import settings
from app.models.comment import Comment
from app.models.topic_monitor import TopicMonitor
from app.models.monitor import MonitorAccount
from app.models.video import Video
from app.services.alert_service import AlertService, LEVEL_CRITICAL, SOURCE_CRAWLER
from app.services.quota_service import QuotaService
from app.services.api_log_service import log_api_call

logger = logging.getLogger(__name__)

# TikHub等第三方数据接口计费/欠费类错误的特征关键字。
# 这类错误会导致抓取环节整体失败(而不是普通的偶发网络错误)，需要主动告警，
# 否则任务会在Celery层面"假成功"返回(status=error)，长时间无人发现。
_BILLING_ERROR_MARKERS = (
    "402",
    "payment required",
    "insufficient balance",
    "insufficient_balance",
    "余额不足",
    "免费额度",
    "add_credit",
)


def _is_billing_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker.lower() in message for marker in _BILLING_ERROR_MARKERS)


async def _alert_on_adapter_error(db: AsyncSession, api_type: str, context: str, exc: Exception) -> None:
    """针对TikHub等数据接口的计费类错误发送告警(带1小时去重)。"""
    if not _is_billing_error(exc):
        return
    await AlertService.send_alert(
        db,
        level=LEVEL_CRITICAL,
        title="TikHub 数据接口余额不足",
        content=f"[{context}] 调用 {api_type} 接口失败，疑似账户余额/免费额度耗尽，"
                f"抓取任务将持续失败直到充值。错误详情: {exc}",
        source=SOURCE_CRAWLER,
        dedup_key=f"tikhub_billing:{api_type}",
    )


# ── 无效评论过滤 ──────────────────────────────────────────────────────────────

# Emoji Unicode 范围正则
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "\uFE0F"
    "\u200D"
    "]+",
    flags=re.UNICODE,
)


def _is_only_emoji(text: str) -> bool:
    """判断文本是否只包含emoji"""
    stripped = _EMOJI_RE.sub("", text).strip()
    return len(stripped) == 0


def _is_only_punctuation(text: str) -> bool:
    """判断文本是否只包含标点符号"""
    for ch in text:
        cat = unicodedata.category(ch)
        if cat not in ("Po", "Pd", "Ps", "Pe", "Pc", "Pi", "Pf"):
            return False
    return True


def _is_valid_comment(content: str) -> bool:
    """判断评论是否有效（非垃圾）"""
    stripped = content.strip()
    if len(stripped) < 3:
        return False
    if _is_only_emoji(stripped):
        return False
    if _is_only_punctuation(stripped):
        return False
    return True


def filter_comments(comments: List[CommentDTO], since_minutes: int) -> List[CommentDTO]:
    """
    过滤评论：
    1. 时间窗口过滤：只保留since_minutes分钟内的评论
    2. 无效过滤：纯emoji、内容太短(<3字符)、纯标点
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=since_minutes)

    filtered = []
    for c in comments:
        # 确保时区感知
        ct = c.comment_time
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)

        # 时间窗口过滤
        if ct < cutoff:
            continue

        # 无效过滤
        if not _is_valid_comment(c.content):
            continue

        filtered.append(c)

    return filtered


async def _apply_active_video_limit(db: AsyncSession, monitor_account_id: int, limit: int) -> None:
    """
    每个监控账号只保留发布时间最新的limit条视频为active(默认1条,只监控最新视频)。
    其余未过期的视频置为inactive,停止评论轮询;已过期(expired)的视频不受影响。
    """
    result = await db.execute(
        select(Video)
        .where(
            Video.monitor_account_id == monitor_account_id,
            Video.status != "expired",
        )
        .order_by(Video.publish_time.desc().nullslast())
    )
    videos = result.scalars().all()
    for idx, video_obj in enumerate(videos):
        if idx < limit:
            if video_obj.status != "active":
                video_obj.status = "active"
        elif video_obj.status != "inactive":
            video_obj.status = "inactive"


# ── 采集服务 ──────────────────────────────────────────────────────────────────

async def crawl_account_comments(db: AsyncSession, monitor_account_id: int) -> dict:
    """
    对指定监控账号执行一次新视频发现流程（不抓取评论）：
    1. 获取监控账号信息
    2. 调用适配器获取视频列表，更新videos表(新建/更新标题等基础信息)
    3. 只保留发布时间最新的 ACCOUNT_ACTIVE_VIDEO_LIMIT 条视频为active，其余置为inactive
    4. 评论抓取统一交给 poll_video_comments 按视频固定间隔轮询处理(只轮询active视频)
    """
    # 1. 获取监控账号
    result = await db.execute(
        select(MonitorAccount).where(MonitorAccount.id == monitor_account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        logger.warning("MonitorAccount id=%d not found, skip", monitor_account_id)
        return {"status": "not_found", "monitor_id": monitor_account_id}

    if account.status != "active":
        logger.info("MonitorAccount id=%d status=%s, skip", monitor_account_id, account.status)
        return {"status": "skipped", "reason": f"status={account.status}"}

    adapter = get_sentiment_adapter()
    now = datetime.now(timezone.utc)

    # 2. 检查作品接口配额
    video_available, video_rate = await QuotaService.check_quota("video_api")
    if not video_available:
        logger.warning("Video API quota exceeded (%.1f%%), skip crawl for account %d", video_rate, monitor_account_id)
        return {"status": "quota_exceeded", "api_type": "video_api", "usage_rate": video_rate}

    # 3. 获取视频列表并更新videos表
    try:
        t0 = time.monotonic()
        video_dtos = await adapter.get_video_list(account.douyin_uid)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("video_api")
        await log_api_call("video_api", "get_video_list", {"account_uid": account.douyin_uid}, 200, elapsed_ms, True)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("video_api")
        await log_api_call("video_api", "get_video_list", {"account_uid": account.douyin_uid}, 500, elapsed_ms, False, str(exc))
        logger.error("Failed to get video list for account %d: %s", monitor_account_id, exc)
        await _alert_on_adapter_error(db, "video_api", f"crawl_account_comments account={monitor_account_id}", exc)
        return {"status": "error", "error": str(exc)}

    all_video_count = len(video_dtos)
    lifecycle_cutoff = now - timedelta(days=settings.VIDEO_LIFECYCLE_DAYS)
    recent_video_dtos = []
    for video_dto in video_dtos:
        publish_time = video_dto.publish_time
        if publish_time is None:
            recent_video_dtos.append(video_dto)
            continue
        if publish_time.tzinfo is None:
            publish_time = publish_time.replace(tzinfo=timezone.utc)
        if publish_time >= lifecycle_cutoff:
            recent_video_dtos.append(video_dto)

    new_video_count = 0
    for vd in recent_video_dtos:
        existing = await db.execute(
            select(Video).where(Video.video_id == vd.video_id)
        )
        video_obj = existing.scalar_one_or_none()
        if video_obj is None:
            video_obj = Video(
                monitor_account_id=account.id,
                video_id=vd.video_id,
                title=vd.title,
                publish_time=vd.publish_time,
            )
            db.add(video_obj)
            await db.flush()
            new_video_count += 1
        else:
            video_obj.title = vd.title
            video_obj.publish_time = vd.publish_time

    await db.flush()
    await _apply_active_video_limit(db, monitor_account_id, settings.ACCOUNT_ACTIVE_VIDEO_LIMIT)
    await db.flush()

    result_info = {
        "status": "ok",
        "monitor_id": monitor_account_id,
        "videos_found": all_video_count,
        "videos_in_lifecycle": len(recent_video_dtos),
        "new_videos": new_video_count,
    }
    logger.info("Video discovery result for account %d: %s", monitor_account_id, result_info)
    return result_info


async def get_crawl_stats(db: AsyncSession) -> dict:
    """获取今日采集统计"""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 今日采集总数
    total_result = await db.execute(
        select(func.count()).select_from(Comment).where(Comment.crawled_at >= today_start)
    )
    total_today = total_result.scalar() or 0

    # 今日已处理（有效）数
    processed_result = await db.execute(
        select(func.count()).select_from(Comment).where(
            Comment.crawled_at >= today_start,
            Comment.is_processed == True,  # noqa: E712
        )
    )
    processed_today = processed_result.scalar() or 0

    return {
        "total_today": total_today,
        "processed_today": processed_today,
        "date": today_start.date().isoformat(),
    }


async def crawl_topic_comments(db: AsyncSession, topic_monitor_id: int) -> dict:
    """
    对指定话题监控执行一次完整的评论采集流程：
    1. 获取话题配置
    2. 调用适配器 fetch_topic_comments 采集该领域评论
    3. 去重 + 存入comments表(source_type="topic")
    4. 不做任何关键词过滤！所有评论直接存入，后续统一由AI意向识别处理
    """
    # 1. 获取话题监控
    result = await db.execute(
        select(TopicMonitor).where(TopicMonitor.id == topic_monitor_id)
    )
    topic_monitor = result.scalar_one_or_none()
    if not topic_monitor:
        logger.warning("TopicMonitor id=%d not found, skip", topic_monitor_id)
        return {"status": "not_found", "topic_monitor_id": topic_monitor_id}

    if topic_monitor.status != "active":
        logger.info("TopicMonitor id=%d status=%s, skip", topic_monitor_id, topic_monitor.status)
        return {"status": "skipped", "reason": f"status={topic_monitor.status}"}

    adapter = get_sentiment_adapter()
    now = datetime.now(timezone.utc)
    since_time = now - timedelta(minutes=topic_monitor.poll_interval_min)

    # 2. 检查评论接口配额
    comment_available, comment_rate = await QuotaService.check_quota("comment_api")
    if not comment_available:
        logger.warning("Comment API quota exceeded (%.1f%%), skip topic crawl '%s'", comment_rate, topic_monitor.topic)
        return {"status": "quota_exceeded", "api_type": "comment_api", "usage_rate": comment_rate}

    # 3. 调用适配器按话题/行业范围采集评论（不做关键词过滤）
    try:
        t0 = time.monotonic()
        raw_comments = await adapter.fetch_topic_comments(
            topic_monitor.topic, topic_monitor.industry, since_time
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("comment_api")
        await log_api_call("comment_api", "fetch_topic_comments",
                           {"topic": topic_monitor.topic, "industry": topic_monitor.industry},
                           200, elapsed_ms, True)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("comment_api")
        await log_api_call("comment_api", "fetch_topic_comments",
                           {"topic": topic_monitor.topic, "industry": topic_monitor.industry},
                           500, elapsed_ms, False, str(exc))
        logger.error("Failed to fetch topic comments for '%s': %s", topic_monitor.topic, exc)
        await _alert_on_adapter_error(db, "comment_api", f"crawl_topic_comments topic={topic_monitor.topic}", exc)
        return {"status": "error", "error": str(exc)}

    total_fetched = len(raw_comments)

    # 3. 过滤（仅过滤无效评论：纯emoji、太短、纯标点）
    valid_comments = filter_comments(raw_comments, topic_monitor.poll_interval_min)

    # 4. 去重+入库，不做任何关键词过滤，全量存储交给AI判断
    if valid_comments:
        cid_list = [c.comment_id for c in valid_comments]
        existing_result = await db.execute(
            select(Comment.comment_id).where(Comment.comment_id.in_(cid_list))
        )
        existing_cids = set(row[0] for row in existing_result.all())
    else:
        existing_cids = set()

    total_saved = 0
    total_duplicate = 0

    for c in valid_comments:
        if c.comment_id in existing_cids:
            total_duplicate += 1
            continue
        comment_obj = Comment(
            video_id=None,  # 话题监控没有关联视频
            comment_id=c.comment_id,
            user_uid=c.user_uid,
            user_nickname=c.user_nickname,
            content=c.content,
            comment_time=c.comment_time,
            source_type="topic",
            source_topic_id=topic_monitor.id,
        )
        db.add(comment_obj)
        total_saved += 1

    await db.flush()

    result_info = {
        "status": "ok",
        "topic_monitor_id": topic_monitor_id,
        "topic": topic_monitor.topic,
        "total_fetched": total_fetched,
        "total_saved": total_saved,
        "total_duplicate": total_duplicate,
    }
    logger.info("Topic crawl result for '%s': %s", topic_monitor.topic, result_info)
    return result_info


# ── 视频生命周期管理与智能轮询 ────────────────────────────────────────────


async def sync_account_videos(db: AsyncSession, monitor_account_id: int) -> dict:
    """
    拉取账号视频列表，维护视频生命周期：
    - 只保存 VIDEO_LIFECYCLE_DAYS 天内的视频，超过则标记 expired
    - 根据评论数判断 heat_level（>= HIGH_HEAT_THRESHOLD 为 high，仅用于展示分级）
    - 新视频 status=active，重新进入生命周期的过期视频恢复 status=active
    - 最后只保留发布时间最新的 ACCOUNT_ACTIVE_VIDEO_LIMIT 条视频为active，其余置为inactive
    """
    # 1. 获取监控账号
    result = await db.execute(
        select(MonitorAccount).where(MonitorAccount.id == monitor_account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        logger.warning("sync_account_videos: MonitorAccount id=%d not found, skip", monitor_account_id)
        return {"status": "not_found", "monitor_id": monitor_account_id}

    if account.status != "active":
        logger.info("sync_account_videos: MonitorAccount id=%d status=%s, skip", monitor_account_id, account.status)
        return {"status": "skipped", "reason": f"status={account.status}"}

    adapter = get_sentiment_adapter()
    now = datetime.now(timezone.utc)
    lifecycle_cutoff = now - timedelta(days=settings.VIDEO_LIFECYCLE_DAYS)

    # 2. 检查作品接口配额
    video_available, video_rate = await QuotaService.check_quota("video_api")
    if not video_available:
        logger.warning("Video API quota exceeded (%.1f%%), skip sync for account %d", video_rate, monitor_account_id)
        return {"status": "quota_exceeded", "api_type": "video_api", "usage_rate": video_rate}

    # 3. 拉取视频列表
    try:
        t0 = time.monotonic()
        video_dtos = await adapter.get_video_list(account.douyin_uid)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("video_api")
        await log_api_call("video_api", "get_video_list", {"account_uid": account.douyin_uid}, 200, elapsed_ms, True)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("video_api")
        await log_api_call("video_api", "get_video_list", {"account_uid": account.douyin_uid}, 500, elapsed_ms, False, str(exc))
        logger.error("sync_account_videos: Failed to get video list for account %d: %s", monitor_account_id, exc)
        await _alert_on_adapter_error(db, "video_api", f"sync_account_videos account={monitor_account_id}", exc)
        return {"status": "error", "error": str(exc)}

    synced_count = 0
    expired_count = 0

    for vd in video_dtos:
        # 确保 publish_time 时区感知
        pub_time = vd.publish_time
        if pub_time and pub_time.tzinfo is None:
            pub_time = pub_time.replace(tzinfo=timezone.utc)

        # 判断是否在生命周期内
        is_within_lifecycle = pub_time and pub_time > lifecycle_cutoff

        # 确定热度等级(仅用于展示分级，不影响轮询频率)
        heat = "normal"

        # 查找或创建视频记录
        existing = await db.execute(
            select(Video).where(Video.video_id == vd.video_id)
        )
        video_obj = existing.scalar_one_or_none()

        if video_obj is None:
            if not is_within_lifecycle:
                # 超过生命周期的新视频不入库
                expired_count += 1
                continue
            video_obj = Video(
                monitor_account_id=account.id,
                video_id=vd.video_id,
                title=vd.title,
                publish_time=pub_time,
                heat_level=heat,
                status="active",
                last_comment_count=vd.comment_count,
            )
            db.add(video_obj)
            synced_count += 1
        else:
            # 更新已有视频
            video_obj.title = vd.title
            video_obj.publish_time = pub_time
            # heat_level 由四档轮询策略维护，同步作品列表时不覆盖

            if not is_within_lifecycle:
                if video_obj.status != "expired":
                    video_obj.status = "expired"
                    expired_count += 1
            elif video_obj.status == "expired":
                video_obj.status = "active"

            video_obj.last_comment_count = vd.comment_count

    await db.flush()

    # 3. 将本账号下超出生命周期的旧视频标记 expired
    old_videos_result = await db.execute(
        select(Video).where(
            Video.monitor_account_id == monitor_account_id,
            Video.status != "expired",
            Video.publish_time < lifecycle_cutoff,
        )
    )
    for old_video in old_videos_result.scalars().all():
        old_video.status = "expired"
        expired_count += 1
    await db.flush()

    # 4. 只保留发布时间最新的N条视频为active(默认只监控最新一条)
    await _apply_active_video_limit(db, monitor_account_id, settings.ACCOUNT_ACTIVE_VIDEO_LIMIT)
    await db.flush()

    result_info = {
        "status": "ok",
        "monitor_id": monitor_account_id,
        "synced": synced_count,
        "expired": expired_count,
        "total_videos": len(video_dtos),
    }
    logger.info("sync_account_videos result for account %d: %s", monitor_account_id, result_info)
    return result_info


def should_poll_video(video: Video, polling_config) -> bool:
    """按四档轮询间隔判断是否到期。"""
    from app.services.polling_strategy import normalize_tier

    if video.status != "active":
        return False
    if video.last_poll_time is None:
        return True
    interval_min = polling_config.interval_minutes(normalize_tier(video.heat_level))
    now = datetime.now(timezone.utc)
    last_poll = video.last_poll_time
    if last_poll.tzinfo is None:
        last_poll = last_poll.replace(tzinfo=timezone.utc)
    elapsed = (now - last_poll).total_seconds()
    return elapsed >= interval_min * 60


async def _fetch_new_comments_by_dedup(
    db: AsyncSession,
    adapter,
    video_id: str,
    time_boundary: datetime | None,
) -> tuple[list[CommentDTO], int]:
    """
    按页拉取评论，逐条与数据库中已有的comment_id比对，收集新评论：
    - TikHub该接口不支持按时间排序，实测返回顺序是热度/综合排序而非时间倒序，
      所以不能假设"遇到已存在的评论id => 后面全是旧评论"，否则一旦有条老评论
      因为点赞多长期占据靠前位置，排在它后面的新评论会被永久跳过、再也拉不到。
    - 因此每一页都做全量去重比对，不因为命中已存在的id而提前终止翻页，
      只根据接口的has_more/最大页数(SENTIMENT_MAX_PAGES)决定是否继续。
    - time_boundary非空时(首次轮询)，只是过滤掉超出范围的评论，同样不提前终止翻页。
    - 相邻两页之间如因接口游标重叠返回了重复评论，只保留一份，避免入库时唯一键冲突

    返回 (新评论列表, 实际请求的页数)。
    """
    cursor = 0
    new_comments: list[CommentDTO] = []
    seen_ids: set[str] = set()
    pages_fetched = 0

    for _ in range(settings.SENTIMENT_MAX_PAGES):
        page = await adapter.fetch_comments_page(video_id, cursor, settings.COMMENT_PAGE_SIZE)
        pages_fetched += 1
        await QuotaService.increment_api_call("comment_api")

        if not page.comments:
            break

        page_ids = [c.comment_id for c in page.comments]
        existing_result = await db.execute(
            select(Comment.comment_id).where(Comment.comment_id.in_(page_ids))
        )
        existing_ids = set(row[0] for row in existing_result.all())

        for c in page.comments:
            if c.comment_id in existing_ids or c.comment_id in seen_ids:
                continue
            comment_time = c.comment_time if c.comment_time.tzinfo else c.comment_time.replace(tzinfo=timezone.utc)
            if time_boundary and comment_time < time_boundary:
                continue
            new_comments.append(c)
            seen_ids.add(c.comment_id)

        if not page.has_more:
            break
        cursor = page.next_cursor

    return new_comments, pages_fetched


async def poll_video_comments(db: AsyncSession, video_db_id: int) -> dict:
    """
    对单个视频执行评论轮询：
    - 检查所属监控账号是否为 active(账号已暂停/移出等非active状态时跳过，不再抓取评论)
    - 检查视频是否过期（发布超 VIDEO_LIFECYCLE_DAYS 天 → 标记 expired, 跳过）
    - 检查是否到了轮询间隔：优先使用所属监控账号自定义的 MonitorAccount.poll_interval_min
      (监控管理列表"设置拉取间隔")，未设置时回退到全局默认 VIDEO_POLL_INTERVAL_MINUTES
    - 按页拉取评论，与库内comment_id逐条比对找出新评论(见 _fetch_new_comments_by_dedup，
      接口返回顺序非时间倒序，不能靠"遇到已存在id"提前停止翻页)
    - 新评论一律入库去重；发布时间在账号自定义的 MonitorAccount.ai_freshness_min 分钟内才标记为
      待AI分析，超时只入库不分析(未设置时回退到全局默认 COMMENT_AI_FRESHNESS_MINUTES)
    - 首次轮询(last_poll_time为空)另外用 FIRST_POLL_BACKFILL_HOURS 限定回溯范围，避免历史评论过多导致翻页过深
    """
    # 1. 获取视频记录
    result = await db.execute(
        select(Video).where(Video.id == video_db_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        logger.warning("poll_video_comments: Video id=%d not found, skip", video_db_id)
        return {"status": "not_found", "video_id": video_db_id}

    # 所属监控账号状态与自定义的拉取间隔/意向时效窗口，用于替代全局固定配置
    account_row = (
        await db.execute(
            select(MonitorAccount.status, MonitorAccount.poll_interval_min, MonitorAccount.ai_freshness_min)
            .where(MonitorAccount.id == video.monitor_account_id)
        )
    ).first()
    if not account_row or account_row[0] != "active":
        return {
            "status": "skipped",
            "video_id": video.video_id,
            "reason": f"account_status={account_row[0] if account_row else 'not_found'}",
        }
    ai_freshness_min = (
        account_row[2] if account_row[2] and account_row[2] > 0
        else settings.COMMENT_AI_FRESHNESS_MINUTES
    )

    now = datetime.now(timezone.utc)

    # 2. 生命周期检查：发布超期 → 标记 expired
    lifecycle_cutoff = now - timedelta(days=settings.VIDEO_LIFECYCLE_DAYS)
    if video.publish_time:
        pub_time = video.publish_time
        if pub_time.tzinfo is None:
            pub_time = pub_time.replace(tzinfo=timezone.utc)
        if pub_time < lifecycle_cutoff:
            video.status = "expired"
            await db.flush()
            logger.info("Video %s expired (published %s)", video.video_id, pub_time)
            return {"status": "expired", "video_id": video.video_id}

    # 3. 状态检查
    if video.status != "active":
        return {"status": "skipped", "video_id": video.video_id, "reason": f"status={video.status}"}

    # 4. 检查是否到了轮询时间
    from app.services.polling_runtime import load_polling_config, incr_poll_call
    from app.services.polling_strategy import (
        VideoPollingState,
        apply_crawl_result,
        normalize_tier,
    )
    polling_config = await load_polling_config(db)
    if not should_poll_video(video, polling_config):
        return {"status": "not_due", "video_id": video.video_id}

    # 5. 检查评论接口配额
    comment_available, comment_rate = await QuotaService.check_quota("comment_api")
    if not comment_available:
        logger.warning("Comment API quota exceeded (%.1f%%), skip poll for video %s", comment_rate, video.video_id)
        return {"status": "quota_exceeded", "video_id": video.video_id, "api_type": "comment_api", "usage_rate": comment_rate}

    # 6. 首次轮询额外限定回溯范围
    is_first_poll = video.last_poll_time is None
    time_boundary = now - timedelta(hours=settings.FIRST_POLL_BACKFILL_HOURS) if is_first_poll else None

    # 7. 分页拉取新评论(遇到已存在的评论id即停止翻页)
    adapter = get_sentiment_adapter()
    t0 = time.monotonic()
    try:
        raw_comments, pages_fetched = await _fetch_new_comments_by_dedup(
            db, adapter, video.video_id, time_boundary,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await log_api_call(
            "comment_api", "fetch_comments_page",
            {"video_id": video.video_id, "pages": pages_fetched, "first_poll": is_first_poll},
            200, elapsed_ms, True,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await QuotaService.increment_api_call("comment_api")
        await log_api_call(
            "comment_api", "fetch_comments_page",
            {"video_id": video.video_id, "first_poll": is_first_poll},
            500, elapsed_ms, False, str(exc),
        )
        logger.error("poll_video_comments: Failed to fetch comments for video %s: %s", video.video_id, exc)
        await _alert_on_adapter_error(db, "comment_api", f"poll_video_comments video={video.video_id}", exc)
        return {"status": "error", "video_id": video.video_id, "error": str(exc)}

    # 8. 过滤无效评论(纯emoji/太短/纯标点)，按发布时间新鲜度决定是否送AI
    valid_comments = [c for c in raw_comments if _is_valid_comment(c.content)]

    new_saved = 0
    ai_eligible_count = 0
    for c in valid_comments:
        comment_time = c.comment_time if c.comment_time.tzinfo else c.comment_time.replace(tzinfo=timezone.utc)
        age_minutes = (now - comment_time).total_seconds() / 60
        ai_eligible = age_minutes <= ai_freshness_min

        comment_obj = Comment(
            video_id=video.id,
            comment_id=c.comment_id,
            user_uid=c.user_uid,
            user_nickname=c.user_nickname,
            content=c.content,
            comment_time=c.comment_time,
            is_processed=not ai_eligible,  # 超过新鲜度窗口的评论只入库,不送AI分析
        )
        db.add(comment_obj)
        new_saved += 1
        if ai_eligible:
            ai_eligible_count += 1

    # 9. 更新轮询时间与四档状态
    video.last_poll_time = now
    video.last_crawled_at = now
    total_comments = video.last_comment_count + new_saved
    state = VideoPollingState(
        video_id=video.video_id,
        tier=normalize_tier(video.heat_level),
        consecutive_no_new=video.zero_comment_streak,
        poll_count=video.tier_poll_count,
        last_known_comment_count=video.last_comment_count,
    )
    old_tier = state.tier
    apply_crawl_result(state, polling_config, new_saved, total_comments)
    video.heat_level = state.tier.value
    video.zero_comment_streak = state.consecutive_no_new
    video.tier_poll_count = state.poll_count
    video.last_comment_count = state.last_known_comment_count
    await incr_poll_call(old_tier)
    await db.flush()

    result_info = {
        "status": "ok",
        "video_id": video.video_id,
        "fetched": len(raw_comments),
        "saved": new_saved,
        "ai_eligible": ai_eligible_count,
        "pages_fetched": pages_fetched,
        "first_poll": is_first_poll,
    }
    logger.info("poll_video_comments result for video %s: %s", video.video_id, result_info)
    return result_info
