import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx

from app.adapters.base import BaseSentimentAdapter, CommentDTO, CommentPage, VideoDTO
from app.core.config import settings

logger = logging.getLogger(__name__)


class SentimentAPIAdapter(BaseSentimentAdapter):
    """TikHub 抖音数据接口适配器。"""

    def __init__(self):
        self.api_key = settings.SENTIMENT_API_KEY
        self.api_url = settings.SENTIMENT_API_URL.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.SENTIMENT_API_TIMEOUT) as client:
            for attempt in range(3):
                response = await client.get(
                    f"{self.api_url}{path}",
                    params=params,
                    headers=self.headers,
                )
                if response.status_code < 400:
                    return self._extract_data(response.json())
                if attempt == 2 or response.status_code not in {400, 429, 500, 502, 503, 504}:
                    response.raise_for_status()
                await asyncio.sleep(attempt + 1)

        raise RuntimeError("TikHub GET 请求重试后仍未成功")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.SENTIMENT_API_TIMEOUT) as client:
            response = await client.post(
                f"{self.api_url}{path}",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            return self._extract_data(response.json())

    @staticmethod
    def _extract_data(response: dict[str, Any]) -> dict[str, Any]:
        code = response.get("code", 200)
        if code != 200:
            message = response.get("message_zh") or response.get("message") or "TikHub 请求失败"
            raise RuntimeError(f"TikHub API error {code}: {message}")

        data = response.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError("TikHub 返回了无法解析的数据") from exc
        if not isinstance(data, dict):
            raise RuntimeError("TikHub 返回数据格式不正确")
        return data

    @staticmethod
    def _nested_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = data.get(key)
        if value is None and isinstance(data.get("data"), dict):
            value = data["data"].get(key)
        return value if isinstance(value, list) else []

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _extract_search_user_info(item: dict[str, Any]) -> Optional[dict[str, Any]]:
        """从用户搜索结果条目里提取真正的用户信息字典。

        fetch_user_search(v1) 返回的每个条目并不会直接把user_info放在顶层，
        而是包在 dynamic_patch.raw_data 这个JSON字符串里(卡片渲染用的数据)，
        需要额外解析一层才能拿到 sec_uid/unique_id 等字段。
        """
        user = item.get("user_info") or item.get("user")
        if isinstance(user, dict):
            return user

        raw_data = (item.get("dynamic_patch") or {}).get("raw_data")
        if isinstance(raw_data, str):
            try:
                parsed = json.loads(raw_data)
            except json.JSONDecodeError:
                return None
            user = parsed.get("user_info") or parsed.get("user")
            if isinstance(user, dict):
                return user
        return None

    async def _resolve_sec_user_id(self, account_uid: str) -> str:
        if account_uid.startswith("MS4w"):
            return account_uid

        # 注意: fetch_user_search_v2 目前在TikHub侧持续返回400(即便用官方文档
        # 演示参数也一样)，怀疑是上游接口异常/下线，改用老版本fetch_user_search
        # (v1)，实测可用，只是响应结构不同(见_extract_search_user_info)。
        data = await self._post(
            "/api/v1/douyin/search/fetch_user_search",
            {"keyword": account_uid, "cursor": 0},
        )
        users = self._nested_list(data, "user_list")
        if not users:
            raise RuntimeError(f"未找到抖音账号 {account_uid}，请使用用户主页链接或 sec_user_id")

        fallback = ""
        for item in users:
            user = self._extract_search_user_info(item)
            if not user:
                continue
            sec_uid = str(
                user.get("sec_uid")
                or user.get("sec_user_id")
                or user.get("user_id")
                or ""
            )
            if not fallback:
                fallback = sec_uid
            identifiers = {
                str(user.get("uid") or ""),
                str(user.get("unique_id") or ""),
                str(user.get("short_id") or ""),
                str(user.get("douyin_id") or ""),
                sec_uid,
            }
            if account_uid in identifiers and sec_uid:
                return sec_uid

        if fallback:
            return fallback
        raise RuntimeError(f"账号 {account_uid} 的搜索结果缺少 sec_user_id")

    @staticmethod
    def _parse_comment_item(item: dict[str, Any], video_id: str) -> Optional[CommentDTO]:
        user = item.get("user") or {}
        comment_id = str(item.get("cid") or item.get("comment_id") or item.get("id") or "")
        content = str(item.get("text") or item.get("content") or "")
        if not comment_id or not content:
            return None
        return CommentDTO(
            comment_id=comment_id,
            video_id=video_id,
            user_uid=str(user.get("sec_uid") or user.get("uid") or ""),
            user_nickname=str(user.get("nickname") or ""),
            content=content,
            comment_time=SentimentAPIAdapter._parse_datetime(item.get("create_time") or item.get("created_at")),
        )

    async def fetch_comments_page(self, video_id: str, cursor: int, count: int) -> CommentPage:
        """获取指定视频某一页评论(按时间倒序)，不做任何时间/去重过滤。"""
        if not self.api_url or not self.api_key:
            logger.warning("SENTIMENT_API_URL or SENTIMENT_API_KEY not configured, returning empty page")
            return CommentPage(comments=[], next_cursor=cursor, has_more=False)

        data = await self._get(
            "/api/v1/douyin/web/fetch_video_comments",
            {"aweme_id": video_id, "cursor": cursor, "count": count},
        )
        items = self._nested_list(data, "comments")
        comments = [c for c in (self._parse_comment_item(item, video_id) for item in items) if c is not None]

        next_cursor = int(data.get("cursor") or 0)
        has_more = bool(data.get("has_more")) and next_cursor != cursor
        return CommentPage(comments=comments, next_cursor=next_cursor, has_more=has_more)

    async def fetch_comments(self, video_id: str, since_time: datetime) -> List[CommentDTO]:
        """获取指定视频从since_time之后的评论(用于话题采集等仍按时间窗口拉取的场景)。"""
        if not self.api_url or not self.api_key:
            logger.warning("SENTIMENT_API_URL or SENTIMENT_API_KEY not configured, returning empty list")
            return []

        cursor = 0
        comments: list[CommentDTO] = []
        normalized_since = since_time if since_time.tzinfo else since_time.replace(tzinfo=timezone.utc)

        for _ in range(settings.SENTIMENT_MAX_PAGES):
            page = await self.fetch_comments_page(video_id, cursor, count=50)
            reached_time_boundary = False

            for c in page.comments:
                if c.comment_time < normalized_since:
                    reached_time_boundary = True
                    continue
                comments.append(c)

            if reached_time_boundary or not page.comments or not page.has_more:
                break
            cursor = page.next_cursor

        return comments

    async def get_video_list(self, account_uid: str) -> List[VideoDTO]:
        """获取账号主页作品列表。"""
        if not self.api_url or not self.api_key:
            logger.warning("SENTIMENT_API_URL or SENTIMENT_API_KEY not configured, returning empty list")
            return []

        sec_user_id = await self._resolve_sec_user_id(account_uid)
        max_cursor = 0
        videos: list[VideoDTO] = []

        for _ in range(settings.SENTIMENT_MAX_PAGES):
            data = await self._get(
                "/api/v1/douyin/app/v3/fetch_user_post_videos",
                {
                    "sec_user_id": sec_user_id,
                    "max_cursor": max_cursor,
                    "count": 20,
                    "sort_type": 0,
                    "channel": "normal",
                },
            )
            items = self._nested_list(data, "aweme_list")
            for item in items:
                video_id = str(item.get("aweme_id") or item.get("id") or "")
                if not video_id:
                    continue
                author = item.get("author") or {}
                statistics = item.get("statistics") or {}
                videos.append(VideoDTO(
                    video_id=video_id,
                    title=str(item.get("desc") or item.get("title") or ""),
                    publish_time=self._parse_datetime(
                        item.get("create_time") or item.get("publish_time")
                    ),
                    account_uid=str(author.get("sec_uid") or sec_user_id),
                    account_nickname=str(author.get("nickname") or ""),
                    comment_count=int(statistics.get("comment_count") or item.get("comment_count") or 0),
                ))

            if not items or not data.get("has_more"):
                break
            next_cursor = int(data.get("max_cursor") or 0)
            if next_cursor == max_cursor:
                break
            max_cursor = next_cursor

        return videos

    async def fetch_topic_comments(self, topic: str, industry: str, since_time: datetime) -> List[CommentDTO]:
        """按话题/行业范围采集全网评论(不做关键词过滤，采集该领域的所有评论)"""
        if not self.api_url or not self.api_key:
            logger.warning("SENTIMENT_API_URL or SENTIMENT_API_KEY not configured, returning empty list")
            return []

        # TODO: 确定供应商后替换为实际请求格式
        url = f"{self.api_url}/comments/search"
        params = {
            "topic": topic,
            "industry": industry,
            "since_time": since_time.isoformat(),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as exc:
                logger.error("Failed to fetch topic comments from sentiment API: %s", exc)
                return []

        comments = []
        for item in data.get("comments", []):
            comments.append(CommentDTO(
                comment_id=item.get("id", ""),
                video_id=item.get("video_id", ""),
                user_uid=item.get("user_id", ""),
                user_nickname=item.get("nickname", ""),
                content=item.get("text", ""),
                comment_time=datetime.fromisoformat(item.get("created_at", datetime.now().isoformat())),
            ))
        return comments

    async def search_videos_by_keyword(self, keyword: str, page: int, page_size: int) -> List[VideoDTO]:
        """从舆情API按关键词搜索全网视频"""
        if not self.api_url or not self.api_key:
            logger.warning("SENTIMENT_API_URL or SENTIMENT_API_KEY not configured, returning empty list")
            return []

        url = f"{self.api_url}/videos/search"
        params = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as exc:
                logger.error("Failed to search videos by keyword '%s': %s", keyword, exc)
                return []

        videos = []
        for item in data.get("videos", []):
            videos.append(VideoDTO(
                video_id=item.get("id", ""),
                title=item.get("title", ""),
                publish_time=datetime.fromisoformat(item.get("publish_time", datetime.now().isoformat())),
                account_uid=item.get("account_uid", ""),
                account_nickname=item.get("account_nickname", ""),
                comment_count=item.get("comment_count", 0),
            ))
        return videos
