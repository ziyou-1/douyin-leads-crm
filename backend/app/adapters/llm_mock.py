"""Mock LLM适配器 — 基于关键词规则模拟AI意向判断。"""
import asyncio
import random
import logging
from typing import List

from app.adapters.llm_base import BaseLLMAdapter, IntentLevel, IntentResult

logger = logging.getLogger(__name__)

# ── 关键词库 ───────────────────────────────────────────────────────────────────

_HIGH_INTENT_KEYWORDS = [
    "怎么买", "多少钱", "价格", "在哪买", "链接", "下单",
    "购买", "想要", "怎么联系", "怎么付款", "批发", "代购",
    "哪里有卖", "求链接", "想买", "加你微信", "私信我",
]

# 高意向理由模板
_HIGH_REASONS = [
    '评论包含明确的购买意向词汇"{kw}"，用户有强烈的消费意愿',
    '用户主动询问购买方式，关键词"{kw}"表明其已进入决策阶段',
    '评论中"{kw}"属于高转化信号，建议优先跟进',
]

_INVALID_REASONS = [
    "评论未包含任何购买或咨询关键词，属于普通互动",
    "评论内容与购买意向无关，暂无跟进价值",
    "评论为一般性互动内容，不具备转化潜力",
]


def _match_keyword(text: str, keywords: list) -> str | None:
    """返回第一个命中的关键词，未命中返回None"""
    for kw in keywords:
        if kw in text:
            return kw
    return None


class MockLLMAdapter(BaseLLMAdapter):
    """基于关键词规则模拟AI意向判断，用于开发和测试"""

    async def analyze_intent(self, comment_text: str, context: dict = None) -> IntentResult:
        """单条评论意向分析"""
        # 模拟异步延迟 0.1-0.5秒
        await asyncio.sleep(random.uniform(0.1, 0.5))

        intent_level, reason, confidence = self._classify(comment_text)

        return IntentResult(
            comment_id="",
            intent_level=intent_level,
            reason=reason,
            confidence=confidence,
        )

    async def batch_analyze_intent(self, comments: List[dict]) -> List[IntentResult]:
        """批量评论意向分析"""
        results = []
        for comment in comments:
            # 模拟异步延迟，批量稍快一些
            await asyncio.sleep(random.uniform(0.05, 0.2))

            content = comment.get("content", "")
            comment_id = str(comment.get("comment_id", ""))

            intent_level, reason, confidence = self._classify(content)

            results.append(IntentResult(
                comment_id=comment_id,
                intent_level=intent_level,
                reason=reason,
                confidence=confidence,
            ))

        return results

    def _classify(self, text: str) -> tuple[IntentLevel, str, float]:
        """基于关键词和随机性进行分类"""
        high_kw = _match_keyword(text, _HIGH_INTENT_KEYWORDS)

        if high_kw:
            reason = random.choice(_HIGH_REASONS).format(kw=high_kw)
            confidence = round(random.uniform(0.75, 0.95), 2)
            return IntentLevel.HIGH, reason, confidence

        reason = random.choice(_INVALID_REASONS)
        confidence = round(random.uniform(0.6, 0.9), 2)
        return IntentLevel.INVALID, reason, confidence
