"""意向识别Celery定时任务。"""
import logging

from app.core.deps import async_session_factory
from app.services.intent_service import (
    BATCH_SIZE,
    assign_unassigned_leads,
    process_unanalyzed_comments,
)
from app.tasks.async_utils import run_async
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _enqueue_leads(lead_ids: list[int]) -> None:
    from sqlalchemy import select

    from app.models.comment import Comment
    from app.models.lead import Lead
    from app.services.dm_queue_service import dm_queue_service

    async with async_session_factory() as enqueue_db:
        try:
            for lid in lead_ids:
                lead_result = await enqueue_db.execute(select(Lead).where(Lead.id == lid))
                lead = lead_result.scalar_one_or_none()
                if not lead:
                    continue

                comment_content = ""
                comment_time = None
                if lead.comment_id:
                    c_result = await enqueue_db.execute(
                        select(Comment.content, Comment.comment_time).where(
                            Comment.id == lead.comment_id
                        )
                    )
                    row = c_result.first()
                    if row:
                        comment_content = row[0] or ""
                        comment_time = row[1]

                await dm_queue_service.enqueue(
                    db=enqueue_db,
                    lead_id=lid,
                    user_uid=lead.user_uid,
                    comment=comment_content,
                    comment_time=comment_time,
                )
            await enqueue_db.commit()
            logger.info("Enqueued %d leads to DM queue", len(lead_ids))
        except Exception as exc:
            await enqueue_db.rollback()
            logger.warning("Failed to enqueue leads to DM queue: %s", exc)


@celery_app.task(
    name="app.tasks.intent_tasks.process_new_comments",
    bind=True,
    max_retries=0,  # 不重试，等下次beat触发
)
def process_new_comments(self):
    """
    处理新评论的意向识别。
    由beat每30秒触发一次。
    每批最多处理50条评论。
    """
    async def _process():
        async with async_session_factory() as db:
            try:
                result = await process_unanalyzed_comments(db, limit=BATCH_SIZE)
                result["leads_assigned"] = await assign_unassigned_leads(db)
                await db.commit()
                return result
            except Exception as exc:
                await db.rollback()
                raise exc

    try:
        result = run_async(_process())

        if result["processed"] > 0:
            logger.info(
                "Intent task completed: processed=%d, leads_created=%d, leads_assigned=%d",
                result["processed"],
                result["leads_created"],
                result["leads_assigned"],
            )

        lead_ids = result.get("lead_ids", [])
        if lead_ids:
            try:
                run_async(_enqueue_leads(lead_ids))
            except Exception as exc:
                logger.warning("Failed to enqueue leads to DM queue: %s", exc)

        return result

    except Exception as exc:
        # 异常不影响下次执行
        logger.error("Intent task failed: %s", exc)
        return {"error": str(exc), "processed": 0, "leads_created": 0}
