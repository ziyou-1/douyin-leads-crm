"""
抖音私信浏览器自动化服务。

提供统一的自动化接口 DouyinAutomation，两种实现:
- MockDouyinAutomation: 开发/测试用模拟实现
- PlaywrightDouyinAutomation: 基于Playwright驱动真实Chromium的生产实现

通过 DOUYIN_AUTOMATION_MODE 配置项切换(mock / playwright)。
"""
import asyncio
import base64
import hashlib
import json
import logging
import random
import re
import time
import uuid
from typing import List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class DouyinAutomation:
    """抖音自动化操作抽象接口。"""

    async def check_session_valid(self, cookie_data: str) -> bool:
        raise NotImplementedError

    async def send_private_message(
        self, cookie_data: str, target_uid: str, content: str
    ) -> Tuple[bool, str]:
        """发送私信。返回 (是否成功, 失败原因)。"""
        raise NotImplementedError

    async def fetch_new_messages(self, cookie_data: str, target_uid: str) -> List[dict]:
        raise NotImplementedError

    async def start_qr_login(self) -> Tuple[str, str]:
        """开始扫码登录。返回 (login_session_id, 二维码图片base64)。"""
        raise NotImplementedError

    async def poll_qr_login(self, login_session_id: str) -> dict:
        """轮询扫码登录状态。返回 {status, storage_state, qr_image_base64,
        verify_message, verify_image_base64}。

        status: pending(待扫码) / confirmed(已确认登录) / expired(已过期) /
                need_verification(触发异地登录二次验证，需要短信验证码)
        qr_image_base64: pending时可能带上刷新后的二维码图片(抖音端会自动更换二维码)
        verify_message/verify_image_base64: need_verification时附带的提示文案和当前页面截图
        """
        raise NotImplementedError

    async def submit_verification_code(self, login_session_id: str, code: str) -> dict:
        """提交异地登录二次验证的短信验证码。返回值结构同poll_qr_login。"""
        raise NotImplementedError

    async def close(self) -> None:
        pass


class MockDouyinAutomation(DouyinAutomation):
    """开发/测试用模拟实现，不依赖真实浏览器。"""

    _MOCK_QR_PNG = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "YPhfz0AEYBxVSF+FABJYAtNIt0ZTAAAAAElFTkSuQmCC"
    )

    async def check_session_valid(self, cookie_data: str) -> bool:
        await asyncio.sleep(random.uniform(0.2, 0.5))
        return True

    async def send_private_message(
        self, cookie_data: str, target_uid: str, content: str
    ) -> Tuple[bool, str]:
        await asyncio.sleep(random.uniform(2.0, 5.0))
        logger.info("[Mock] send_private_message to %s: success", target_uid)
        return True, ""

    async def fetch_new_messages(self, cookie_data: str, target_uid: str) -> List[dict]:
        await asyncio.sleep(random.uniform(0.3, 0.8))
        return []

    async def start_qr_login(self) -> Tuple[str, str]:
        await asyncio.sleep(0.2)
        return f"mock-{uuid.uuid4().hex[:8]}", self._MOCK_QR_PNG

    async def poll_qr_login(self, login_session_id: str) -> dict:
        await asyncio.sleep(0.2)
        return {
            "status": "confirmed", "storage_state": "{}", "qr_image_base64": None,
            "verify_message": None, "verify_image_base64": None,
        }

    async def submit_verification_code(self, login_session_id: str, code: str) -> dict:
        await asyncio.sleep(0.2)
        return {
            "status": "confirmed", "storage_state": "{}", "qr_image_base64": None,
            "verify_message": None, "verify_image_base64": None,
        }


