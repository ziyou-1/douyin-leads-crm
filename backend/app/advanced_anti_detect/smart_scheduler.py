"""
智能调度 + 熔断机制
===================

【核心思想】发消息前综合判断"现在能不能发"；出现风控信号时自动保护账号，
绝不"硬发"——硬发只会把小问题升级成封号。

【抖音检测什么？】
1. 日发送量：每个号每天约 30-50 条上限（新号更少）
2. 频率：短时间连发 → 限流
3. 时段：凌晨 1-6 点发私信 = 没有真人这么干 → 重点监控
4. 风控信号：验证码 / 限流提示 / 账号锁定
5. 账号健康度：新号、被封过的号要更保守

【熔断是什么？】借自金融行业：异常时自动暂停，防止损失扩大。
- captcha（验证码）   → 休息2小时
- rate_limit（限流）  → 降速50%
- account_locked（锁号）→ 停用 + 通知

【每个阈值的取值理由】见各常量处的注释。
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

# ---- 风控信号类型（字符串常量，调用方直接传字符串即可）----
CAPTCHA = "captcha"                # 弹验证码：抖音怀疑你不是真人
RATE_LIMIT = "rate_limit"          # 限流：发太快被限制
ACCOUNT_LOCKED = "account_locked"  # 锁号：最严重，需人工介入


@dataclass
class AccountHealthScore:
    """
    账号健康度评分（0-100，越高越安全）。

    【维度与权重】（为什么这么定）：
    - 验证码次数   权重30%：验证码是抖音最直接的"怀疑信号"，权重最高
    - 发送成功率   权重30%：成功率低 = 账号大概率已被隐性限流
    - 账号年龄     权重20%：7天以上的老号，风控容忍度明显更高
    - 历史封禁记录 权重20%：被封过的号更容易再次被封（有案底）
    """
    account_id: int
    captcha_count_24h: int = 0   # 近24h验证码次数
    success_count_24h: int = 0   # 近24h发送成功数
    fail_count_24h: int = 0      # 近24h发送失败数
    account_age_days: int = 1    # 账号使用天数
    block_count_30d: int = 0     # 近30天被封次数

    def calculate(self) -> int:
        """计算健康度总分（0-100），各维度单独打分后加权求和"""
        # 维度1：验证码（0次=100分，每多1次扣40分，3次以上归零）
        captcha_score = max(0, 100 - self.captcha_count_24h * 40)
        # 维度2：成功率（无发送记录时：账号干净则给满分避免新号被误杀；
        # 但若已有验证码/封禁等负面信号，未知成功率不应乐观假设为满分，给中性分50）
        total = self.success_count_24h + self.fail_count_24h
        has_negative = self.captcha_count_24h > 0 or self.block_count_30d > 0
        if total == 0:
            success_score = 50 if has_negative else 100
        else:
            success_score = int(100 * self.success_count_24h / total)
        # 维度3：账号年龄（7天满分，线性增长；不满1天15分起步）
        age_score = min(100, int(15 + 85 * self.account_age_days / 7))
        # 维度4：封号记录（1次砍半，2次以上归零）
        block_score = max(0, 100 - self.block_count_30d * 50)
        return int(captcha_score * 0.3 + success_score * 0.3 +
                   age_score * 0.2 + block_score * 0.2)


@dataclass
class _AccountState:
    """账号运行时状态（内部数据结构）"""
    account_id: int
    sent_today: int = 0                       # 今日已发送数
    daily_limit: int = 40                     # 今日发送上限
    rest_until: Optional[datetime] = None     # 休息截止时间（验证码/失败后冷却）
    last_send_time: Optional[datetime] = None # 上次发送时间
    speed_factor: float = 1.0                 # 降速系数（1.0=全速，0.5=半速）
    disabled: bool = False                    # 是否被停用（锁号）
    health: AccountHealthScore = field(default_factory=lambda: AccountHealthScore(0))


class SmartScheduler:
    """
    智能调度器：所有发送动作前必须先问它。

    用法：
        scheduler = SmartScheduler()
        scheduler.register(account_id=1, daily_limit=40)
        if scheduler.should_send(account_id):
            await send_message(...)                          # 业务发送
            scheduler.record_send(account_id, success=True)  # 必须回填结果
        # 收到风控信号时：
        scheduler.on_risk_signal(account_id, CAPTCHA)
    """

    DEFAULT_DAILY_LIMIT = 40    # 日限40条：官方上限约50，留20%安全余量
    BASE_INTERVAL = 180         # 基础间隔180秒(3分钟)：真人发私信间隔普遍3-10分钟
    ACTIVE_HOURS = (8, 23)      # 活跃时段8-23点：凌晨1-6点发私信是重点监控对象
    CAPTCHA_REST_HOURS = 2      # 验证码后休息2小时：立刻继续=承认自己是机器人
    HEALTH_MIN_SCORE = 20       # 健康度<20分停用：低于此值账号已在悬崖边

    def __init__(self, daily_limit: int = DEFAULT_DAILY_LIMIT):
        self.daily_limit = daily_limit
        self._states: Dict[int, _AccountState] = {}
        self._notify: Optional[Callable] = None  # 锁号通知回调

    def register(self, account_id: int, daily_limit: int = 0):
        """
        注册账号到调度器（未注册的账号一律不允许发送）。

        新号建议 daily_limit=20 起步，观察一周无风控再逐步提到 40。
        """
        self._states[account_id] = _AccountState(
            account_id=account_id,
            daily_limit=daily_limit or self.daily_limit,
            health=AccountHealthScore(account_id=account_id),
        )

    # --------------------------------------------------------------
    # 核心方法1：能不能发？
    # --------------------------------------------------------------
    def should_send(self, account_id: int) -> bool:
        """
        综合判断该账号现在能不能发（日限/频率/时段/风控信号/健康度）。

        检查顺序按"最快失败优先"排列，避免无谓计算。
        想知道不能发的原因，看 get_block_reason()。
        """
        state = self._states.get(account_id)
        if state is None:
            return False  # 未注册的账号不允许发

        # 1. 是否被停用（锁号）
        if state.disabled:
            return False
        # 2. 是否在休息期（验证码/连续失败后的强制冷却）
        if state.rest_until and datetime.now() < state.rest_until:
            return False
        # 3. 今日日限
        if state.sent_today >= state.daily_limit:
            return False
        # 4. 活跃时段（凌晨不发）
        hour = datetime.now().hour
        if not (self.ACTIVE_HOURS[0] <= hour < self.ACTIVE_HOURS[1]):
            return False
        # 5. 发送间隔（结合健康度动态调整，见 get_send_interval）
        if state.last_send_time:
            elapsed = (datetime.now() - state.last_send_time).total_seconds()
            if elapsed < self.get_send_interval(account_id):
                return False
        # 6. 健康度（太低直接停）
        if state.health.calculate() < self.HEALTH_MIN_SCORE:
            return False
        return True

    def get_block_reason(self, account_id: int) -> str:
        """获取不能发送的原因（人可读，用于日志/监控）"""
        state = self._states.get(account_id)
        if state is None:
            return "账号未注册"
        if state.disabled:
            return "账号已被锁号停用"
        if state.rest_until and datetime.now() < state.rest_until:
            mins = (state.rest_until - datetime.now()).total_seconds() / 60
            return f"休息冷却中，还需{mins:.0f}分钟"
        if state.sent_today >= state.daily_limit:
            return f"今日已达上限{state.daily_limit}条"
        hour = datetime.now().hour
        if not (self.ACTIVE_HOURS[0] <= hour < self.ACTIVE_HOURS[1]):
            return f"非活跃时段({self.ACTIVE_HOURS[0]}-{self.ACTIVE_HOURS[1]}点)"
        score = state.health.calculate()
        if score < self.HEALTH_MIN_SCORE:
            return f"健康度过低({score}分)"
        return "发送间隔未到"

    # --------------------------------------------------------------
    # 核心方法2：风控信号处理（熔断）
    # --------------------------------------------------------------
    def on_risk_signal(self, account_id: int, signal_type: str):
        """
        收到风控信号时的自动处理（熔断核心）。

        | 信号            | 处理动作       | 理由                        |
        | captcha         | 休息2小时      | 已被怀疑，立刻继续=自爆      |
        | rate_limit      | 降速50%       | 已被限流，硬发会升级成封号   |
        | account_locked  | 停用+通知     | 已锁号，任何操作都是徒劳     |
        """
        state = self._states.get(account_id)
        if state is None:
            return

        if signal_type == CAPTCHA:
            # 验证码 → 强制休息2小时（冷却期任何发送请求都会被拒绝）
            state.rest_until = datetime.now() + timedelta(hours=self.CAPTCHA_REST_HOURS)
            state.health.captcha_count_24h += 1  # 计入健康度扣分
            print(f"[调度] 账号{account_id} 收到验证码 → 休息{self.CAPTCHA_REST_HOURS}小时")

        elif signal_type == RATE_LIMIT:
            # 限流 → 降速50%：发送间隔翻倍、日限减半（下限5条防止归零）
            state.speed_factor *= 0.5
            state.daily_limit = max(5, int(state.daily_limit * 0.5))
            print(f"[调度] 账号{account_id} 被限流 → 降速50%")

        elif signal_type == ACCOUNT_LOCKED:
            # 锁号 → 完全停用 + 通知管理员人工介入
            state.disabled = True
            state.health.block_count_30d += 1
            print(f"[调度][严重] 账号{account_id} 被锁号 → 已停用")
            if self._notify:
                self._notify(account_id, "账号被锁定，需要人工介入处理")

    # --------------------------------------------------------------
    # 核心方法3：动态发送间隔
    # --------------------------------------------------------------
    def get_send_interval(self, account_id: int) -> float:
        """
        根据健康度动态调整发送间隔（秒）。

        【逻辑】健康度高 → 间隔接近基础值180s；健康度低 → 间隔成倍拉长
        （最高约5倍=15分钟）。再叠加降速系数（限流后间隔翻倍）和
        ±20%随机抖动（彻底消除固定间隔特征）。
        """
        state = self._states.get(account_id)
        if state is None:
            return self.BASE_INTERVAL
        score = state.health.calculate()
        # 分档系数：80+分→×1.0；60-79→×1.5；40-59→×2.5；<40→×5.0
        multiplier = 1.0 if score >= 80 else 1.5 if score >= 60 else 2.5 if score >= 40 else 5.0
        interval = self.BASE_INTERVAL * multiplier / max(state.speed_factor, 0.1)
        return interval * random.uniform(0.8, 1.2)  # ±20%抖动去规律性

    # --------------------------------------------------------------
    # 辅助方法
    # --------------------------------------------------------------
    def record_send(self, account_id: int, success: bool):
        """每次发送后必须回填结果（用于更新健康度的成功率数据）"""
        state = self._states.get(account_id)
        if state is None:
            return
        state.sent_today += 1
        state.last_send_time = datetime.now()
        if success:
            state.health.success_count_24h += 1
        else:
            state.health.fail_count_24h += 1

    def set_notify(self, callback: Callable):
        """设置锁号通知回调，如：set_notify(lambda aid, msg: send_alert(aid, msg))"""
        self._notify = callback

    def reset_daily(self):
        """
        每天0点重置：日计数清零、限流降速恢复（健康度数据保留不重置，
        因为验证码/封号记录的冷却期是24h滚动窗口，跨天不该清零）。
        """
        for state in self._states.values():
            state.sent_today = 0
            state.speed_factor = 1.0
            state.daily_limit = self.daily_limit

    def get_status(self, account_id: int) -> dict:
        """获取账号状态摘要（用于监控面板展示）"""
        state = self._states.get(account_id)
        if state is None:
            return {}
        rest_min = 0
        if state.rest_until and datetime.now() < state.rest_until:
            rest_min = int((state.rest_until - datetime.now()).total_seconds() / 60)
        return {
            "account_id": account_id,
            "sent_today": state.sent_today,
            "daily_limit": state.daily_limit,
            "health_score": state.health.calculate(),
            "disabled": state.disabled,
            "rest_minutes": rest_min,
        }
