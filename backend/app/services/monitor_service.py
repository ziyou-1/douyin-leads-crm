"""Monitor service — business logic for Douyin account monitoring."""

import csv
import datetime
import io
import re
from typing import Optional, Tuple, List

from sqlalchemy import select, update, func as sa_func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitor import MonitorAccount
from app.models.chat import ChatMessage
from app.models.comment import Comment
from app.models.lead import Lead
from app.models.user import User
from app.models.video import Video
from app.schemas.monitor import MonitorAccountCreate, MonitorAccountUpdate, BatchImportResult


def parse_douyin_url(url: str) -> Tuple[str, str]:
    """Parse a Douyin URL and return (douyin_uid, original_url).

    Supported formats:
    - https://www.douyin.com/user/MS4wLjABAAAA...
    - https://v.douyin.com/xxxxx/
    - Direct UID string

    Returns (uid, stored_url).
    """
    url = url.strip()

    # Match /user/XXXX pattern
    user_match = re.search(r'/user/([A-Za-z0-9_\-]+)', url)
    if user_match:
        return user_match.group(1), url

    # Short link pattern — keep original URL, use last path segment as uid
    if 'v.douyin.com' in url or 'douyin.com' in url:
        # Extract last meaningful path segment
        cleaned = url.rstrip('/')
        parts = cleaned.split('/')
        uid = parts[-1] if parts else url
        return uid, url

    # Direct UID
    return url, url


async def create_monitor(
    db: AsyncSession, data: MonitorAccountCreate, created_by: Optional[int] = None
) -> MonitorAccount:
    """Create a new monitor account from a Douyin URL."""
    uid, stored_url = parse_douyin_url(data.douyin_url)

    monitor = MonitorAccount(
        douyin_url=stored_url,
        douyin_uid=uid,
        nickname="",
        poll_interval_min=data.poll_interval_min,
        ai_freshness_min=data.ai_freshness_min,
        high_intent_min=data.high_intent_min,
        created_by=created_by,
    )
    db.add(monitor)
    await db.flush()
    await db.refresh(monitor)
    return monitor


async def get_monitor_by_id(db: AsyncSession, monitor_id: int) -> Optional[MonitorAccount]:
    result = await db.execute(
        select(MonitorAccount).where(MonitorAccount.id == monitor_id)
    )
    return result.scalar_one_or_none()


async def get_monitor_by_uid(db: AsyncSession, uid: str) -> Optional[MonitorAccount]:
    result = await db.execute(
        select(MonitorAccount).where(MonitorAccount.douyin_uid == uid)
    )
    return result.scalar_one_or_none()


