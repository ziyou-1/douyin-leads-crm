from typing import List, Optional
from pydantic import BaseModel


class DashboardOverview(BaseModel):
    today_leads: int = 0  # 今日新线索(高意向+中意向)
    today_reply_rate: float = 0.0  # 综合回复率(%)：今日线索中，用户在抖音端真实回复过客服的占比
    today_high_intent: int = 0  # 高意向线索
    today_high_reply_rate: float = 0.0  # 高意向线索回复率(%)
    today_medium_intent: int = 0  # 中意向线索数
    today_medium_reply_rate: float = 0.0  # 中意向线索回复率(%)
    poll_calls_hot: int = 0
    poll_calls_normal: int = 0
    poll_calls_cold: int = 0
    poll_calls_paused: int = 0


class SalesPerformanceItem(BaseModel):
    user_id: int
    username: str
    total_leads: int = 0
    high_intent: int = 0
    converted: int = 0
    conversion_rate: float = 0.0
    avg_response_hours: float = 0.0


class MonitorStatsItem(BaseModel):
    monitor_id: int
    nickname: str
    total_comments: int = 0
    total_leads: int = 0
    lead_rate: float = 0.0


class TrendDataPoint(BaseModel):
    date: str
    comments: int = 0
    leads: int = 0
    high_intent: int = 0
    converted: int = 0


class TrendResponse(BaseModel):
    data: List[TrendDataPoint]
