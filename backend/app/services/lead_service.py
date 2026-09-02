"""线索管理服务 — CRUD、分配、状态流转、跟进记录。"""
import datetime
import logging
from typing import Optional, List

from sqlalchemy import select, and_, exists, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadFollowup
from app.models.chat import ChatMessage
from app.models.comment import Comment
from app.models.video import Video
from app.models.monitor import MonitorAccount
from app.core.roles import ROLE_ADMIN, ROLE_CUSTOMER_SERVICE
from app.models.user import User

logger = logging.getLogger(__name__)

# ── 状态流转规则 ────────────────────────────────────────────────────────────────
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"assigned", "closed"},
    "assigned": {"following"},
    "following": {"converted", "closed"},
    "converted": set(),
    "closed": set(),
}


def _check_transition(current: str, target: str, is_admin: bool) -> bool:
    """检查状态流转是否合法。admin 可从 pending 直接关闭。"""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target in allowed:
        return True
    # admin 特权：任意状态 → closed
    if is_admin and target == "closed":
        return True
    return False


# ── 线索列表 ────────────────────────────────────────────────────────────────────

async def get_leads(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    assigned_to: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    current_user=None,
) -> dict:
    """
    获取线索列表(分页+筛选)。
    admin 看全部；客服只看自己被分配的。
    """
    conditions = []

    if current_user and current_user.role == ROLE_CUSTOMER_SERVICE:
        conditions.append(Lead.assigned_to == current_user.id)

    if status:
        conditions.append(Lead.status == status)
    if assigned_to is not None:
        conditions.append(Lead.assigned_to == assigned_to)
    if search:
        conditions.append(Lead.user_nickname.ilike(f"%{search}%"))
    if start_date:
        conditions.append(Lead.created_at >= datetime.datetime.fromisoformat(start_date))
    if end_date:
        conditions.append(Lead.created_at <= datetime.datetime.fromisoformat(end_date + "T23:59:59"))

    where_clause = and_(*conditions) if conditions else True  # type: ignore

    # 总数
    count_stmt = select(func.count(Lead.id)).where(where_clause)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    has_communicated = exists(
        select(ChatMessage.id).where(
            ChatMessage.lead_id == Lead.id,
            ChatMessage.direction == "outbound",
            ChatMessage.status != "failed",
            Lead.assigned_at.is_not(None),
            ChatMessage.sent_at >= Lead.assigned_at,
        )
    )

    # 分页查询，关联查询评论、视频、分配人和沟通状态
    stmt = (
        select(
            Lead,
            Comment.content,
            Comment.comment_time,
            Video.title,
            User.username,
            has_communicated.label("has_communicated"),
        )
        .outerjoin(Comment, Lead.comment_id == Comment.id)
        .outerjoin(Video, Lead.video_id == Video.id)
        .outerjoin(User, Lead.assigned_to == User.id)
        .where(where_clause)
        .order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    data = []
    for row in rows:
        lead = row[0]
        comment_content = row[1]
        comment_time = row[2]
        video_title = row[3]
        assigned_name = row[4]
        communicated = row[5]
        data.append({
            "id": lead.id,
            "comment_id": lead.comment_id,
            "video_id": lead.video_id,
            "user_uid": lead.user_uid,
            "user_nickname": lead.user_nickname,
            "user_avatar": lead.user_avatar,
            "ai_reason": lead.ai_reason,
            "status": lead.status,
            "chat_status": lead.chat_status,
            "assigned_to": lead.assigned_to,
            "assigned_to_name": assigned_name,
            "assigned_at": lead.assigned_at,
            "created_at": lead.created_at,
            "comment_content": comment_content or "",
            "comment_time": comment_time,
            "video_title": video_title or "",
            "has_communicated": bool(communicated),
        })

    return {"data": data, "total": total, "page": page, "page_size": page_size}


# ── 线索详情 ────────────────────────────────────────────────────────────────────

async def get_lead_detail(db: AsyncSession, lead_id: int) -> Optional[dict]:
    """获取线索详情(含原评论、视频信息、监控账号、跟进记录)"""
    has_communicated = exists(
        select(ChatMessage.id).where(
            ChatMessage.lead_id == Lead.id,
            ChatMessage.direction == "outbound",
            ChatMessage.status != "failed",
            Lead.assigned_at.is_not(None),
            ChatMessage.sent_at >= Lead.assigned_at,
        )
    )
    stmt = (
        select(
            Lead,
            Comment.content,
            Comment.comment_time,
            Video.title,
            MonitorAccount.nickname,
            has_communicated.label("has_communicated"),
        )
        .outerjoin(Comment, Lead.comment_id == Comment.id)
        .outerjoin(Video, Lead.video_id == Video.id)
        .outerjoin(MonitorAccount, Video.monitor_account_id == MonitorAccount.id)
        .where(Lead.id == lead_id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        return None

    lead = row[0]
    comment_content = row[1]
    comment_time = row[2]
    video_title = row[3]
    monitor_name = row[4]
    communicated = row[5]

    # 获取分配人名称
    assigned_to_name = None
    if lead.assigned_to:
        u_result = await db.execute(select(User.username).where(User.id == lead.assigned_to))
        assigned_to_name = u_result.scalar_one_or_none()

    # 跟进记录
    followups = await get_followups(db, lead_id)

    return {
        "id": lead.id,
        "comment_id": lead.comment_id,
        "video_id": lead.video_id,
        "user_uid": lead.user_uid,
        "user_nickname": lead.user_nickname,
        "user_avatar": lead.user_avatar,
        "ai_reason": lead.ai_reason,
        "status": lead.status,
        "chat_status": lead.chat_status,
        "assigned_to": lead.assigned_to,
        "assigned_to_name": assigned_to_name,
        "assigned_at": lead.assigned_at,
        "created_at": lead.created_at,
        "comment_content": comment_content or "",
        "comment_time": comment_time,
        "video_title": video_title or "",
        "has_communicated": bool(communicated),
        "monitor_account_name": monitor_name or "",
        "followups": followups,
    }


# ── 分配 ────────────────────────────────────────────────────────────────────────

async def assign_lead(
    db: AsyncSession,
    lead_id: int,
    user_id: int,
    operator_id: int,
) -> Optional[dict]:
    """手动分配线索给客服"""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return None

    u_result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.role == ROLE_CUSTOMER_SERVICE,
            User.status == "active",
        )
    )
    target_user = u_result.scalar_one_or_none()
    if not target_user:
        return {"error": "目标客服不存在或已禁用"}

    lead.assigned_to = user_id
    lead.assigned_at = datetime.datetime.now(datetime.timezone.utc)

    # 状态流转：pending → assigned
    if lead.status == "pending":
        lead.status = "assigned"

    # 记录跟进
    followup = LeadFollowup(
        lead_id=lead_id,
        operator_id=operator_id,
        action="assign",
        content=f"分配给 {target_user.username}",
    )
    db.add(followup)
    await db.flush()
    return {"id": lead.id, "assigned_to": lead.assigned_to, "status": lead.status}


async def batch_assign_leads(
    db: AsyncSession,
    lead_ids: List[int],
    user_id: int,
    operator_id: int,
) -> dict:
    """批量分配线索"""
    u_result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.role == ROLE_CUSTOMER_SERVICE,
            User.status == "active",
        )
    )
    target_user = u_result.scalar_one_or_none()
    if not target_user:
        return {"error": "目标客服不存在或已禁用"}

    now = datetime.datetime.now(datetime.timezone.utc)
    count = 0
    for lid in lead_ids:
        result = await db.execute(select(Lead).where(Lead.id == lid))
        lead = result.scalar_one_or_none()
        if lead and lead.status in ("pending", "assigned"):
            lead.assigned_to = user_id
            lead.assigned_at = now
            if lead.status == "pending":
                lead.status = "assigned"
            followup = LeadFollowup(
                lead_id=lid,
                operator_id=operator_id,
                action="assign",
                content=f"批量分配给 {target_user.username}",
            )
            db.add(followup)
            count += 1

    await db.flush()
    return {"assigned_count": count}