async def get_monitors(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "desc",
) -> Tuple[list, int]:
    """Return (list_of_monitors, total_count) with pagination and filters."""
    query = select(MonitorAccount).where(
        MonitorAccount.status.notin_(['deleted', 'removed'])
    )
    count_query = select(sa_func.count()).select_from(MonitorAccount).where(
        MonitorAccount.status.notin_(['deleted', 'removed'])
    )

    if status_filter:
        query = query.where(MonitorAccount.status == status_filter)
        count_query = count_query.where(MonitorAccount.status == status_filter)

    if search:
        like_pattern = f"%{search}%"
        query = query.where(
            or_(
                MonitorAccount.nickname.ilike(like_pattern),
                MonitorAccount.douyin_uid.ilike(like_pattern),
            )
        )
        count_query = count_query.where(
            or_(
                MonitorAccount.nickname.ilike(like_pattern),
                MonitorAccount.douyin_uid.ilike(like_pattern),
            )
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    if sort_by == "total_high_count":
        sort_column = MonitorAccount.total_high_count
    else:
        sort_column = MonitorAccount.id
    order_expression = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    query = query.order_by(order_expression, MonitorAccount.id.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    monitors = list(result.scalars().all())

    return monitors, total


async def update_monitor(
    db: AsyncSession, monitor_id: int, data: MonitorAccountUpdate
) -> Optional[MonitorAccount]:
    monitor = await get_monitor_by_id(db, monitor_id)
    if monitor is None or monitor.status == 'deleted':
        return None
    if data.nickname is not None:
        monitor.nickname = data.nickname
    if data.status is not None:
        monitor.status = data.status
    if data.poll_interval_min is not None:
        monitor.poll_interval_min = data.poll_interval_min
    if data.ai_freshness_min is not None:
        monitor.ai_freshness_min = data.ai_freshness_min
    if data.high_intent_min is not None:
        monitor.high_intent_min = data.high_intent_min
    await db.flush()
    await db.refresh(monitor)
    return monitor


async def delete_monitor(db: AsyncSession, monitor_id: int) -> bool:
    """Soft delete by setting status to 'deleted'."""
    monitor = await get_monitor_by_id(db, monitor_id)
    if monitor is None:
        return False
    monitor.status = 'deleted'
    await db.flush()
    return True


async def batch_delete_monitors(db: AsyncSession, monitor_ids: list[int]) -> int:
    result = await db.execute(
        update(MonitorAccount)
        .where(
            MonitorAccount.id.in_(monitor_ids),
            MonitorAccount.status != 'deleted',
        )
        .values(status='deleted')
    )
    await db.flush()
    return result.rowcount or 0


async def batch_update_status(
    db: AsyncSession,
    monitor_ids: list[int],
    target_status: str,
) -> int:
    result = await db.execute(
        update(MonitorAccount)
        .where(
            MonitorAccount.id.in_(monitor_ids),
            MonitorAccount.status.notin_(["deleted", "removed"]),
        )
        .values(status=target_status)
    )
    await db.flush()
    return result.rowcount or 0


async def batch_update_poll_interval(
    db: AsyncSession,
    monitor_ids: list[int],
    poll_interval_min: int,
    ai_freshness_min: Optional[int] = None,
    high_intent_min: Optional[int] = None,
) -> int:
    values: dict = {"poll_interval_min": poll_interval_min}
    if ai_freshness_min is not None:
        values["ai_freshness_min"] = ai_freshness_min
    if high_intent_min is not None:
        values["high_intent_min"] = high_intent_min
    result = await db.execute(
        update(MonitorAccount)
        .where(
            MonitorAccount.id.in_(monitor_ids),
            MonitorAccount.status.notin_(["deleted", "removed"]),
        )
        .values(**values)
    )
    await db.flush()
    return result.rowcount or 0


async def toggle_status(db: AsyncSession, monitor_id: int) -> Optional[MonitorAccount]:
    """Toggle between active and paused."""
    monitor = await get_monitor_by_id(db, monitor_id)
    if monitor is None or monitor.status == 'deleted':
        return None
    monitor.status = 'paused' if monitor.status == 'active' else 'active'
    await db.flush()
    await db.refresh(monitor)
    return monitor


async def get_removed_monitors(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
) -> Tuple[list, int]:
    """Return (list_of_removed_monitors, total_count) with pagination."""
    query = select(MonitorAccount).where(MonitorAccount.status == 'removed')
    count_query = select(sa_func.count()).select_from(MonitorAccount).where(
        MonitorAccount.status == 'removed'
    )

    if search:
        like_pattern = f"%{search}%"
        query = query.where(
            or_(
                MonitorAccount.nickname.ilike(like_pattern),
                MonitorAccount.douyin_uid.ilike(like_pattern),
            )
        )
        count_query = count_query.where(
            or_(
                MonitorAccount.nickname.ilike(like_pattern),
                MonitorAccount.douyin_uid.ilike(like_pattern),
            )
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(MonitorAccount.id.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    monitors = list(result.scalars().all())

    return monitors, total


async def restore_monitor(db: AsyncSession, monitor_id: int) -> Optional[MonitorAccount]:
    """恢复被移出的账号（将status从removed改回active）"""
    monitor = await get_monitor_by_id(db, monitor_id)
    if monitor is None or monitor.status != 'removed':
        return None
    monitor.status = 'active'
    await db.flush()
    await db.refresh(monitor)
    return monitor


async def get_monitor_account_stats(
    db: AsyncSession,
    monitor_id: int,
    days: int,
    detail_limit: int = 500,
) -> Optional[dict]:
    monitor = await get_monitor_by_id(db, monitor_id)
    if monitor is None or monitor.status == "deleted":
        return None

    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(days=days)
    lead_time = sa_func.coalesce(Comment.comment_time, Lead.created_at)
    conditions = [
        Video.monitor_account_id == monitor_id,
        lead_time >= start_time,
        lead_time <= end_time,
    ]

    lead_count_query = (
        select(sa_func.count(Lead.id))
        .join(Video, Lead.video_id == Video.id)
        .outerjoin(Comment, Lead.comment_id == Comment.id)
        .where(and_(*conditions))
    )
    high_lead_count = (await db.execute(lead_count_query)).scalar() or 0

    outbound_conditions = [
        ChatMessage.direction == "outbound",
        ChatMessage.status != "failed",
        Lead.assigned_to.is_not(None),
        Lead.assigned_at.is_not(None),
        ChatMessage.sent_at >= Lead.assigned_at,
        ChatMessage.sent_at >= start_time,
        ChatMessage.sent_at <= end_time,
    ]
    outbound_query = (
        select(
            Lead.assigned_to,
            User.username,
            sa_func.count(ChatMessage.id).label("outbound_count"),
            sa_func.count(sa_func.distinct(Lead.id)).label("communicated_leads"),
        )
        .join(Lead, ChatMessage.lead_id == Lead.id)
        .join(Video, Lead.video_id == Video.id)
        .join(User, Lead.assigned_to == User.id)
        .where(
            Video.monitor_account_id == monitor_id,
            and_(*outbound_conditions),
        )
        .group_by(Lead.assigned_to, User.username)
    )
    outbound_rows = (await db.execute(outbound_query)).all()
    outbound_map = {
        row.assigned_to: {
            "outbound_count": row.outbound_count,
            "communicated_leads": row.communicated_leads,
        }
        for row in outbound_rows
    }

    assigned_query = (
        select(
            Lead.assigned_to,
            User.username,
            sa_func.count(Lead.id).label("assigned_leads"),
        )
        .join(Video, Lead.video_id == Video.id)
        .outerjoin(Comment, Lead.comment_id == Comment.id)
        .join(User, Lead.assigned_to == User.id)
        .where(and_(*conditions), Lead.assigned_to.is_not(None))
        .group_by(Lead.assigned_to, User.username)
    )
    assigned_rows = (await db.execute(assigned_query)).all()
    sales_stats = []
    for row in assigned_rows:
        message_stats = outbound_map.get(row.assigned_to, {})
        sales_stats.append({
            "user_id": row.assigned_to,
            "username": row.username,
            "assigned_leads": row.assigned_leads,
            "communicated_leads": message_stats.get("communicated_leads", 0),
            "outbound_messages": message_stats.get("outbound_count", 0),
        })

    outbound_count_subquery = (
        select(sa_func.count(ChatMessage.id))
        .where(
            ChatMessage.lead_id == Lead.id,
            ChatMessage.direction == "outbound",
            ChatMessage.status != "failed",
            Lead.assigned_at.is_not(None),
            ChatMessage.sent_at >= Lead.assigned_at,
            ChatMessage.sent_at >= start_time,
            ChatMessage.sent_at <= end_time,
        )
        .correlate(Lead)
        .scalar_subquery()
    )
    details_query = (
        select(
            Lead.id,
            Lead.user_nickname,
            Lead.user_uid,
            Lead.ai_reason,
            Comment.content,
            Comment.comment_time,
            Video.title,
            User.username,
            outbound_count_subquery.label("outbound_messages"),
        )
        .join(Video, Lead.video_id == Video.id)
        .outerjoin(Comment, Lead.comment_id == Comment.id)
        .outerjoin(User, Lead.assigned_to == User.id)
        .where(and_(*conditions))
        .order_by(lead_time.desc())
        .limit(detail_limit)
    )
    detail_rows = (await db.execute(details_query)).all()
    leads = [{
        "lead_id": row.id,
        "user_nickname": row.user_nickname,
        "user_uid": row.user_uid,
        "comment_content": row.content or "",
        "comment_time": row.comment_time,
        "video_title": row.title or "",
        "ai_reason": row.ai_reason,
        "sales_name": row.username,
        "outbound_messages": row.outbound_messages or 0,
    } for row in detail_rows]

    outbound_message_count = sum(row.outbound_count for row in outbound_rows)
    communicated_lead_count = sum(row.communicated_leads for row in outbound_rows)
    return {
        "monitor": {
            "id": monitor.id,
            "nickname": monitor.nickname,
            "douyin_uid": monitor.douyin_uid,
        },
        "days": days,
        "start_time": start_time,
        "end_time": end_time,
        "high_lead_count": high_lead_count,
        "outbound_message_count": outbound_message_count,
        "communicated_lead_count": communicated_lead_count,
        "sales_stats": sales_stats,
        "leads": leads,
    }


async def export_monitor_account_stats(
    db: AsyncSession,
    monitor_id: int,
    days: int,
) -> Optional[io.BytesIO]:
    from openpyxl import Workbook

    stats = await get_monitor_account_stats(db, monitor_id, days, detail_limit=10000)
    if stats is None:
        return None

    wb = Workbook()
    ws = wb.active
    ws.title = "意向评论统计"
    ws.append([
        "监控账号", "评论用户", "用户UID", "评论内容", "评论时间",
        "来源视频", "AI判定理由", "分配客服", "客服私信数",
    ])
    monitor_name = stats["monitor"]["nickname"] or stats["monitor"]["douyin_uid"]
    for item in stats["leads"]:
        comment_time = item["comment_time"]
        ws.append([
            monitor_name,
            item["user_nickname"],
            item["user_uid"],
            item["comment_content"],
            comment_time.strftime("%Y-%m-%d %H:%M:%S") if comment_time else "",
            item["video_title"],
            item["ai_reason"],
            item["sales_name"] or "",
            item["outbound_messages"],
        ])

    for column in ws.columns:
        max_length = max((len(str(cell.value)) for cell in column if cell.value is not None), default=0)
        ws.column_dimensions[column[0].column_letter].width = min(max_length + 4, 50)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


_DOUYIN_URL_PATTERN = re.compile(
    r"https?://(?:www\.|v\.)?douyin\.com/[^\s\"'<>，。；、]+",
    re.IGNORECASE,
)


def _normalize_import_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_import_row(values: list[object], row_number: int) -> tuple[dict | None, str | None]:
    cells = [_normalize_import_cell(value) for value in values]
    non_empty = [value for value in cells if value]
    if not non_empty:
        return None, None

    nickname = non_empty[0]
    if nickname in {"昵称", "账号昵称", "用户昵称"}:
        return None, None

    url = ""
    for value in reversed(non_empty):
        match = _DOUYIN_URL_PATTERN.search(value)
        if match:
            url = match.group(0).rstrip(".,;!?，。；！？、)]}）】")
            break

    uid = ""
    for value in non_empty[1:]:
        if re.fullmatch(r"\d{5,20}", value):
            uid = value
            break

    if not uid and len(non_empty) >= 2:
        candidate = non_empty[1]
        if not _DOUYIN_URL_PATTERN.search(candidate):
            uid = candidate

    if not nickname or not uid or not url:
        missing = []
        if not nickname:
            missing.append("昵称")
        if not uid:
            missing.append("抖音UID")
        if not url:
            missing.append("抖音链接")
        return None, f"第 {row_number} 行缺少{'、'.join(missing)}"

    return {"nickname": nickname, "douyin_uid": uid, "douyin_url": url}, None


async def batch_import(
    db: AsyncSession, file_content: bytes, filename: str, created_by: Optional[int] = None
) -> BatchImportResult:
    """Parse CSV or Excel file and batch import monitor accounts."""
    result = BatchImportResult()
    records: List[dict] = []
    normalized_filename = filename.lower()

    try:
        rows: list[list[object]] = []
        if normalized_filename.endswith('.csv'):
            text = file_content.decode('utf-8-sig')
            rows = [list(row) for row in csv.reader(io.StringIO(text))]
        elif normalized_filename.endswith('.xlsx'):
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
            ws = wb.active
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
            wb.close()
        elif normalized_filename.endswith('.xls'):
            import xlrd

            wb = xlrd.open_workbook(file_contents=file_content, on_demand=True)
            ws = wb.sheet_by_index(0)
            rows = [ws.row_values(row_index) for row_index in range(ws.nrows)]
            wb.release_resources()
        else:
            result.fail_count = 1
            result.errors.append("不支持的文件格式，仅支持 .csv、.xlsx 和 .xls")
            return result

        for row_number, row in enumerate(rows, start=1):
            record, error = _parse_import_row(row, row_number)
            if record:
                records.append(record)
            elif error:
                result.fail_count += 1
                result.errors.append(error)
    except Exception as exc:
        result.fail_count = 1
        result.errors.append(f"文件解析失败，请确认文件格式与扩展名一致：{exc}")
        return result

    for record in records:
        nickname = record["nickname"]
        uid = record["douyin_uid"]
        url = record["douyin_url"]
        try:
            existing = await get_monitor_by_uid(db, uid)
            if existing:
                if existing.status == 'deleted':
                    existing.status = 'active'
                    existing.nickname = nickname
                    existing.douyin_url = url
                    result.success_count += 1
                elif existing.nickname != nickname or existing.douyin_url != url:
                    existing.nickname = nickname
                    existing.douyin_url = url
                    result.success_count += 1
                else:
                    result.fail_count += 1
                    result.errors.append(f"UID {uid} 已存在")
                continue

            legacy_result = await db.execute(
                select(MonitorAccount).where(
                    MonitorAccount.douyin_uid == nickname,
                    MonitorAccount.douyin_url == nickname,
                )
            )
            legacy = legacy_result.scalar_one_or_none()
            if legacy:
                legacy.nickname = nickname
                legacy.douyin_uid = uid
                legacy.douyin_url = url
                if legacy.status == 'deleted':
                    legacy.status = 'active'
                result.success_count += 1
                continue

            monitor = MonitorAccount(
                douyin_url=url,
                douyin_uid=uid,
                nickname=nickname,
                poll_interval_min=5,
                created_by=created_by,
            )
            db.add(monitor)
            await db.flush()
            result.success_count += 1
        except Exception as e:
            result.fail_count += 1
            result.errors.append(f"导入 UID {uid} 失败: {str(e)}")

    return result
