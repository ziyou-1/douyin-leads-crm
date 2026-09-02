"""养号 API。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, require_admin
from app.schemas.common import ResponseModel
from app.services.auto_nurture_v2 import nurture_manager

router = APIRouter(prefix="/nurture", tags=["养号管理"])


class RegisterRequest(BaseModel):
    account_id: int
    is_new: bool = True


@router.post("/accounts/register", response_model=ResponseModel)
async def register_account(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    nurture_manager.register(req.account_id, is_new=req.is_new)
    nurture_manager.persist()
    return ResponseModel(data=nurture_manager.get_status(req.account_id))


@router.get("/accounts/nurture-status", response_model=ResponseModel)
async def nurture_status(
    account_id: int | None = None,
    current_user=Depends(get_current_user),
):
    if account_id is not None:
        data = nurture_manager.get_status(account_id)
        if data is None:
            return ResponseModel(code=404, message="账号未注册养号", data=None)
        return ResponseModel(data=data)
    return ResponseModel(
        data=[nurture_manager.get_status(aid) for aid in list(nurture_manager._records)]
    )


@router.post("/accounts/{account_id}/graduate", response_model=ResponseModel)
async def graduate_account(
    account_id: int,
    force: bool = True,
    current_user=Depends(require_admin),
):
    result = nurture_manager.graduate(account_id, force=force)
    nurture_manager.persist()
    return ResponseModel(data=result)