async def auto_assign_leads(db: AsyncSession, operator_id: int) -> dict:
    """
    将未分配线索均衡分配给所有启用的普通客服。
    """
    sales_result = await db.execute(
        select(User).where(User.role == ROLE_CUSTOMER_SERVICE, User.status == "active")
    )
    sales_list = list(sales_result.scalars().all())
    if not sales_list:
        return {"error": "没有可用的客服人员", "assigned_count": 0}

    # 统计每个销售当前已分配的线索数量
    count_stmt = (
        select(Lead.assigned_to, func.count(Lead.id))
        .where(Lead.assigned_to.isnot(None))
        .group_by(Lead.assigned_to)
    )
    count_result = await db.execute(count_stmt)
    count_map = {row[0]: row[1] for row in count_result.all()}

    sales_sorted = sorted(sales_list, key=lambda u: (count_map.get(u.id, 0), u.id))

    # 获取所有 pending 且未分配的线索
    pending_result = await db.execute(
        select(Lead).where(Lead.status == "pending", Lead.assigned_to.is_(None)).order_by(Lead.created_at)
    )
    pending_leads = list(pending_result.scalars().all())

    now = datetime.datetime.now(datetime.timezone.utc)
    count = 0
    for i, lead in enumerate(pending_leads):
        target = sales_sorted[i % len(sales_sorted)]
        lead.assigned_to = target.id
        lead.assigned_at = now
        lead.status = "assigned"
        followup = LeadFollowup(
            lead_id=lead.id,
            operator_id=operator_id,
            action="assign",
            content=f"自动分配给 {target.username}",
        )
        db.add(followup)
        count += 1

    await db.flush()
    return {"assigned_count": count, "sales_count": len(sales_sorted)}


