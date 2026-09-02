#!/bin/bash
set -e

echo "Initializing database tables and default admin..."
python -m app.init_db

echo "Syncing alembic version..."
python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.deps import engine

HEAD = "h8i9j0k1l2m3"

async def sync() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        rows = result.fetchall()
        if not rows:
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": HEAD},
            )
            print(f"[start] Stamped alembic head {HEAD}")
        else:
            print(f"[start] Alembic current: {rows[0][0]}")

asyncio.run(sync())
PY

echo "Applying pending migrations..."
#alembic upgrade head

echo "Starting uvicorn server..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips="*"
