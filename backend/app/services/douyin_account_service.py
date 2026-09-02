"""Douyin chat account management service."""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitor import DouyinChatAccount
from app.models.user import User
from app.core.config import settings
from app.services.douyin_automation import automation


logger = logging.getLogger(__name__)


async def _refresh_login_status(account: DouyinChatAccount) -> str:
    try:
        is_valid = await automation.check_session_valid(account.cookie_data)
    except Exception as exc:
        logger.warning(
            "Failed to validate Douyin account session account_id=%s: %s",
            account.id,
            exc,
        )
        is_valid = False

    account.login_status = "online" if is_valid else "expired"
    account.last_active_at = datetime.now(timezone.utc)
    return account.login_status


async def add_account(
    db: AsyncSession,
    douyin_uid: str,
    nickname: str,
    cookie_data: str,
    assigned_to: Optional[int] = None,
    proxy_url: str = "",
    nurture_enabled: bool = False,
) -> Tuple[DouyinChatAccount, bool]:
    """新增抖音私信账号。同一个douyin_uid如果已经存在(比如账号cookie过期后
    重新扫码登录刷新)，直接更新已有记录的cookie_data，而不是报唯一键冲突
    错误，因为"重新扫码登录同一个账号刷新登录态"是完全合理的正常操作。
    返回(account, is_new)。
    """
    existing = (
        await db.execute(
            select(DouyinChatAccount).where(DouyinChatAccount.douyin_uid == douyin_uid)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.nickname = nickname or existing.nickname
        existing.cookie_data = cookie_data
        existing.proxy_url = proxy_url
        existing.nurture_enabled = nurture_enabled
        existing.login_status = "offline"
        await db.flush()
        await _refresh_login_status(existing)
        await db.flush()
        if nurture_enabled:
            from app.services.auto_nurture_v2 import nurture_manager
            nurture_manager.register(existing.id, is_new=False)
            nurture_manager.persist()
        return existing, False

    account = DouyinChatAccount(
        douyin_uid=douyin_uid,
        nickname=nickname,
        cookie_data=cookie_data,
        proxy_url=proxy_url,
        nurture_enabled=nurture_enabled,
        assigned_to_user_id=assigned_to,
        login_status="offline",
    )
    db.add(account)
    await db.flush()
    await _refresh_login_status(account)
    await db.flush()
    if nurture_enabled:
        from app.services.auto_nurture_v2 import nurture_manager
        nurture_manager.register(account.id, is_new=True)
        nurture_manager.persist()
    return account, True


async def get_accounts(
    db: AsyncSession,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> List[dict]:
    """Get account list. Admin sees all, sales sees only assigned."""
    stmt = select(DouyinChatAccount, User.username).outerjoin(
        User, User.id == DouyinChatAccount.assigned_to_user_id
    )
    if not is_admin and user_id is not None:
        stmt = stmt.where(DouyinChatAccount.assigned_to_user_id == user_id)
    stmt = stmt.order_by(DouyinChatAccount.id.desc())

    result = await db.execute(stmt)
    rows = result.all()

    accounts = []
    for account, username in rows:
        accounts.append({
            "id": account.id,
            "douyin_uid": account.douyin_uid,
            "nickname": account.nickname,
            "login_status": account.login_status,
            "assigned_to_user_id": account.assigned_to_user_id,
            "assigned_to_username": username,
            "last_active_at": account.last_active_at,
            "created_at": account.created_at,
            "proxy_url": account.proxy_url,
            "nurture_enabled": account.nurture_enabled,
        })
    return accounts


async def get_account_by_id(db: AsyncSession, account_id: int) -> Optional[DouyinChatAccount]:
    result = await db.execute(
        select(DouyinChatAccount).where(DouyinChatAccount.id == account_id)
    )
    return result.scalar_one_or_none()


async def assign_account(db: AsyncSession, account_id: int, user_id: int) -> bool:
    """Assign account to a user, respecting the per-user limit."""
    # Check per-user limit
    count = await get_user_account_count(db, user_id)
    if count >= settings.MAX_ACCOUNTS_PER_USER:
        return False

    await db.execute(
        update(DouyinChatAccount)
        .where(DouyinChatAccount.id == account_id)
        .values(assigned_to_user_id=user_id)
    )
    await db.flush()
    return True


async def unassign_account(db: AsyncSession, account_id: int) -> None:
    """Remove account assignment."""
    await db.execute(
        update(DouyinChatAccount)
        .where(DouyinChatAccount.id == account_id)
        .values(assigned_to_user_id=None)
    )
    await db.flush()


async def update_cookie(db: AsyncSession, account_id: int, cookie_data: str) -> None:
    """Update cookie data for an account."""
    await db.execute(
        update(DouyinChatAccount)
        .where(DouyinChatAccount.id == account_id)
        .values(cookie_data=cookie_data, login_status="offline")
    )
    await db.flush()


async def check_login_status(db: AsyncSession, account_id: int) -> dict:
    """Check login validity via automation and update status."""
    account = await get_account_by_id(db, account_id)
    if not account:
        return {"status": "not_found"}

    new_status = await _refresh_login_status(account)
    await db.flush()

    return {"status": new_status, "douyin_uid": account.douyin_uid}


async def get_user_account_count(db: AsyncSession, user_id: int) -> int:
    """Get number of accounts assigned to a user."""
    result = await db.execute(
        select(func.count(DouyinChatAccount.id)).where(
            DouyinChatAccount.assigned_to_user_id == user_id
        )
    )
    return result.scalar() or 0


async def delete_account(db: AsyncSession, account_id: int) -> bool:
    """Delete an account."""
    result = await db.execute(
        delete(DouyinChatAccount).where(DouyinChatAccount.id == account_id)
    )
    await db.flush()
    return result.rowcount > 0


async def get_user_available_accounts(db: AsyncSession, user_id: int) -> List[DouyinChatAccount]:
    """Get accounts available for a user to send messages."""
    result = await db.execute(
        select(DouyinChatAccount).where(
            DouyinChatAccount.assigned_to_user_id == user_id,
            DouyinChatAccount.login_status != "expired",
        )
    )
    return list(result.scalars().all())


# ── 二维码登录(Playwright浏览器自动化) ────────────────────────────────────

async def start_qr_login() -> Tuple[str, str, int]:
    """打开浏览器扫码登录页，返回 (login_session_id, 二维码base64, 有效期秒数)"""
    session_id, qr_base64 = await automation.start_qr_login()
    return session_id, qr_base64, settings.PLAYWRIGHT_QR_LOGIN_TTL_SEC


async def poll_qr_login(login_session_id: str) -> dict:
    """轮询扫码登录状态。confirmed时附带storage_state供add_account保存。"""
    return await automation.poll_qr_login(login_session_id)


async def submit_qr_verification(login_session_id: str, code: str) -> dict:
    """提交异地登录二次验证的短信验证码。"""
    return await automation.submit_verification_code(login_session_id, code)