# ── 状态流转 ────────────────────────────────────────────────────────────────────

async def update_lead_status(
    db: AsyncSession,
    lead_id: int,
    new_status: str,
    operator_id: int,
    is_admin: bool = False,
) -> Optional[dict]:
    """更新线索状态(带流转规则校验)"""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return None

    if not _check_transition(lead.status, new_status, is_admin):
        return {"error": f"不允许从 {lead.status} 流转到 {new_status}"}

    old_status = lead.status
    lead.status = new_status

    # 状态中文映射
    status_labels = {
        "pending": "待分配", "assigned": "已分配", "following": "跟进中",
        "converted": "已转化", "closed": "已关闭",
    }
    followup = LeadFollowup(
        lead_id=lead_id,
        operator_id=operator_id,
        action="status_change",
        content=f"{status_labels.get(old_status, old_status)} → {status_labels.get(new_status, new_status)}",
    )
    db.add(followup)
    await db.flush()
    return {"id": lead.id, "status": lead.status}


# ── 跟进记录 ────────────────────────────────────────────────────────────────────

async def add_followup(
    db: AsyncSession,
    lead_id: int,
    operator_id: int,
    action: str = "note",
    content: str = "",
) -> Optional[dict]:
    """添加跟进记录"""
    # 验证线索存在
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return None

    followup = LeadFollowup(
        lead_id=lead_id,
        operator_id=operator_id,
        action=action,
        content=content,
    )
    db.add(followup)
    await db.flush()
    return {
        "id": followup.id,
        "lead_id": followup.lead_id,
        "operator_id": followup.operator_id,
        "action": followup.action,
        "content": followup.content,
        "created_at": followup.created_at,
    }


async def get_followups(db: AsyncSession, lead_id: int) -> List[dict]:
    """获取线索的跟进历史(含操作人名称)"""
    stmt = (
        select(LeadFollowup, User.username)
        .outerjoin(User, LeadFollowup.operator_id == User.id)
        .where(LeadFollowup.lead_id == lead_id)
        .order_by(LeadFollowup.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": row[0].id,
            "lead_id": row[0].lead_id,
            "operator_id": row[0].operator_id,
            "operator_name": row[1] or "系统",
            "action": row[0].action,
            "content": row[0].content,
            "created_at": row[0].created_at,
        }
        for row in rows
    ]


# ── 转人工 & 标记无效 ────────────────────────────────────────────────────────

async def transfer_to_human(
    db: AsyncSession,
    lead_id: int,
    sales_user_id: int,
    operator_id: int,
) -> Optional[dict]:
    """将线索转为人工服务状态"""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return None

    u_result = await db.execute(
        select(User).where(
            User.id == sales_user_id,
            User.role == ROLE_CUSTOMER_SERVICE,
            User.status == "active",
        )
    )
    sales_user = u_result.scalar_one_or_none()
    if not sales_user:
        return {"error": "客服人员不存在或已禁用"}

    # 更新 chat_status 和线索状态
    lead.chat_status = 1  # 人工服务
    if lead.status == "pending":
        lead.status = "assigned"
    lead.assigned_to = sales_user_id
    if not lead.assigned_at:
        lead.assigned_at = datetime.datetime.now(datetime.timezone.utc)

    # 记录跟进
    followup = LeadFollowup(
        lead_id=lead_id,
        operator_id=operator_id,
        action="status_change",
        content=f"转为人工服务，分配给 {sales_user.username}",
    )
    db.add(followup)
    await db.flush()
    return {"id": lead.id, "chat_status": lead.chat_status, "status": lead.status, "assigned_to": lead.assigned_to}
