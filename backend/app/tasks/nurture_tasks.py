"""养号日推进。"""

import logging

from app.core.config import settings
from app.core.deps import async_session_factory
from app.models.monitor import DouyinChatAccount
from app.services.auto_nurture_v2 import nurture_manager
from app.services.douyin_automation import automation
from app.tasks.celery_app import celery_app
from sqlalchemy import select

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.nurture_tasks.nurture_daily_tick")
def nurture_daily_tick():
    if settings.DOUYIN_AUTOMATION_MODE != "playwright":
        raise RuntimeError("nurture_daily_tick requires DOUYIN_AUTOMATION_MODE=playwright")

    async def _run():
        async def page_factory(account_id: int):
            async with async_session_factory() as db:
                account = (
                    await db.execute(
                        select(DouyinChatAccount).where(DouyinChatAccount.id == account_id)
                    )
                ).scalar_one_or_none()
            if account is None:
                raise RuntimeError(f"douyin account {account_id} not found")
            context = await automation._get_context(
                account.cookie_data,
                account_id=account.id,
                proxy_url=account.proxy_url,
            )
            return await context.new_page()

        return await nurture_manager.daily_tick(page_factory)

    from app.tasks.async_utils import run_async

    result = run_async(_run())
    nurture_manager.persist()
    return {"executed": result}
