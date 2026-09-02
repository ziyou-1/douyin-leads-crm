"""意向识别服务 — 批量分析评论并自动创建线索。"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_llm_adapter
from app.adapters.llm_base import IntentLevel, IntentResult
from app.core.config import settings
from app.models.comment import Comment
from app.models.lead import Lead
from app.models.monitor import MonitorAccount
from app.models.user import User
from app.models.video import Video
from app.core.roles import ROLE_CUSTOMER_SERVICE

logger = logging.getLogger(__name__)

# 每批处理的最大评论数
BATCH_SIZE = 50
ASSIGNMENT_LOCK_KEY = 20260827


async def process_unanalyzed_comments(db: AsyncSession, limit: int = BATCH_SIZE) -> dict:
    """
    处理未分析的评论:
    1. 查询is_processed=False的评论
    2. 批量调用LLM适配器分析
    3. high → 创建Lead(每条高意向评论都单独生成一条线索，不做同用户去重); invalid → 仅标记已处理
       创建Lead时按评论发布距分析时刻的间隔二次分级为 high/medium (见_resolve_lead_intent_level)
    4. 更新comment.is_processed = True
    5. 分配客服时，同一用户优先继续分配给上次跟进的客服，避免多个客服重复跟进同一个人
    """
    # 查询未处理的评论
    stmt = (
        select(Comment)
        .where(Comment.is_processed == False)  # noqa: E712
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    result = await db.execute(stmt)
    comments = list(result.scalars().all())

    if not comments:
        return {"processed": 0, "leads_created": 0, "lead_ids": []}

    # 预加载视频标题信息 (video_id → title)
    video_ids = list({c.video_id for c in comments})
    video_map: dict[int, str] = {}
    if video_ids:
        vresult = await db.execute(select(Video.id, Video.title).where(Video.id.in_(video_ids)))
        for row in vresult.all():
            video_map[row[0]] = row[1]

    # 构造LLM输入
    llm_comments = []
    for c in comments:
        llm_comments.append({
            "comment_id": str(c.id),
            "content": c.content,
            "video_title": video_map.get(c.video_id, ""),
        })

    # 调用LLM批量分析
    adapter = get_llm_adapter()
    try:
        intent_results = await adapter.batch_analyze_intent(llm_comments)
    except Exception as exc:
        logger.error("LLM batch analysis failed: %s", exc)
        raise

    # 构建comment.id → IntentResult映射
    result_map: dict[int, IntentResult] = {}
    for ir in intent_results:
        try:
            result_map[int(ir.comment_id)] = ir
        except (ValueError, TypeError):
            logger.warning("Invalid comment_id in IntentResult: %s", ir.comment_id)

    leads_created = 0
    lead_ids_created: list[int] = []
    processed = 0
    for comment in comments:
        ir = result_map.get(comment.id)
        if ir is None:
            continue

        comment.is_processed = True
        processed += 1

        # high → 每条都单独创建线索(不做同用户/同视频去重)
        if ir.intent_level == IntentLevel.HIGH:
            lead = await create_lead_from_intent(db, comment, ir)
            if lead:
                leads_created += 1
                lead_ids_created.append(lead.id)

    await db.flush()

    logger.info(
        "Intent analysis complete: processed=%d, leads_created=%d",
        processed, leads_created,
    )
    return {
        "processed": processed,
        "leads_created": leads_created,
        "lead_ids": lead_ids_created,
    }


async def analyze_single_comment(db: AsyncSession, comment_id: int) -> Optional[dict]:
    """重新分析单条评论(管理员手动触发)"""
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        return None

    # 获取视频标题
    vresult = await db.execute(select(Video.title).where(Video.id == comment.video_id))
    video_title = vresult.scalar_one_or_none() or ""

    adapter = get_llm_adapter()
    try:
        ir = await adapter.analyze_intent(
            comment.content,
            context={"comment_id": str(comment.id), "video_title": video_title},
        )
    except Exception as exc:
        logger.error("LLM single analysis failed for comment %d: %s", comment_id, exc)
        return {"error": f"AI分析失败: {exc}"}

    # 删除这条评论自己之前生成的旧线索(重新分析同一条评论时替换掉旧结果)
    old_result = await db.execute(
        select(Lead).where(and_(
            Lead.comment_id == comment.id,
            Lead.video_id == comment.video_id,
        ))
    )
    old_lead = old_result.scalar_one_or_none()
    if old_lead:
        await db.delete(old_lead)
        await db.flush()

    lead = None
    if ir.intent_level == IntentLevel.HIGH:
        lead = await create_lead_from_intent(db, comment, ir)

    comment.is_processed = True
    await db.flush()

    return {
        "comment_id": comment.id,
        "intent_level": ir.intent_level.value,
        "reason": ir.reason,
        "confidence": ir.confidence,
        "lead_created": lead is not None,
        "lead_id": lead.id if lead else None,
    }


async def _resolve_lead_intent_level(db: AsyncSession, comment: Comment) -> str:
    """按评论发布距当前(送AI分析完成)的间隔，二次分级AI判定的高意向评论：
    评论所属监控账号自定义的 MonitorAccount.high_intent_min(默认8分钟)内为high，
    超过(但仍在该账号 ai_freshness_min 新鲜度窗口内，才会走到这里)记为medium。
    账号未关联到时回退全局默认 LEAD_HIGH_INTENT_MINUTES。"""
    if not comment.comment_time:
        return "high"
    comment_time = comment.comment_time
    if comment_time.tzinfo is None:
        comment_time = comment_time.replace(tzinfo=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - comment_time).total_seconds() / 60

    high_intent_min = settings.LEAD_HIGH_INTENT_MINUTES
    if comment.video_id:
        row = (
            await db.execute(
                select(MonitorAccount.high_intent_min)
                .join(Video, Video.monitor_account_id == MonitorAccount.id)
                .where(Video.id == comment.video_id)
            )
        ).first()
        if row and row[0]:
            high_intent_min = row[0]

    return "high" if age_minutes <= high_intent_min else "medium"


async def create_lead_from_intent(
    db: AsyncSession,
    comment: Comment,
    intent_result: IntentResult,
) -> Optional[Lead]:
    """根据意向分析结果创建Lead记录

    分配客服时优先延续该用户上次的跟进客服(见_get_preferred_customer_service)，
    避免同一个人的多条线索被分给不同客服，导致重复跟进。
    """
    customer_service = await _get_preferred_customer_service(db, comment.user_uid)
    if customer_service is None:
        customer_service = await _get_least_loaded_customer_service(db)
    assigned_at = datetime.now(timezone.utc) if customer_service else None
    intent_level = await _resolve_lead_intent_level(db, comment)
    lead = Lead(
        comment_id=comment.id,
        video_id=comment.video_id,
        user_uid=comment.user_uid,
        user_nickname=comment.user_nickname,
        user_avatar="",
        ai_reason=intent_result.reason,
        intent_level=intent_level,
        status="assigned" if customer_service else "pending",
        assigned_to=customer_service.id if customer_service else None,
        assigned_at=assigned_at,
    )
    db.add(lead)
    await db.flush()

    # high意向时同步更新对应monitor_account的统计
    if intent_result.intent_level == IntentLevel.HIGH:
        await _update_monitor_account_high_stats(db, comment.video_id)

    return lead


async def _get_preferred_customer_service(
    db: AsyncSession,
    user_uid: str,
) -> Optional[User]:
    """如果该用户之前已经有线索分配给某个在职客服，优先继续分配给同一个客服(跨视频/跨账号)，
    避免同一个人的多条高意向线索被分配给不同客服重复跟进。"""
    result = await db.execute(
        select(User)
        .join(Lead, Lead.assigned_to == User.id)
        .where(
            Lead.user_uid == user_uid,
            Lead.assigned_to.is_not(None),
            User.status == "active",
        )
        .order_by(Lead.assigned_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_least_loaded_customer_service(
    db: AsyncSession,
) -> Optional[User]:
    await db.execute(select(func.pg_advisory_xact_lock(ASSIGNMENT_LOCK_KEY)))
    result = await db.execute(
        select(User)
        .outerjoin(Lead, Lead.assigned_to == User.id)
        .where(
            User.role == ROLE_CUSTOMER_SERVICE,
            User.status == "active",
        )
        .group_by(User.id)
        .order_by(func.count(Lead.id).asc(), User.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def assign_unassigned_leads(db: AsyncSession) -> int:
    result = await db.execute(
        select(Lead)
        .where(Lead.status == "pending", Lead.assigned_to.is_(None))
        .order_by(Lead.created_at.asc(), Lead.id.asc())
        .with_for_update(skip_locked=True)
    )
    leads = list(result.scalars().all())
    assigned_count = 0

    for lead in leads:
        customer_service = await _get_preferred_customer_service(db, lead.user_uid)
        if customer_service is None:
            customer_service = await _get_least_loaded_customer_service(db)
        if customer_service is None:
            break
        lead.assigned_to = customer_service.id
        lead.assigned_at = datetime.now(timezone.utc)
        lead.status = "assigned"
        await db.flush()
        assigned_count += 1

    return assigned_count


async def _update_monitor_account_high_stats(db: AsyncSession, video_id: int):
    """更新对应monitor_account的high评论统计

    通过 comment.video_id -> Video.monitor_account_id -> MonitorAccount 追溯
    """
    vresult = await db.execute(select(Video).where(Video.id == video_id))
    video = vresult.scalar_one_or_none()
    if not video or not video.monitor_account_id:
        return

    mresult = await db.execute(
        select(MonitorAccount).where(MonitorAccount.id == video.monitor_account_id)
    )
    account = mresult.scalar_one_or_none()
    if not account:
        return

    account.last_high_intent_at = datetime.now(timezone.utc)
    account.total_high_count += 1
    await db.flush()


async def get_intent_stats(db: AsyncSession) -> dict:
    """按意向级别统计线索数量。"""
    result = await db.execute(
        select(Lead.intent_level, func.count(Lead.id)).group_by(Lead.intent_level)
    )
    counts = {level: n for level, n in result.all()}
    return {
        "high": counts.get("high", 0),
        "medium": counts.get("medium", 0),
        "low": counts.get("low", 0),
        "invalid": counts.get("invalid", 0),
        "total": sum(counts.values()),
    }
