# 抖音线索 CRM

从抖音评论里挖高意向线索，再用扫码登录的发送号自动私信。前端是 Vue 3，后端是 FastAPI + Celery + Playwright，私信走尘锋 ChatDoing / OpenKF。

仓库是生产行为的干净副本：不含 `.env`、Cookie、`storage_state`、密钥。

## 它做什么

1. **监控**：按抖音账号或话题拉视频和评论（TikHub）。
2. **意向**：通义千问给评论打标。只有 `high` 会建线索；`mid` / `invalid` 不进私信。
3. **首条私信**：线索入队后，把评论推给 ChatDoing。真正往抖音发消息的是 ChatDoing 回调用 Playwright。
4. **跟进**：同一条线索粘在同一个发送号上；不同线索在可用发送号之间轮转。
5. **养号 / 轮询 / 风控**：定时任务里还有养号、轮询策略、发送上限和举报率检查。

后台页面：仪表盘、监控、线索、聊天、抖音账号、告警、参数配置、用户。

## 架构

```text
TikHub 评论
    ↓
LLM（.env 的 LLM_MODEL）
    ↓ 仅 high
线索 + dm_queue
    ↓
initiate_ai_conversation
    推评论到 ChatDoing（不在这里 Playwright 发送）
    ↓
ChatDoing SPI POST /open-kf/spi/v1/messages/send
    立刻 200 确认，Playwright 放后台
    ↓
抖音私信发出，写入 chat_messages.sent_at
```

Compose 服务：`nginx`、`frontend`、`web`（`:8000`）、`celery-worker`、`celery-beat`、`postgres`、`redis`。健康检查：`GET /health` → `{"status":"ok"}`。HTTP API 前缀：`/api/v1`。

## 发送规则（当前）

可用发送号必须同时满足：

- `login_status == online`
- `proxy_url` 为空，或是 `socks5://` / `http(s)://`
- Cookie 是 Playwright `storage_state` JSON（以 `{` 开头）。请求头那种短 Cookie 不能发。
- **不看客服分配**。分配只影响线索归属，不挡住自动发送。

同一线索后续消息跟 `dm_queue.send_account_id`（没有则跟最后一条 `chat_messages.douyin_account_id`）。不同线索按当日发送量在在线号之间轮转。

SPI `/messages/send` 一律当 AI 回复处理（`handle_ai_reply`），并必须先回 200 再 Playwright。如果接口等浏览器发完再返回，ChatDoing 会显示「发送失败 / 未知异常」，即使抖音其实已经发出去了。

`sent_at` 用 Python 的 UTC 当前时间，不用事务开始时的数据库 `now()`。

## 仓库结构

```text
backend/     FastAPI、Celery、Playwright、OpenKF SPI
frontend/    Vue 3 + Element Plus
nginx/       反代与 TLS
docker-compose.yml
.env.example
```

## 本地启动

需要 Docker、以及可访问的 TikHub / 通义千问 / ChatDoing 凭证。

```bash
cp .env.example .env
# 填 SECRET_KEY、数据库密码、LLM_API_KEY、SENTIMENT_API_KEY、OPENKF_* 
docker compose up -d --build
curl http://localhost:8000/health
```

首次初始化会建默认管理员（见 `backend/app/init_db.py`）。上线后立刻改密码。

生产发送必须把 `DOUYIN_AUTOMATION_MODE` 设成真实 Playwright 模式，不要留 `mock`。发送号在「抖音账号」里扫码登录，确认状态是 `online`，Cookie 是完整 `storage_state`。

不要执行 `docker compose down` 来热修。改代码后重启 `web` / `celery-worker` / `celery-beat`；若出现 502 再重启 `nginx`。

## 环境变量

只列名字，不要把真实值写进仓库。完整模板在根目录 `.env.example`。

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` / `POSTGRES_*` | PostgreSQL |
| `REDIS_URL` / `CELERY_*` | Redis 与任务队列 |
| `SECRET_KEY` | JWT |
| `SENTIMENT_API_KEY` / `SENTIMENT_API_URL` | TikHub 拉评论、视频 |
| `LLM_API_KEY` / `LLM_API_URL` / `LLM_MODEL` | 意向模型。适配器读的是 `.env`，不是后台「AI模型名称」 |
| `OPENKF_*` | 尘锋 ChatDoing |
| `DOUYIN_AUTOMATION_MODE` / `PLAYWRIGHT_*` | 浏览器发送 |
| `DM_*` | 日限额、发送窗口、批大小 |

## 定时任务

| 任务 | 节奏 |
| --- | --- |
| 监控 / 话题 / 视频评论采集 | 每分钟检查 |
| 新评论意向 | 30 秒 |
| 私信队列 | 每分钟 |
| 同步 ChatDoing 收件箱 | 180 秒 |
| Cookie 探活 / 续期 | 每 6 小时的 :30 |
| 养号 | 每天 10:30 |
| 未发送队列滚到次日 | 23:00 |

后台「登录状态」来自 Playwright 探活，可能落后于真实抖音会话。Cookie 死后，界面可能仍显示 `online`，直到下一次检查。

## 已知上限

- Playwright 会偶发超时，重试后可能成功。失败队列项不会自动重试。
- `process_queue` 一批结束才提交，队列界面在跑批期间可能一直显示「待处理」。
- ChatDoing 里已经打上的「发送失败」徽章，没有状态回写接口，改不了历史记录。
- 评论长度小于 3、或超出约 20 分钟新鲜窗口的，不会进意向。
- 监控号必须填真实 `sec_uid`。UID 填错时，最新视频可能是 0 条评论。

## 不要提交

`.env`、Cookie 原文、Playwright `storage_state`、真实 Token、账号密码。
