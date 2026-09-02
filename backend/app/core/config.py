from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Douyin Lead Mining System"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database (PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/douyin_leads"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT / Auth
    SECRET_KEY: str = "change-me-in-production-super-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Sentiment Analysis API
    SENTIMENT_API_KEY: str = ""
    SENTIMENT_API_URL: str = "https://api.tikhub.io"
    SENTIMENT_API_TIMEOUT: float = 30.0
    SENTIMENT_MAX_PAGES: int = 5
    SENTIMENT_TOPIC_VIDEO_LIMIT: int = 5

    # LLM API (通义千问 Qwen)
    LLM_API_KEY: str = ""
    LLM_API_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    LLM_MODEL: str = "qwen3.8-max"

    # OpenKF SPI (Dustess Chatdoing)
    OPENKF_APPID: str = ""
    OPENKF_KEY_ID: str = ""
    OPENKF_KEY: str = ""  # Base64-encoded 32-byte AES key
    OPENKF_CALLBACK_URL: str = ""  # chatdoing callback base URL(纯域名根地址，不带路径)
    OPENKF_LOCAL_APP_ID: str = ""  # local app ID for callback path

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Risk control - chat automation
    DAILY_SEND_LIMIT: int = 50
    MIN_SEND_INTERVAL: int = 2  # seconds
    MAX_SEND_INTERVAL: int = 5  # seconds
    WORK_HOURS_START: int = 9
    WORK_HOURS_END: int = 22
    MAX_ACCOUNTS_PER_USER: int = 10

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # 账号管理配置
    ACCOUNT_POOL_MAX: int = 1000  # 监控池上限
    ACCOUNT_CLEAN_DAYS: int = 14  # N天无high评论视为低质
    ACCOUNT_CLEAN_INTERVAL_DAYS: int = 7  # 清洗周期

    # 全网发现配置
    DISCOVERY_KEYWORDS: str = "婚姻挽回,老公出轨,分手复合,离婚,断联,原配挽回,婚姻修复"
    DISCOVERY_MAX_PAGES: int = 300  # 最大检索分页
    DISCOVERY_HIGH_THRESHOLD: int = 30  # 新账号入选阈值(≥N条high评论)
    DISCOVERY_VIDEO_DAYS: int = 3  # 视频发布N天内

    # API Quota (daily limits)
    DAILY_MAX_COMMENT_REQUESTS: int = 60000  # 评论接口每日上限
    DAILY_MAX_VIDEO_REQUESTS: int = 20000     # 作品接口每日上限
    QUOTA_WARNING_THRESHOLD: float = 0.9     # 90%触发告警
    QUOTA_CRITICAL_THRESHOLD: float = 1.0    # 100%触发严重告警+暂停
    QUOTA_REDIS_TTL_SECONDS: int = 25 * 3600  # 25小时自动过期

    # 视频轮询配置
    VIDEO_LIFECYCLE_DAYS: int = 14  # 视频生命周期(天)
    HIGH_HEAT_THRESHOLD: int = 200  # 高热视频评论阈值(仅用于展示分级,不影响轮询频率)
    ACCOUNT_SYNC_INTERVAL_HOURS: int = 6  # 账号作品全量同步间隔(小时,处理过期/生命周期)
    ACCOUNT_ACTIVE_VIDEO_LIMIT: int = 1  # 每个监控账号默认只主动轮询评论的视频数(按发布时间取最新N条,其余置为inactive)
    MAX_CONCURRENT_VIDEO_POLL: int = 2  # 视频评论轮询最大并发数

    VIDEO_POLL_INTERVAL_MINUTES: float = 2.5  # 每个视频固定轮询间隔(分钟),不再区分热度/降级
    COMMENT_PAGE_SIZE: int = 20  # 单页评论拉取条数
    COMMENT_AI_FRESHNESS_MINUTES: int = 20  # 评论发布后N分钟内才送AI分析,超时只入库不分析
    LEAD_HIGH_INTENT_MINUTES: int = 8  # AI判定高意向时,评论发布距分析时刻在N分钟内记为high,超过(仍在新鲜度窗口内)记为medium
    FIRST_POLL_BACKFILL_HOURS: int = 24  # 视频首次纳入轮询时,向前回溯抓取评论的时间窗口(小时)

    # 私信发送队列配置
    DM_DAILY_GLOBAL_LIMIT: int = 5000  # 全局每日上限
    DM_DAILY_SAFE_LIMIT: int = 4000  # 运行安全线(预留20%)
    DM_ACCOUNT_DAILY_LIMIT: int = 100  # 单账号每日上限
    DM_SEND_WINDOW_START: int = 8  # 发送窗口开始(时)
    DM_SEND_WINDOW_END: int = 23  # 发送窗口结束(时)
    DM_USER_DEDUP_DAYS: int = 7  # 同一用户去重天数
    DM_MIN_INTERVAL_SEC: int = 3  # 最小发送间隔(秒)
    DM_MAX_INTERVAL_SEC: int = 8  # 最大发送间隔(秒)
    DM_BATCH_SIZE: int = 8  # 每次process_queue处理的条数

    # AI对话配置
    AI_MAX_ROUNDS: int = 5  # 最多AI对话轮次，超过强制转人工
    AI_CHAT_TEMPLATES_COUNT: int = 3  # 话术模板套数(轮换用)

    # 风控配置 — 举报拉黑率熔断
    REPORT_RATE_WARNING: float = 0.007  # 举报拉黑率0.7%降量
    REPORT_RATE_CRITICAL: float = 0.01  # 举报拉黑率1.0%暂停
    DM_THROTTLE_RATIO: float = 0.5  # 降量比例(50%)
    RISK_MIN_SAMPLE: int = 50  # 样本量不足此值不触发风控

    # 抖音私信自动化通道 — Playwright浏览器自动化
    DOUYIN_AUTOMATION_MODE: str = "mock"  # mock / playwright
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_NAV_TIMEOUT_MS: int = 30000
    PLAYWRIGHT_QR_LOGIN_TTL_SEC: int = 120  # 二维码有效期
    PLAYWRIGHT_CONTEXT_IDLE_MIN: int = 30  # 浏览器上下文空闲多久后回收

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