class PlaywrightDouyinAutomation(DouyinAutomation):
    """基于Playwright的抖音网页版(www.douyin.com)浏览器自动化实现。

    重要提示: 抖音网页前端DOM结构会持续变化。_SEL_QR_IMAGE(img[aria-label='二维码'])
    已在真实网络环境下实测验证有效(能截取到可扫描的真实二维码)。私信相关的
    _SEL_CHAT_INPUT / _SEL_CHAT_SEND_BUTTON / _SEL_CHAT_MESSAGE_ITEM
    因缺少已登录账号无法实测，仍是根据抖音网页版通用
    结构推断的最佳猜测，上线前必须用真实账号人工核对一遍并按实际情况调整。
    """

    HOME_URL = "https://www.douyin.com/"
    USER_URL_TMPL = "https://www.douyin.com/user/{sec_uid}"

    # 登录态判定: 未登录时不存在这些会话cookie，是抖音/字节体系登录后
    # 才会写入的cookie，比依赖易变的DOM class名更稳定。名字列了几个常见的
    # 备选，避免因单一cookie名不匹配导致登录成功却一直判定为未登录。
    _LOGIN_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")

    _SEL_QR_IMAGE = "img[aria-label='二维码']"
    _SEL_CHAT_INPUT = ".messageEditorinputArea[contenteditable='true']"
    _SEL_CHAT_SEND_BUTTON = ".e2e-send-msg-btn"
    _SEL_CHAT_MESSAGE_ITEM = "[class*='message-item'], [class*='msg-item']"

    # 异地登录二次验证(短信验证码)相关选择器: 抖音会随机弹出"验证码"输入弹层，
    # 具体DOM结构未能实测拿到真实样本，这里用占位符/文案等通用特征匹配来
    # 提高命中率，而非依赖某个具体class名。命中不准时可结合poll/submit返回的
    # verify_image_base64截图和日志里的候选元素信息再调整。
    _SEL_VERIFY_CODE_CANDIDATES = (
        "input[placeholder*='验证码']",
        "input[type='tel']",
        "input[type='number']",
        "input[type='text']",
    )
    _VERIFY_SUBMIT_TEXTS = ("确认", "确定", "登录", "下一步", "验证", "完成", "提交")

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._contexts: dict[str, dict] = {}  # key(账号cookie哈希) -> {context, last_used}
        self._qr_sessions: dict[str, dict] = {}  # session_id -> {context, page, created_at}
        self._init_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    # ── 浏览器生命周期 ────────────────────────────────────────────────────

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        async with self._init_lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.PLAYWRIGHT_HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            if self._cleanup_task is None:
                self._cleanup_task = asyncio.create_task(self._idle_context_reaper())
            logger.info("PlaywrightDouyinAutomation: browser launched")

    async def close(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
        for entry in list(self._contexts.values()):
            await self._safe_close(entry["context"])
        self._contexts.clear()
        for entry in list(self._qr_sessions.values()):
            await self._safe_close(entry["context"])
        self._qr_sessions.clear()
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @staticmethod
    async def _safe_close(obj):
        try:
            await obj.close()
        except Exception:
            pass

    async def _idle_context_reaper(self):
        """周期性回收长时间未使用的浏览器上下文/未完成的扫码会话，避免内存无限增长。

        扫码登录对话框如果被用户直接关掉(不等确认或过期就退出)，之前没有
        主动清理机制，_qr_sessions里对应的浏览器上下文和页面会一直占用不释放，
        积累多次后会拖慢甚至拖垮浏览器实例。这里按TTL统一清一遍。
        """
        idle_limit = settings.PLAYWRIGHT_CONTEXT_IDLE_MIN * 60
        while True:
            await asyncio.sleep(300)
            now = time.time()
            for key, entry in list(self._contexts.items()):
                if now - entry["last_used"] > idle_limit:
                    await self._safe_close(entry["context"])
                    self._contexts.pop(key, None)
                    logger.info("PlaywrightDouyinAutomation: idle context evicted key=%s", key)
            for session_id, entry in list(self._qr_sessions.items()):
                if now - entry["created_at"] > settings.PLAYWRIGHT_QR_LOGIN_TTL_SEC:
                    await self._discard_qr_session(session_id)
                    logger.info(
                        "PlaywrightDouyinAutomation: abandoned qr session evicted id=%s",
                        session_id,
                    )

    @staticmethod
    def _context_key(cookie_data: str) -> str:
        return hashlib.sha1(cookie_data.encode("utf-8")).hexdigest()[:16]

    async def _get_context(self, cookie_data: str, account_id: int | None = None, proxy_url: str = ""):
        """按账号(cookie+代理)复用浏览器上下文，并注入固定指纹伪装。"""
        await self._ensure_browser()
        key = self._context_key(f"{cookie_data}|{proxy_url}|{account_id}")
        entry = self._contexts.get(key)
        if entry is not None:
            entry["last_used"] = time.time()
            return entry["context"]

        storage_state = None
        if cookie_data:
            try:
                storage_state = json.loads(cookie_data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("PlaywrightDouyinAutomation: cookie_data不是有效的storage_state JSON")

        from app.services.anti_detect_service import apply_context_stealth, build_context_kwargs
        extra = await build_context_kwargs(cookie_data, account_id=account_id, proxy_url=proxy_url)
        profile = extra.pop("profile")
        context = await self._browser.new_context(storage_state=storage_state, **extra)
        await apply_context_stealth(context, profile)
        self._contexts[key] = {"context": context, "last_used": time.time()}
        return context

    async def _is_logged_in(self, page) -> bool:
        try:
            cookies = await page.context.cookies()
            return any(c["name"] in self._LOGIN_COOKIE_NAMES for c in cookies)
        except Exception:
            return False

    async def _qr_still_visible(self, page) -> bool:
        """判断二维码是否还在。抖音客户端会周期性自动刷新二维码(替换src/短暂
        隐藏再显示)，单次is_visible()检测可能刚好卡在刷新的一瞬间被误判为
        "已消失"，因此用短间隔重试几次，只有连续都检测不到才算真的消失。
        """
        for _ in range(3):
            try:
                if await page.locator(self._SEL_QR_IMAGE).first.is_visible():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.4)
        return False

    async def _is_identity_verification_page(self, page) -> bool:
        """检测抖音"身份验证"选择页(标题精确文案"身份验证"，列出接收短信验证码/
        验证登录密码/发送短信验证等选项)。这是异地登录二次验证的真实入口，
        比泛泛的"验证码"字样靠谱得多。"""
        try:
            return await page.locator("text=身份验证").first.is_visible()
        except Exception:
            return False

    async def _click_receive_sms_option(self, page) -> bool:
        """在身份验证选择页里点"接收短信验证码"，推进到真正的验证码输入步骤。"""
        try:
            option = page.locator("text=接收短信验证码").first
            if await option.is_visible():
                await option.click()
                return True
        except Exception as exc:
            logger.warning("_click_receive_sms_option failed: %s", exc)
        return False

    async def _extract_verification_hint(self, page) -> Optional[str]:
        """从页面文案里提取验证提示。只信任脱敏手机号这种强信号，因为"验证码"
        字样本身在登录弹层里(验证码登录tab)一直存在，不能作为触发判断依据，
        否则会把二维码刷新的正常瞬间误判成需要验证。
        """
        try:
            text = await page.inner_text("body")
        except Exception:
            return None
        match = re.search(r"1\d{2}\*{2,8}\d{2,4}", text)
        if match:
            return f"抖音检测到异地登录，请查看手机号{match.group(0)}收到的短信验证码并在下方输入"
        return None

    async def _capture_full_page(self, page) -> Optional[str]:
        """截取当前页面全图，用于身份验证提示展示给前端。"""
        try:
            shot = await page.screenshot(timeout=5000)
            return base64.b64encode(shot).decode("ascii")
        except Exception as exc:
            logger.warning("_capture_full_page failed: %s", exc)
            return None

    async def _find_verify_anchor_box(self, page) -> Optional[dict]:
        """定位验证码弹层的锚点(脱敏手机号提示文字，如"139******58")的
        屏幕坐标包围盒。选择器(input[type='text']等)非常通用，登录弹层
        背后可能还叠着一个"验证码登录"tab里同样长相的输入框，仅凭
        is_visible()两个都算可见，会误选中用户实际看不到的那个。用
        这个锚点的位置做参照，就近找输入框/按钮，避免选错。
        """
        try:
            candidates = page.locator("text=/1\\d{2}\\*{2,8}\\d{2,4}/")
            count = await candidates.count()
            for i in range(count):
                el = candidates.nth(i)
                if await el.is_visible():
                    box = await el.bounding_box()
                    if box:
                        return box
        except Exception:
            pass
        return None

    async def _nearest_visible_by_selectors(
        self, page, selectors, anchor_box: Optional[dict],
        min_width: float = 0, max_dist: float = 400,
    ):
        best_el = None
        best_dist = None
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
            except Exception:
                continue
            for i in range(count):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    box = await el.bounding_box()
                except Exception:
                    box = None
                if not box:
                    continue
                # 国家/地区代码选择框("+86"之类)、小图标按钮等宽度很窄，
                # 真正的验证码输入框/提交按钮不会这么窄，用最小宽度过滤掉，
                # 避免几何距离碰巧更近就被误选中。
                if box["width"] < min_width:
                    continue
                if anchor_box is None:
                    return el
                dx = (box["x"] + box["width"] / 2) - (anchor_box["x"] + anchor_box["width"] / 2)
                dy = (box["y"] + box["height"] / 2) - (anchor_box["y"] + anchor_box["height"] / 2)
                dist = (dx * dx + dy * dy) ** 0.5
                if dist > max_dist:
                    continue
                # 验证码弹层内的输入框/按钮通常都在提示文字下方，对出现在
                # 提示文字上方的候选加惩罚分，因为那更可能是背后其它弹层里
                # 恰好选择器也匹配上的无关元素。
                penalty = 0 if dy >= -5 else 5000
                dist += penalty
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_el = el
        return best_el

    async def _locate_verify_input(self, page):
        anchor_box = await self._find_verify_anchor_box(page)
        return await self._nearest_visible_by_selectors(
            page, self._SEL_VERIFY_CODE_CANDIDATES, anchor_box, min_width=100,
        )

    async def _locate_verify_submit(self, page):
        anchor_box = await self._find_verify_anchor_box(page)
        # 抖音这个"验证"按钮实测既不是<button>标签也没有role='button'属性，
        # 只是个普通div/span，之前用button/div[role='button']选择器完全
        # 匹配不到，导致submit_el一直是None，代码走进else分支按Enter键，
        # 但这个输入框没有绑定回车提交，等于验证码从头到尾都没真正交出去。
        # 改用精确整串文字匹配(不限标签)，避免被"接收短信验证码"这种
        # 包含"验证"子串的其它文案误命中。
        selectors = []
        for text in self._VERIFY_SUBMIT_TEXTS:
            selectors.append(f'text="{text}"')
            selectors.append(f"button:has-text('{text}')")
            selectors.append(f"div[role='button']:has-text('{text}')")
        return await self._nearest_visible_by_selectors(
            page, selectors, anchor_box, min_width=40,
        )

    @staticmethod
    def _status_dict(
        status: str,
        storage_state: Optional[str] = None,
        qr_image_base64: Optional[str] = None,
        verify_message: Optional[str] = None,
        verify_image_base64: Optional[str] = None,
    ) -> dict:
        return {
            "status": status,
            "storage_state": storage_state,
            "qr_image_base64": qr_image_base64,
            "verify_message": verify_message,
            "verify_image_base64": verify_image_base64,
        }

    async def _finalize_login(self, login_session_id: str, entry: dict) -> dict:
        storage_state = await entry["context"].storage_state()
        cookie_json = json.dumps(storage_state, ensure_ascii=False)

        # 登录成功的上下文直接转正复用，避免刚登录又重新创建上下文
        self._qr_sessions.pop(login_session_id, None)
        key = self._context_key(cookie_json)
        self._contexts[key] = {"context": entry["context"], "last_used": time.time()}
        await self._safe_close(entry["page"])

        return self._status_dict("confirmed", storage_state=cookie_json)

    # ── 会话校验 ──────────────────────────────────────────────────────────

    async def check_session_valid(self, cookie_data: str) -> bool:
        if not cookie_data:
            return False
        context = await self._get_context(cookie_data)
        page = await context.new_page()
        try:
            await page.goto(self.HOME_URL, timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS)
            return await self._is_logged_in(page)
        except Exception as exc:
            logger.warning("check_session_valid failed: %s", exc)
            return False
        finally:
            await self._safe_close(page)

    # ── 发送私信 ──────────────────────────────────────────────────────────

    async def send_private_message(
        self, cookie_data: str, target_uid: str, content: str,
        account_id: int | None = None, proxy_url: str = "",
    ) -> Tuple[bool, str]:
        context = await self._get_context(cookie_data, account_id=account_id, proxy_url=proxy_url)
        page = await context.new_page()
        try:
            await page.goto(
                self.USER_URL_TMPL.format(sec_uid=target_uid),
                timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS,
            )
            if not await self._is_logged_in(page):
                return False, "会话已失效，需要重新登录"

            from app.core.config import settings as _settings
            if _settings.DOUYIN_AUTOMATION_MODE == "playwright":
                from app.services.daily_warmup import warmup_before_dm
                from app.services.auto_nurture_v2 import PreInteraction
                await warmup_before_dm(page, self._context_key(cookie_data))
                await PreInteraction().interact_before_dm(page, target_uid)
                await page.goto(
                    self.USER_URL_TMPL.format(sec_uid=target_uid),
                    timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS,
                )

            await page.get_by_role(
                "button", name="私信", exact=True
            ).first.click(timeout=10000)
            await page.wait_for_selector(self._SEL_CHAT_INPUT, timeout=25000)

            # 逐字符模拟真人输入节奏，避免整段粘贴触发异常行为检测
            input_box = page.locator(self._SEL_CHAT_INPUT).last
            await input_box.click()
            for ch in content:
                await input_box.type(ch, delay=random.uniform(40, 120))
            await asyncio.sleep(random.uniform(0.3, 0.8))

            await page.click(self._SEL_CHAT_SEND_BUTTON, timeout=5000)
            await asyncio.sleep(random.uniform(0.5, 1.0))
            return True, ""
        except Exception as exc:
            logger.error("send_private_message failed target=%s error=%s", target_uid, exc)
            return False, str(exc)
        finally:
            await self._safe_close(page)

    # ── 拉取消息 ──────────────────────────────────────────────────────────

    async def fetch_new_messages(self, cookie_data: str, target_uid: str) -> List[dict]:
        context = await self._get_context(cookie_data)
        page = await context.new_page()
        try:
            await page.goto(
                self.USER_URL_TMPL.format(sec_uid=target_uid),
                timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS,
            )
            await page.get_by_role(
                "button", name="私信", exact=True
            ).first.click(timeout=10000)
            await page.wait_for_selector(self._SEL_CHAT_MESSAGE_ITEM, timeout=10000)
            texts = await page.locator(self._SEL_CHAT_MESSAGE_ITEM).all_inner_texts()
            return [{"content": text} for text in texts[-20:]]
        except Exception as exc:
            logger.warning("fetch_new_messages failed target=%s error=%s", target_uid, exc)
            return []
        finally:
            await self._safe_close(page)

    # ── 二维码登录 ────────────────────────────────────────────────────────

    async def start_qr_login(self) -> Tuple[str, str]:
        await self._ensure_browser()
        context = await self._browser.new_context(
            user_agent=self._UA,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await context.new_page()
        session_id = uuid.uuid4().hex

        try:
            # 未登录态访问首页会自动弹出"扫码登录"弹窗(扫码登录为默认选中tab)
            await page.goto(self.HOME_URL, timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS)
            qr_element = page.locator(self._SEL_QR_IMAGE).first
            # 浏览器刚冷启动时首次导航加载明显更慢，15秒偶尔不够等到二维码
            # 元素挂载，放宽到30秒；前端起始调用超时也留了60秒余量能兼容。
            await qr_element.wait_for(timeout=30000)
            # 二维码图片元素挂载后，真实的base64图案数据是异步填充的，
            # 需要等待src属性变为真实的data URI再截图，否则会截到占位图。
            await page.wait_for_function(
                """(el) => el.getAttribute('src') && el.getAttribute('src').length > 200""",
                arg=await qr_element.element_handle(),
                timeout=20000,
            )
            qr_bytes = await qr_element.screenshot()
            qr_base64 = base64.b64encode(qr_bytes).decode("ascii")
        except Exception:
            await self._safe_close(page)
            await self._safe_close(context)
            raise

        self._qr_sessions[session_id] = {
            "context": context,
            "page": page,
            "created_at": time.time(),
            "lock": asyncio.Lock(),
        }
        return session_id, qr_base64

    async def poll_qr_login(self, login_session_id: str) -> dict:
        entry = self._qr_sessions.get(login_session_id)
        if entry is None:
            return self._status_dict("expired")

        if time.time() - entry["created_at"] > settings.PLAYWRIGHT_QR_LOGIN_TTL_SEC:
            await self._discard_qr_session(login_session_id)
            return self._status_dict("expired")

        # 前端用定时器轮询，网络慢或浏览器操作耗时较长时可能出现上一次还没
        # 返回、下一次又发起的重叠请求；多个协程同时操作同一个 Playwright
        # page 会互相打断导航(ERR_ABORTED)、抢占元素，表现为反复自愈失败。
        # 用会话级锁串行化，避免并发操作同一个 page。
        lock: asyncio.Lock = entry.setdefault("lock", asyncio.Lock())
        if lock.locked():
            return self._status_dict("pending")

        async with lock:
            return await self._poll_qr_login_locked(login_session_id, entry)

    async def _poll_qr_login_locked(self, login_session_id: str, entry: dict) -> dict:
        page = entry["page"]
        try:
            if await self._is_logged_in(page):
                return await self._finalize_login(login_session_id, entry)

            # "身份验证"选择页的判断必须放在二维码可见性检测之前: 抖音会把
            # 验证弹层盖在原二维码同一屏幕位置上，此时原二维码img元素在DOM
            # 层面可能仍报告"可见"(只是被盖住了)，如果先查二维码可见性会
            # 一直误判成"还在等扫码"，实际把验证弹层的内容截图当二维码发给
            # 前端(表现为前端二维码区域花屏)。所以先认身份验证页，认不出来
            # 才退回去看二维码是否还在。
            if await self._is_identity_verification_page(page):
                clicked = False
                if not entry.get("sms_requested"):
                    entry["sms_requested"] = True
                    clicked = await self._click_receive_sms_option(page)
                    if clicked:
                        await asyncio.sleep(1.5)
                hint = await self._extract_verification_hint(page)
                logger.info(
                    "poll_qr_login: identity verification required, clicked_sms=%s", clicked,
                )
                return self._status_dict(
                    "need_verification",
                    verify_message=hint or "抖音要求进行身份验证，已尝试发送短信验证码，请查看手机短信后在下方输入验证码",
                    verify_image_base64=await self._capture_full_page(page),
                )

            if await self._qr_still_visible(page):
                # 抖音页面的二维码通常会自动过期/刷新(生成新token)，如果一直
                # 展示登录之初截的那张静态图，用户扫的其实是早已失效的旧码，
                # 扫了也不会有任何反应。每次轮询都重新截一次图跟页面实时同步，
                # 保证用户看到的始终是当前真正有效、可扫的那张二维码。
                qr_base64 = await self._reshoot_qr(page)
                return self._status_dict("pending", qr_image_base64=qr_base64)

            # 二维码和身份验证页都检测不到，再看能否提取到脱敏手机号这种
            # 强信号，有就直接判定需要验证。
            hint = await self._extract_verification_hint(page)
            if hint:
                return self._status_dict(
                    "need_verification",
                    verify_message=hint,
                    verify_image_base64=await self._capture_full_page(page),
                )

            # 都没检测到时也不要立刻做"重新加载首页"这种破坏性操作——万一
            # 页面正处于扫码后跳转到身份验证页的过渡渲染中，强制刷新会把
            # 用户刚扫码确认的进度冲掉，变回一张全新未扫描的二维码，等于
            # 白扫。所以先等一下再复查一次身份验证页，确认真的没有才自愈。
            await asyncio.sleep(2.0)
            if await self._is_identity_verification_page(page):
                clicked = False
                if not entry.get("sms_requested"):
                    entry["sms_requested"] = True
                    clicked = await self._click_receive_sms_option(page)
                    if clicked:
                        await asyncio.sleep(1.5)
                hint = await self._extract_verification_hint(page)
                logger.info(
                    "poll_qr_login: identity verification required after settle, clicked_sms=%s", clicked,
                )
                return self._status_dict(
                    "need_verification",
                    verify_message=hint or "抖音要求进行身份验证，已尝试发送短信验证码，请查看手机短信后在下方输入验证码",
                    verify_image_base64=await self._capture_full_page(page),
                )

            try:
                await page.goto(self.HOME_URL, timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS)
                qr_element = page.locator(self._SEL_QR_IMAGE).first
                await qr_element.wait_for(timeout=8000)
                await page.wait_for_function(
                    """(el) => el.getAttribute('src') && el.getAttribute('src').length > 200""",
                    arg=await qr_element.element_handle(),
                    timeout=8000,
                )
                qr_base64 = await self._reshoot_qr(page)
                return self._status_dict("pending", qr_image_base64=qr_base64)
            except Exception as exc:
                logger.warning("poll_qr_login: 二维码消失后自愈重新加载失败: %s", exc)
                return self._status_dict(
                    "need_verification",
                    verify_message="抖音要求进行安全验证，请查看手机短信/APP提示后在下方输入验证码",
                    verify_image_base64=await self._capture_full_page(page),
                )
        except Exception as exc:
            logger.warning("poll_qr_login error: %s", exc)
            return self._status_dict("pending")

    async def submit_verification_code(self, login_session_id: str, code: str) -> dict:
        entry = self._qr_sessions.get(login_session_id)
        if entry is None:
            return self._status_dict("expired")

        if time.time() - entry["created_at"] > settings.PLAYWRIGHT_QR_LOGIN_TTL_SEC:
            await self._discard_qr_session(login_session_id)
            return self._status_dict("expired")

        page = entry["page"]
        try:
            input_el = await self._locate_verify_input(page)
            if input_el is None:
                logger.warning(
                    "submit_verification_code: 未定位到验证码输入框 session=%s", login_session_id,
                )
                return self._status_dict(
                    "need_verification",
                    verify_message="未能自动定位验证码输入框，请稍后重试或联系管理员核对页面结构",
                    verify_image_base64=await self._capture_full_page(page),
                )

            # 验证码输入框上方经常盖着一层用于过渡动画的透明容器(如
            # div#uc-second-verify)，元素本身可见但会拦截常规点击的坐标
            # 命中检测，导致Locator.click一直等到超时。用force跳过这层
            # 遮挡检测直接点。
            await input_el.click(force=True, timeout=10000)
            await input_el.fill("")
            for ch in code.strip():
                await input_el.type(ch, delay=random.uniform(60, 150))

            submit_el = await self._locate_verify_submit(page)
            if submit_el is not None:
                await submit_el.click(force=True, timeout=10000)
            else:
                await page.keyboard.press("Enter")

            # 提交后到抖音真正写入登录cookie/跳转之间有网络往返延迟，一次性
            # 等1.5秒判断太早容易把"还在处理中"误判成"验证失败"。改成多次
            # 轮询检测，累计等够5秒还没登录成功才真正判定失败。
            logged_in = False
            for _ in range(5):
                await asyncio.sleep(1.0)
                if await self._is_logged_in(page):
                    logged_in = True
                    break

            if logged_in:
                return await self._finalize_login(login_session_id, entry)

            hint = await self._extract_verification_hint(page)
            logger.info(
                "submit_verification_code: still need_verification after submit session=%s",
                login_session_id,
            )
            return self._status_dict(
                "need_verification",
                verify_message=hint or "验证码可能有误或已失效，请确认后重试",
                verify_image_base64=await self._capture_full_page(page),
            )
        except Exception as exc:
            logger.warning("submit_verification_code failed: %s", exc)
            return self._status_dict(
                "need_verification",
                verify_message=f"提交验证码时出错: {exc}",
                verify_image_base64=await self._capture_full_page(page),
            )

    async def _reshoot_qr(self, page) -> Optional[str]:
        """重新截取当前页面上的二维码图片，跟随抖音端的自动刷新保持同步。"""
        try:
            qr_element = page.locator(self._SEL_QR_IMAGE).first
            qr_bytes = await qr_element.screenshot(timeout=5000)
            return base64.b64encode(qr_bytes).decode("ascii")
        except Exception as exc:
            logger.warning("_reshoot_qr failed: %s", exc)
            return None

    async def _discard_qr_session(self, session_id: str) -> None:
        entry = self._qr_sessions.pop(session_id, None)
        if entry is None:
            return
        await self._safe_close(entry["page"])
        await self._safe_close(entry["context"])


# ── 模块级单例(按配置选择实现) ──────────────────────────────────────────────

_automation_instance: Optional[DouyinAutomation] = None


def get_automation() -> DouyinAutomation:
    global _automation_instance
    if _automation_instance is None:
        if settings.DOUYIN_AUTOMATION_MODE == "playwright":
            _automation_instance = PlaywrightDouyinAutomation()
            logger.info("DouyinAutomation: using PlaywrightDouyinAutomation (production)")
        else:
            _automation_instance = MockDouyinAutomation()
            logger.info("DouyinAutomation: using MockDouyinAutomation (mock)")
    return _automation_instance


automation = get_automation()


async def send_private_message_with_retry(
    cookie_data: str, target_uid: str, content: str, max_retries: int = 3,
    account_id: int | None = None, proxy_url: str = "",
) -> Tuple[bool, str]:
    """带重试的私信发送，最多重试max_retries次，重试间隔随机打散。"""
    last_error = ""
    for attempt in range(max_retries):
        if attempt > 0:
            await asyncio.sleep(random.uniform(1.5, 3.0))
        ok, err = await automation.send_private_message(
            cookie_data, target_uid, content, account_id=account_id, proxy_url=proxy_url,
        )
        if ok:
            return True, ""
        last_error = err or "发送失败"
        logger.warning(
            "send_private_message_with_retry: attempt %d/%d failed target=%s error=%s",
            attempt + 1, max_retries, target_uid, last_error,
        )
    return False, last_error
