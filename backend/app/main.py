import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router
from app.api.v1.openkf_spi import router as openkf_spi_router

# 默认root logger级别是WARNING，业务代码里大量logger.info()此前一直被静默丢弃。
# 这里统一开到INFO，保证正常业务日志(比如AI回复/私信发送/扫码登录排障)能被看到。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    # ── startup ──
    # Import models so that Alembic metadata is populated
    import app.models  # noqa: F401

    # 初始化默认系统配置
    from app.core.deps import async_session_factory
    from app.services.system_config_service import SystemConfigService
    async with async_session_factory() as session:
        try:
            inserted = await SystemConfigService.init_default_configs(session)
            await session.commit()
            if inserted > 0:
                print(f"[lifespan] Initialized {inserted} default system config(s)")
            from sqlalchemy import text
            await session.execute(text(
                "ALTER TABLE videos ADD COLUMN IF NOT EXISTS tier_poll_count INTEGER NOT NULL DEFAULT 0"
            ))
            await session.execute(text(
                "ALTER TABLE douyin_chat_accounts ADD COLUMN IF NOT EXISTS proxy_url TEXT NOT NULL DEFAULT ''"
            ))
            await session.execute(text(
                "ALTER TABLE douyin_chat_accounts ADD COLUMN IF NOT EXISTS nurture_enabled BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.commit()
        except Exception as exc:
            await session.rollback()
            print(f"[lifespan] Failed to init default configs: {exc}")

    yield
    # ── shutdown ──
    from app.services.douyin_automation import automation
    await automation.close()

    # Dispose the async engine
    from app.core.deps import engine
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# OpenKF SPI endpoints (no JWT, protected by AES-256-GCM envelope)
app.include_router(openkf_spi_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
