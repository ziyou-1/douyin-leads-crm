"""LLM意向分析适配器基类与数据结构。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from enum import Enum


DEFAULT_INTENT_ANALYSIS_PROMPT = (
    "你是一个专业的抖音视频评论意向分析助手。请分析用户评论是否有购买、咨询或合作意向。\n\n"
    "判断标准：\n"
    "- high（高意向）：明确表达购买意愿、询问价格、询问购买方式、要求联系方式、表示想要或需要\n"
    "- invalid（无效）：仅询问效果或详情、泛泛表示感兴趣、犹豫对比、纯闲聊、表情、吐槽、"
    "无关内容、广告\n\n"
    "请严格以 JSON 格式返回，不要输出其他内容：\n"
    '{"intent_level": "high/invalid", "reason": "简要分析理由（20字以内）"}'
)


class IntentLevel(str, Enum):
    """评论意向等级"""
    HIGH = "high"
    INVALID = "invalid"


@dataclass
class IntentResult:
    """单条评论的意向分析结果"""
    comment_id: str
    intent_level: IntentLevel
    reason: str  # AI分析理由
    confidence: float = 0.0  # 置信度 0-1


class BaseLLMAdapter(ABC):
    """LLM意向分析适配器抽象基类"""

    @abstractmethod
    async def analyze_intent(self, comment_text: str, context: dict = None) -> IntentResult:
        """单条评论意向分析

        Args:
            comment_text: 评论文本内容
            context: 可选上下文信息, 如 video_title 等

        Returns:
            IntentResult: 意向分析结果
        """
        ...

    @abstractmethod
    async def batch_analyze_intent(self, comments: List[dict]) -> List[IntentResult]:
        """批量评论意向分析(降低API调用成本)

        Args:
            comments: 评论列表, 每项包含 comment_id, content, 以及可选的 video_title 等上下文

        Returns:
            List[IntentResult]: 每条评论的分析结果
        """
        ...
