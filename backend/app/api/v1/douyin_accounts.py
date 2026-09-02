"""Douyin account management API routes."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, require_admin
from app.core.roles import ROLE_ADMIN
from app.schemas.chat import (
    DouyinAccountCreate,
    DouyinAccountOut,
    DouyinAccountAssign,
    DouyinAccountCookieUpdate,
    QrLoginStartOut,
    QrLoginStatusOut,
    QrVerifyCodeIn,
)
from app.schemas.common import ResponseModel
from app.services import douyin_account_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/douyin-accounts", tags=["抖音账号管理"])


@router.post("/qr-login/start", response_model=ResponseModel)
async def start_qr_login(
    current_user=Depends(require_admin),
):
    """打开浏览器扫码登录页，返回二维码图片(admin only)。"""
    try:
        session_id, qr_base64, ttl = await douyin_account_service.start_qr_login()
    except Exception as exc:
        logger.exception("start_qr_login failed")
        raise HTTPException(status_code=502, detail=f"打开登录页失败: {exc}")
    return ResponseModel(data=QrLoginStartOut(
        login_session_id=session_id, qr_image_base64=qr_base64, expires_in=ttl,
    ))


@router.get("/qr-login/{login_session_id}/status", response_model=ResponseModel)
async def get_qr_login_status(
    login_session_id: str,
    current_user=Depends(require_admin),
):
    """轮询扫码登录状态，confirmed时返回storage_state供后续add_account使用。"""
    result = await douyin_account_service.poll_qr_login(login_session_id)
    return ResponseModel(data=QrLoginStatusOut(
        status=result["status"],
        cookie_data=result.get("storage_state"),
        qr_image_base64=result.get("qr_image_base64"),
        verify_message=result.get("verify_message"),
        verify_image_base64=result.get("verify_image_base64"),
    ))


@router.post("/qr-login/{login_session_id}/verify", response_model=ResponseModel)
async def submit_qr_verification_code(
    login_session_id: str,
    body: QrVerifyCodeIn,
    current_user=Depends(require_admin),
):
    """提交异地登录二次验证的短信验证码(admin only)。"""
    result = await douyin_account_service.submit_qr_verification(login_session_id, body.code)
    return ResponseModel(data=QrLoginStatusOut(
        status=result["status"],
        cookie_data=result.get("storage_state"),
        qr_image_base64=result.get("qr_image_base64"),
        verify_message=result.get("verify_message"),
        verify_image_base64=result.get("verify_image_base64"),
    ))


@router.get("", response_model=ResponseModel)
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get account list. Admin sees all, customer service sees only assigned."""
    is_admin = current_user.role == ROLE_ADMIN
    accounts = await douyin_account_service.get_accounts(
        db, user_id=current_user.id, is_admin=is_admin
    )
    return ResponseModel(data=accounts)


@router.post("", response_model=ResponseModel)
async def add_account(
    body: DouyinAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Add a new Douyin chat account (admin only)."""
    account, is_new = await douyin_account_service.add_account(
        db,
        douyin_uid=body.douyin_uid,
        nickname=body.nickname,
        cookie_data=body.cookie_data,
        proxy_url=body.proxy_url,
        nurture_enabled=body.nurture_enabled,
    )
    message = "账号添加成功" if is_new else "该抖音号已存在，登录态已刷新更新"
    return ResponseModel(message=message, data={"id": account.id})


@router.put("/{account_id}/assign", response_model=ResponseModel)
async def assign_account(
    account_id: int,
    body: DouyinAccountAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Assign account to a user (admin only)."""
    success = await douyin_account_service.assign_account(db, account_id, body.user_id)
    if not success:
        raise HTTPException(status_code=400, detail="该用户已达账号绑定上限(10个)")
    return ResponseModel(message="分配成功")


@router.put("/{account_id}/unassign", response_model=ResponseModel)
async def unassign_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Remove account assignment (admin only)."""
    await douyin_account_service.unassign_account(db, account_id)
    return ResponseModel(message="已取消分配")


@router.put("/{account_id}/cookie", response_model=ResponseModel)
async def update_cookie(
    account_id: int,
    body: DouyinAccountCookieUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update cookie for an account."""
    account = await douyin_account_service.get_account_by_id(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    # Only admin or assigned user can update cookie
    if current_user.role != "admin" and account.assigned_to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="没有权限操作此账号")
    await douyin_account_service.update_cookie(db, account_id, body.cookie_data)
    return ResponseModel(message="Cookie已更新")


@router.get("/{account_id}/status", response_model=ResponseModel)
async def check_status(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Check login status of an account."""
    result = await douyin_account_service.check_login_status(db, account_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="账号不存在")
    return ResponseModel(data=result)


@router.delete("/{account_id}", response_model=ResponseModel)
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Delete a Douyin chat account (admin only)."""
    success = await douyin_account_service.delete_account(db, account_id)
    if not success:
        raise HTTPException(status_code=404, detail="账号不存在")
    return ResponseModel(message="账号已删除")
