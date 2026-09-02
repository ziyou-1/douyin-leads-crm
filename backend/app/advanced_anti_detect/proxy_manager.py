"""
IP 代理管理器（账号-IP 永久绑定）
=================================

【核心思想】每个账号永久绑定一个住宅IP，像真人"永远在自己家上网"。

【抖音检测什么？】
1. 同一 IP 登录多个账号 → 判定"工作室" → 批量关联封号
2. 同一账号频繁换城市IP（今天北京明天纽约）→ 判定"用了代理工具"
3. 数据中心IP（阿里云/腾讯云/AWS 网段）→ 公开黑名单，直接标记可疑

【住宅代理 vs 数据中心代理（新接手开发的必读知识）】
- 住宅代理（Residential）：IP 登记在家庭宽带/移动运营商名下，抖音视为
  普通家庭用户 → 信任度高；价格约 2-3元/IP/天，略贵但必须用。
- 数据中心代理（Datacenter）：IP 登记在云厂商名下，全网黑名单公开可查，
  几乎必被识别为代理 → 封号率极高；虽然便宜（0.1-0.5元/IP/天），
  但省下的钱会加倍赔回在封号损失上。
- 结论：本项目【必须】使用住宅代理，严禁数据中心代理。

【代理服务商推荐】
- 快代理（kuaidaili.com）  ：国内最大住宅IP池，约2-3元/IP/天，稳定性最好（首选）
- 芝麻代理（zhimahttp.com）：住宅IP质量好，按天/按量计费灵活，客服响应快
- BrightData（brightdata.com）：海外最大（7200万+住宅IP），做TikTok海外版用，贵但稳

【支持的代理格式】socks5://user:pass@host:port（同时兼容 http:// 前缀）
"""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

# aiohttp 仅健康检查使用，在 health_check 内导入


class ProxyStatus(Enum):
    """代理状态：健康 / 被封"""
    HEALTHY = "healthy"
    BLOCKED = "blocked"


@dataclass
class ProxyInfo:
    """
    一个代理IP的信息。

    - proxy_url:  代理地址，格式 socks5://user:pass@host:port
    - city:       IP所在城市（换IP时优先保持同城，避免"账号换城市"被风控）
    - fail_count: 连续健康检查失败次数（达到阈值判定被封）
    """
    proxy_url: str
    city: str = "未知"
    status: ProxyStatus = ProxyStatus.HEALTHY
    fail_count: int = 0
    last_check: Optional[datetime] = None


class ProxyManager:
    """
    IP代理管理器：账号-IP永久绑定 + 定期健康检查 + 被封自动换同城IP。

    用法：
        mgr = ProxyManager(proxy_pool=[...])    # 从服务商API拉取的IP池
        url = await mgr.get_proxy(account_id)   # 拿到该账号的固定代理
        browser = await p.chromium.launch(proxy={"server": url})
    """

    CHECK_INTERVAL = 1800   # 巡检间隔30分钟：过频浪费流量、还容易惊动风控
    MAX_FAIL_COUNT = 3      # 连续失败3次才判死：单次失败可能只是网络抖动/服务商抽风
    CHECK_TIMEOUT = 10      # 健康检查超时10秒（住宅IP普遍比机房慢，别设太短）

    def __init__(self, proxy_pool: List[ProxyInfo]):
        self.proxy_pool = proxy_pool
        # 账号 → 代理 的永久绑定表（核心数据结构：一对一，绝不轻易换）
        self._binding: Dict[int, ProxyInfo] = {}
        self._check_task: Optional[asyncio.Task] = None

    async def get_proxy(self, account_id: int) -> str:
        """
        获取账号绑定的代理（核心方法）。

        已绑定且健康 → 直接返回（永久不变，像真人永远在家里上网）；
        未绑定 / 已被封 → 从池中分配新IP（优先同城市）并建立新的永久绑定。
        """
        proxy = self._binding.get(account_id)
        if proxy and proxy.status == ProxyStatus.HEALTHY:
            return proxy.proxy_url  # 已绑定：永远返回同一个IP

        # 未绑定或已被封：分配新代理（优先同城市，保持登录地稳定）
        prefer_city = proxy.city if proxy else None
        new_proxy = self._allocate(prefer_city)
        self._binding[account_id] = new_proxy
        print(f"[代理] 账号{account_id} 绑定IP: {new_proxy.proxy_url} ({new_proxy.city})")
        return new_proxy.proxy_url

    def _allocate(self, prefer_city: Optional[str]) -> ProxyInfo:
        """
        从池里挑一个健康代理（内部方法）。

        优先选同城市的（真人不会今天在上海明天突然在广州登录）；
        同城没有了才退而求其次换城市，并同时考虑补充代理池。
        """
        healthy = [p for p in self.proxy_pool if p.status == ProxyStatus.HEALTHY]
        if not healthy:
            raise RuntimeError("代理池耗尽！请联系运维补充住宅代理IP")
        same_city = [p for p in healthy if p.city == prefer_city] if prefer_city else []
        return random.choice(same_city or healthy)

    async def health_check(self, proxy: ProxyInfo) -> ProxyStatus:
        """
        IP健康检查（定期ping测试）：通过代理访问轻量接口，判断IP是否还能用。

        【注意】不要拿 douyin.com 首页当探测目标（流量大且敏感），
        用一个轻量公共接口测连通性即可；socks5 代理 aiohttp 需要
        aiohttp-socks 扩展（pip install aiohttp-socks），或改用 http 代理探测。
        """
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=self.CHECK_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://httpbin.org/ip", proxy=proxy.proxy_url) as resp:
                    ok = resp.status == 200
        except Exception:
            ok = False

        proxy.last_check = datetime.now()
        if ok:
            proxy.fail_count = 0
            proxy.status = ProxyStatus.HEALTHY
        else:
            proxy.fail_count += 1
            # 连续3次失败才判死：单次失败可能只是网络抖动，误杀会浪费好IP
            if proxy.fail_count >= self.MAX_FAIL_COUNT:
                proxy.status = ProxyStatus.BLOCKED
                print(f"[代理] {proxy.proxy_url} 连续失败{proxy.fail_count}次，判定被封")
        return proxy.status

    async def report_blocked(self, account_id: int) -> str:
        """
        业务层发现IP被封（如发送时返回403/频繁超时）→ 立刻换同城市IP。

        返回新代理URL；之后 get_proxy 也会返回这个新IP。
        """
        proxy = self._binding.get(account_id)
        if proxy:
            proxy.status = ProxyStatus.BLOCKED
        return await self.get_proxy(account_id)

    async def start_health_check_loop(self):
        """启动后台巡检任务：每30分钟检查所有已绑定IP，发现被封自动换"""
        self._check_task = asyncio.create_task(self._loop())
        print("[代理] 后台健康巡检已启动（每30分钟一次）")

    async def _loop(self):
        """后台巡检循环（内部方法）"""
        while True:
            try:
                for account_id, proxy in list(self._binding.items()):
                    status = await self.health_check(proxy)
                    if status == ProxyStatus.BLOCKED:
                        await self.get_proxy(account_id)  # 自动换IP
                await asyncio.sleep(self.CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[代理] 巡检异常: {e}")
                await asyncio.sleep(60)  # 异常后等1分钟再试，别死循环刷屏

    async def stop(self):
        """停止后台巡检（程序退出时调用）"""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
