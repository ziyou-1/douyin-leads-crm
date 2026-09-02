import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, model_validator


class MonitorAccountCreate(BaseModel):
    douyin_url: str = Field(..., description="抖音用户链接或UID")
    poll_interval_min: int = Field(5, ge=1, description="拉取间隔(分钟)")
    ai_freshness_min: int = Field(20, ge=1, le=1440, description="意向评论AI分析时效窗口(分钟)")
    high_intent_min: int = Field(8, ge=1, le=1440, description="高/中意向二次分级阈值(分钟)")

    @model_validator(mode="after")
    def _check_high_intent_within_freshness(self):
        if self.high_intent_min > self.ai_freshness_min:
            raise ValueError("高意向阈值不能大于意向时效窗口")
        return self


class MonitorAccountUpdate(BaseModel):
    nickname: Optional[str] = None
    status: Optional[str] = None
    poll_interval_min: Optional[int] = Field(None, ge=1)
    ai_freshness_min: Optional[int] = Field(None, ge=1, le=1440)
    high_intent_min: Optional[int] = Field(None, ge=1, le=1440)


class MonitorBatchStatusUpdate(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=100)
    status: Literal["active", "paused"]


class MonitorBatchIntervalUpdate(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=100)
    poll_interval_min: int = Field(..., ge=1, le=1440)
    ai_freshness_min: int = Field(20, ge=1, le=1440, description="意向评论AI分析时效窗口(分钟)")
    high_intent_min: int = Field(8, ge=1, le=1440, description="高/中意向二次分级阈值(分钟)")

    @model_validator(mode="after")
    def _check_high_intent_within_freshness(self):
        if self.high_intent_min > self.ai_freshness_min:
            raise ValueError("高意向阈值不能大于意向时效窗口")
        return self


class MonitorAccountOut(BaseModel):
    id: int
    douyin_url: str
    douyin_uid: str
    nickname: str
    avatar: str
    status: str
    poll_interval_min: int
    ai_freshness_min: int = 20
    high_intent_min: int = 8
    created_by: Optional[int]
    created_at: datetime.datetime
    source: str = "manual"
    last_high_intent_at: Optional[datetime.datetime] = None
    total_high_count: int = 0

    class Config:
        from_attributes = True


class MonitorAccountList(BaseModel):
    code: int = 200
    message: str = "success"
    data: List[MonitorAccountOut] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class BatchImportResult(BaseModel):
    success_count: int = 0
    fail_count: int = 0
    errors: List[str] = []
