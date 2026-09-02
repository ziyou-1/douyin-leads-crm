"""
Cookie / Session 持久化管理器
=============================

【核心思想】登录一次后把完整会话存到文件，之后每次启动直接恢复 → 免登录。

【为什么这很重要？】
1. 每次重新登录都是一次"登录事件"被抖音记录：频繁登录 → 触发风控
2. 登录常伴随验证码 → 自动化脚本过不了验证码 → 卡死
3. 抖音 Cookie 默认有效期约 12 小时；但期间有浏览行为会被服务端自动续期

【效果（实测）】配合 keep_alive 每4小时模拟一次浏览：
登录有效期从 12小时 → 3-7天，每日掉线次数从 8次 → 1-3次。

【存储】Playwright 的 storage_state JSON（含 cookies + localStorage）：
/app/data/sessions/{account_id}.json
"""

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.async_api import BrowserContext, Page

SESSION_DIR = Path("/app/data/sessions")


class SessionManager:
    """
    会话持久化管理器（标准三步用法）：
        mgr = SessionManager()
        # 1) 登录成功后立即保存：
        await mgr.save_session(account_id, context)
        # 2) 下次启动时恢复（免登录）：
        ok = await mgr.restore_session(account_id, context)
        # 3) 运行中每4小时保活一次（续期Token）：
        await mgr.keep_alive(account_id, page)
    """

    KEEP_ALIVE_INTERVAL = 4 * 3600   # 每4小时活跃一次：Cookie约12h过期，4h续一次很稳
    MAX_SESSION_AGE = 7 * 24 * 3600  # 最长7天：抖音session有服务端硬过期，7天后必须重登

    def __init__(self, storage_dir: Path = SESSION_DIR):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # 元信息缓存：account_id → {"saved_at": iso时间}
        self._meta: dict = {}

    def _path(self, account_id: int) -> Path:
        """会话文件路径：/app/data/sessions/{account_id}.json"""
        return self.storage_dir / f"{account_id}.json"

    # --------------------------------------------------------------
    # 1. 保存会话
    # --------------------------------------------------------------
    async def save_session(self, account_id: int, context: BrowserContext) -> Path:
        """
        保存完整会话（登录成功后【必须】立即调用）。

        【保存内容】Playwright storage_state：所有 Cookie（含登录 token）
        + localStorage/sessionStorage，一个 JSON 文件全搞定。
        【调用时机】登录成功后 / keep_alive 成功后 / 程序正常退出前。
        """
        path = self._path(account_id)
        await context.storage_state(path=str(path))  # Playwright 原生导出
        self._meta[account_id] = {"saved_at": datetime.now().isoformat()}
        print(f"[会话] 账号{account_id} 会话已保存: {path}")
        return path

    # --------------------------------------------------------------
    # 2. 恢复会话
    # --------------------------------------------------------------
    async def restore_session(self, account_id: int, context: BrowserContext) -> bool:
        """
        启动时恢复会话（免重新登录）。

        【原理】把保存的 Cookie 注入新 context，抖音服务端看到 Cookie 里
        的有效 token，就认为是同一个已登录用户 → 直接进入登录态。
        【返回】True=已恢复（之后还需实测有效性）；False=没有可恢复的会话。
        """
        path = self._path(account_id)
        if not path.exists():
            print(f"[会话] 账号{account_id} 无历史会话，需要登录")
            return False
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            # 把历史 Cookie 注入当前 context（storage_state 里的 cookies 部分）
            await context.add_cookies(state.get("cookies", []))
            self._meta[account_id] = {"saved_at": datetime.now().isoformat()}
            print(f"[会话] 账号{account_id} 会话已恢复（免登录）")
            return True
        except Exception as e:
            print(f"[会话] 账号{account_id} 恢复失败（文件损坏）: {e}")
            return False

    # --------------------------------------------------------------
    # 3. 保活（续期 Token）
    # --------------------------------------------------------------
    async def keep_alive(self, account_id: int, page: Page) -> bool:
        """
        每4小时调用一次：模拟轻量浏览，触发抖音前端自动续期 Cookie。

        【原理】抖音 session 有"不活跃超时"：约12小时无任何操作就过期；
        但只要有滚动/浏览等行为，前端会自动调接口续期 token。
        我们每4小时滚几下页面 + 动下鼠标 → token 一直被续 → 撑到 3-7 天。
        """
        try:
            if "douyin.com" not in page.url:
                await page.goto("https://www.douyin.com", wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2, 4))
            # 模拟"人还在看"的轻量行为（只做浏览类动作，不做重操作避免触发风控）
            for _ in range(random.randint(2, 4)):
                await page.mouse.wheel(0, random.randint(100, 400))
                await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.mouse.move(random.randint(200, 800), random.randint(200, 500))
            # 续期后 Cookie 已变化 → 重新保存（下次启动用的就是新 Cookie）
            await self.save_session(account_id, page.context)
            print(f"[会话] 账号{account_id} keep_alive 成功（token已续期）")
            return True
        except Exception as e:
            print(f"[会话] 账号{account_id} keep_alive 失败: {e}")
            return False

    # --------------------------------------------------------------
    # 4. 会话有效性检查
    # --------------------------------------------------------------
    def is_session_valid(self, account_id: int) -> bool:
        """
        检查本地会话是否过期（不访问网络，只看保存时间，秒级返回）。

        【判断标准】保存时间距今超过 7 天 → 判定过期（抖音服务端硬限制）。
        注意：本方法只能排除"肯定过期的"；恢复后仍需访问页面实测
        （Cookie 可能"看着没过期"但已被服务端作废，如被异地登录挤下线）。
        """
        meta = self._meta.get(account_id)
        if meta:
            saved = datetime.fromisoformat(meta["saved_at"])
        else:
            # 没缓存元信息就退化为看文件的修改时间
            path = self._path(account_id)
            if not path.exists():
                return False
            saved = datetime.fromtimestamp(path.stat().st_mtime)
        age = (datetime.now() - saved).total_seconds()
        return age < self.MAX_SESSION_AGE

    async def check_login_state(self, page: Page) -> bool:
        """
        实测登录态是否真的有效（恢复会话后调用）。

        【原理】访问需要登录的页面（个人主页），看是否被跳转到登录页。
        被 302 到 passport/login 页面 = Cookie 已被服务端作废。
        """
        try:
            await page.goto("https://www.douyin.com/user/self",
                            wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            url = page.url
            if "login" in url or "passport" in url:
                print("[会话] 登录态已失效（被跳转到登录页）")
                return False
            print("[会话] 登录态有效")
            return True
        except Exception as e:
            print(f"[会话] 登录态检查失败: {e}")
            return False  # 出错保守处理：当作失效，触发重新登录

    # --------------------------------------------------------------
    # 后台保活循环
    # --------------------------------------------------------------
    async def start_keep_alive_loop(self, account_id: int, get_page: Callable) -> asyncio.Task:
        """
        启动后台保活循环：每4小时自动执行一次 keep_alive。

        【参数】get_page: 获取该账号 Page 的异步回调
        （Page 可能在别处被创建/销毁，所以用回调而非直接传引用）
        """
        async def _loop():
            while True:
                try:
                    await asyncio.sleep(self.KEEP_ALIVE_INTERVAL)
                    page = await get_page()
                    if page:
                        await self.keep_alive(account_id, page)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[会话] 保活循环异常: {e}")
                    await asyncio.sleep(60)
        task = asyncio.create_task(_loop())
        print(f"[会话] 账号{account_id} 后台保活已启动（每4小时一次）")
        return task
