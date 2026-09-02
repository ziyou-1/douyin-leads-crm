"""Chat messaging service with risk control and OpenKF integration."""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.models.lead import Lead
from app.models.monitor import DouyinChatAccount
from app.models.user import User
from app.core.config import settings
from app.core.roles import ROLE_CUSTOMER_SERVICE
from app.services.douyin_automation import automation
from app.services.openkf_service import openkf_service

logger = logging.getLogger(__name__)

# In-memory daily send counter (per account per day).
# In production this should be Redis-backed.
_daily_send_counts: dict = {}


def _today_key(account_id: int) -> str:
    return f"{account_id}:{datetime.now().strftime('%Y-%m-%d')}"


async def check_send_limit(douyin_account_id: int) -> dict:
    """Check if account has reached daily send limit."""
    key = _today_key(douyin_account_id)
    count = _daily_send_counts.get(key, 0)
    remaining = max(0, settings.DAILY_SEND_LIMIT - count)
    return {
        "account_id": douyin_account_id,
        "daily_limit": settings.DAILY_SEND_LIMIT,
        "sent_today": count,
        "remaining": remaining,
        "is_limited": remaining <= 0,
    }


def _is_work_hours() -> bool:
    """Check if current time is within working hours."""
    now = datetime.now()
    return settings.WORK_HOURS_START <= now.hour < settings.WORK_HOURS_END


