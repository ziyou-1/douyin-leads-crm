"""轮询策略 API：读写配置、返回分档调用次数。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.deps import get_db, get_current_user, require_admin
from app.schemas.common import ResponseModel
from app.services.polling_strategy import PollingConfig
from app.services.polling_runtime import (
    load_polling_config,
    save_polling_config,
    get_poll_call_counts,
)

router = APIRouter(prefix="/polling", tags=["轮询策略配置"])


class IntervalsUpdate(BaseModel):
    hot: Optional[int] = Field(None, ge=1)
    normal: Optional[int] = Field(None, ge=1)
    cold: Optional[int] = Field(None, ge=1)
    paused: Optional[int] = Field(None, ge=1)


class UpgradeConditionsUpdate(BaseModel):
    to_hot: Optional[int] = Field(None, ge=1)
    to_normal_from_cold: Optional[int] = Field(None, ge=1)
    to_cold_from_paused: Optional[int] = Field(None, ge=1)


class DowngradeConditionsUpdate(BaseModel):
    hot_to_normal: Optional[int] = Field(None, ge=1)
    normal_max_polls: Optional[int] = Field(None, ge=1)
    cold_max_polls: Optional[int] = Field(None, ge=1)


class PollingConfigUpdate(BaseModel):
    intervals: Optional[IntervalsUpdate] = None
    upgrade_conditions: Optional[UpgradeConditionsUpdate] = None
    downgrade_conditions: Optional[DowngradeConditionsUpdate] = None


@router.get("/config", response_model=ResponseModel)
async def get_polling_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    config = await load_polling_config(db)
    return ResponseModel(data=config.to_frontend_dict())


@router.put("/config", response_model=ResponseModel)
async def update_polling_config(
    body: PollingConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    current = (await load_polling_config(db)).to_frontend_dict()
    if body.intervals:
        current["intervals"].update(body.intervals.model_dump(exclude_none=True))
    if body.upgrade_conditions:
        current["upgrade_conditions"].update(body.upgrade_conditions.model_dump(exclude_none=True))
    if body.downgrade_conditions:
        current["downgrade_conditions"].update(body.downgrade_conditions.model_dump(exclude_none=True))
    new_config = PollingConfig.from_frontend_dict(current)
    await save_polling_config(db, new_config, current_user.username)
    await db.commit()
    return ResponseModel(message="配置已更新", data=new_config.to_frontend_dict())


@router.get("/call-counts", response_model=ResponseModel)
async def polling_call_counts(
    current_user=Depends(get_current_user),
):
    return ResponseModel(data=await get_poll_call_counts())