async def send_message(
    db: AsyncSession,
    lead_id: int,
    douyin_account_id: int,
    content: str,
) -> dict:
    """Send a private message to a lead via OpenKF callback."""
    # Risk control: check daily limit
    limit_info = await check_send_limit(douyin_account_id)
    if limit_info["is_limited"]:
        return {"success": False, "error": "今日发送已达上限", "code": "DAILY_LIMIT"}

    # Risk control: work hours warning
    work_hours_warning = False
    if not _is_work_hours():
        work_hours_warning = True

    # Get lead info for target uid
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return {"success": False, "error": "线索不存在", "code": "LEAD_NOT_FOUND"}

    # 如果当前是AI托管，销售发消息时自动切换为人工服务
    switched_to_human = False
    if lead.chat_status == 2:
        lead.chat_status = 1  # 人工服务
        switched_to_human = True
        logger.info(
            "Lead %d auto-switched from AI to human service", lead_id,
        )

    # Get account
    result = await db.execute(
        select(DouyinChatAccount).where(DouyinChatAccount.id == douyin_account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        return {"success": False, "error": "抖音账号不存在", "code": "ACCOUNT_NOT_FOUND"}

    # Resolve chat_id: prefer lead.chat_id, then check chat_messages
    chat_id = lead.chat_id or await _get_chat_id_for_lead(db, lead_id)
    sender_id = account.douyin_uid if account else ""

    ext_msg_id = ""
    send_error = ""
    if settings.DOUYIN_AUTOMATION_MODE == "playwright":
        push_ok, send_error = await automation.send_private_message(
            cookie_data=account.cookie_data,
            target_uid=lead.user_uid,
            content=content,
            account_id=account.id,
            proxy_url=account.proxy_url,
        )
        # 发送成功后，同步这条人工消息给chatdoing，保持其会话上下文与真实聊天记录一致
        # (同步失败不影响本次发送结果，仅记录日志)
        if push_ok and chat_id and settings.OPENKF_CALLBACK_URL:
            try:
                _sync_ok, ext_msg_id = await openkf_service.push_message_to_chatdoing(
                    chat_id=chat_id,
                    sender_id=sender_id,
                    content=content,
                    msg_type=0,
                    chat_status=1,  # 人工服务
                )
                if not _sync_ok:
                    logger.warning(
                        "send_message: 同步OpenKF失败(不影响本次发送结果) lead_id=%d chat_id=%s",
                        lead_id, chat_id,
                    )
            except Exception as exc:
                logger.warning(
                    "send_message: 同步OpenKF异常(不影响本次发送结果) lead_id=%d: %s",
                    lead_id, exc,
                )
    else:
        push_ok = False
        if chat_id and settings.OPENKF_CALLBACK_URL:
            push_ok, ext_msg_id = await openkf_service.push_message_to_chatdoing(
                chat_id=chat_id,
                sender_id=sender_id,
                content=content,
            )
        if not push_ok:
            send_error = "OpenKF未配置或推送失败"

    # Save message record
    msg = ChatMessage(
        lead_id=lead_id,
        douyin_account_id=douyin_account_id,
        chat_id=chat_id,
        external_msg_id=ext_msg_id,
        direction="outbound",
        content=content,
        msg_type="text",
        status="sent" if push_ok else "failed",
    )
    db.add(msg)

    # Update daily count
    key = _today_key(douyin_account_id)
    _daily_send_counts[key] = _daily_send_counts.get(key, 0) + 1

    # Update account last active
    account.last_active_at = datetime.now(timezone.utc)

    # Update lead status to contacted
    if push_ok and lead.status == "assigned":
        lead.status = "following"

    await db.flush()

    return {
        "success": push_ok,
        "error": send_error if not push_ok else "",
        "message_id": msg.id if push_ok else None,
        "work_hours_warning": work_hours_warning,
        "remaining": settings.DAILY_SEND_LIMIT - _daily_send_counts[key],
        "switched_to_human": switched_to_human,
        "chat_status": lead.chat_status,
    }


async def get_messages(
    db: AsyncSession,
    lead_id: int,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Get paginated message history for a lead."""
    # Count total
    count_result = await db.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.lead_id == lead_id)
    )
    total = count_result.scalar() or 0

    # Fetch messages (newest first for pagination, but display oldest first)
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.lead_id == lead_id)
        .order_by(ChatMessage.sent_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return {
        "messages": [
            {
                "id": m.id,
                "lead_id": m.lead_id,
                "douyin_account_id": m.douyin_account_id,
                "direction": m.direction,
                "content": m.content,
                "msg_type": m.msg_type,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "status": m.status,
            }
            for m in messages
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_chat_sessions(
    db: AsyncSession,
    current_user,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
) -> dict:
    """Get paginated chat sessions.

    - customer_service: 只能看到分配给自己的线索 + AI托管中未分配的线索(共享池)
    - admin / customer_service_admin: 看到全部线索(不管是否已开始对话)，
      覆盖所有客服的AI自动跟进和人工会话记录
    """
    conditions = []

    if current_user.role == ROLE_CUSTOMER_SERVICE:
        conditions.append(
            or_(
                Lead.assigned_to == current_user.id,
                and_(Lead.chat_status == 2, Lead.assigned_to.is_(None)),
            )
        )
    # admin / customer_service_admin: 不加限制条件，展示全部意向线索

    if keyword:
        conditions.append(
            or_(
                Lead.user_nickname.ilike(f"%{keyword}%"),
                Lead.user_uid.ilike(f"%{keyword}%"),
            )
        )

    where_clause = and_(*conditions) if conditions else True

    count_result = await db.execute(select(func.count(Lead.id)).where(where_clause))
    total = count_result.scalar() or 0

    lead_result = await db.execute(
        select(Lead, User.username)
        .outerjoin(User, Lead.assigned_to == User.id)
        .where(where_clause)
        .order_by(Lead.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = lead_result.all()

    sessions = []
    for lead, assigned_to_name in rows:
        # Get last message for this lead
        msg_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.lead_id == lead.id)
            .order_by(ChatMessage.sent_at.desc())
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()

        # Count unread (inbound messages after last outbound)
        unread_count = 0
        if last_msg and last_msg.direction == "inbound":
            # Simple: count inbound messages that haven't been "read"
            unread_result = await db.execute(
                select(func.count(ChatMessage.id)).where(
                    and_(
                        ChatMessage.lead_id == lead.id,
                        ChatMessage.direction == "inbound",
                        ChatMessage.status != "read",
                    )
                )
            )
            unread_count = unread_result.scalar() or 0

        sessions.append({
            "lead_id": lead.id,
            "lead_nickname": lead.user_nickname,
            "lead_uid": lead.user_uid,
            "last_message": last_msg.content if last_msg else None,
            "last_message_at": last_msg.sent_at.isoformat() if last_msg and last_msg.sent_at else None,
            "unread_count": unread_count,
            "chat_status": lead.chat_status,
            "chat_id": lead.chat_id,
            "assigned_to": lead.assigned_to,
            "assigned_to_name": assigned_to_name,
        })

    return {
        "data": sessions,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_session_by_lead_id(
    db: AsyncSession, current_user, lead_id: int,
) -> Optional[dict]:
    """获取单个线索的会话摘要(用于从线索管理跳转到聊天页深链接定位，
    不受会话列表分页范围限制)。按角色校验访问权限。"""
    result = await db.execute(
        select(Lead, User.username)
        .outerjoin(User, Lead.assigned_to == User.id)
        .where(Lead.id == lead_id)
    )
    row = result.first()
    if not row:
        return None
    lead, assigned_to_name = row

    if current_user.role == ROLE_CUSTOMER_SERVICE:
        allowed = lead.assigned_to == current_user.id or (
            lead.chat_status == 2 and lead.assigned_to is None
        )
        if not allowed:
            return None

    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.lead_id == lead.id)
        .order_by(ChatMessage.sent_at.desc())
        .limit(1)
    )
    last_msg = msg_result.scalar_one_or_none()

    unread_count = 0
    if last_msg and last_msg.direction == "inbound":
        unread_result = await db.execute(
            select(func.count(ChatMessage.id)).where(
                and_(
                    ChatMessage.lead_id == lead.id,
                    ChatMessage.direction == "inbound",
                    ChatMessage.status != "read",
                )
            )
        )
        unread_count = unread_result.scalar() or 0

    return {
        "lead_id": lead.id,
        "lead_nickname": lead.user_nickname,
        "lead_uid": lead.user_uid,
        "last_message": last_msg.content if last_msg else None,
        "last_message_at": last_msg.sent_at.isoformat() if last_msg and last_msg.sent_at else None,
        "unread_count": unread_count,
        "chat_status": lead.chat_status,
        "chat_id": lead.chat_id,
        "assigned_to": lead.assigned_to,
        "assigned_to_name": assigned_to_name,
    }


async def _get_chat_id_for_lead(db: AsyncSession, lead_id: int) -> Optional[str]:
    """Get the OpenKF chat_id for a lead. Checks lead.chat_id first, then chat_messages."""
    # Check lead.chat_id field
    result = await db.execute(
        select(Lead.chat_id).where(Lead.id == lead_id)
    )
    lead_chat_id = result.scalar_one_or_none()
    if lead_chat_id:
        return lead_chat_id

    # Fallback: check chat_messages table
    msg_result = await db.execute(
        select(ChatMessage.chat_id)
        .where(ChatMessage.lead_id == lead_id)
        .where(ChatMessage.chat_id.isnot(None))
        .order_by(ChatMessage.sent_at.desc())
        .limit(1)
    )
    row = msg_result.first()
    return row[0] if row else None


async def receive_message(
    db: AsyncSession,
    lead_id: int,
    content: str,
) -> Optional[ChatMessage]:
    """Simulate receiving a message from a lead."""
    # Find any account associated with this lead's conversations
    result = await db.execute(
        select(ChatMessage.douyin_account_id)
        .where(ChatMessage.lead_id == lead_id)
        .order_by(ChatMessage.sent_at.desc())
        .limit(1)
    )
    row = result.first()
    account_id = row[0] if row else None

    if account_id is None:
        # Use first available account
        acc_result = await db.execute(
            select(DouyinChatAccount.id).limit(1)
        )
        acc_row = acc_result.first()
        if not acc_row:
            return None
        account_id = acc_row[0]

    msg = ChatMessage(
        lead_id=lead_id,
        douyin_account_id=account_id,
        direction="inbound",
        content=content,
        msg_type="text",
        status="delivered",
    )
    db.add(msg)
    await db.flush()
    return msg
