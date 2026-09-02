"""
高级行为模拟器
==============

【核心思想】让自动化的操作节奏无限接近真人。滚动的快慢节奏、打字的犹豫
和错字、鼠标的抖动与曲线，都是真人天然存在、脚本天然缺失的特征。

【抖音检测什么？】（反作弊不只看指纹，还分析"行为流"）
1. 滚动：真人有"快-慢-停-看-继续"的节奏；脚本匀速滚动，deltaY序列方差≈0
2. 打字：真人间隔不均、会犹豫、会打错再删；脚本每字间隔完全一样（一眼假）
3. 鼠标：真人的手会抖、轨迹是光滑曲线；脚本直线移动甚至瞬移
4. 节奏：真人打开页面会先浏览几秒再操作；脚本一加载完就点按钮

【用法】所有方法均为 asyncio 风格，传入 Playwright 的 Page：
    sim = BehaviorSimulator(page)
    await sim.bezier_mouse_move(x, y)     # 鼠标沿贝塞尔曲线移动过去
    await sim.human_like_type("你好")     # 像真人一样打字
"""

import asyncio
import math
import random

from playwright.async_api import Page


class BehaviorSimulator:
    """高级行为模拟器：滚动 / 打字 / 鼠标 / 操作前浏览，全部真人化"""

    def __init__(self, page: Page):
        self.page = page
        # 记录鼠标逻辑位置（作为贝塞尔移动的起点，保证轨迹连续）
        self._mouse_x, self._mouse_y = 400.0, 300.0

    # ================================================================
    # 1. 真人滚动
    # ================================================================
    async def human_like_scroll(self, distance: int = 500, direction: str = "down"):
        """
        真人滚动：快 → 慢 → 停 → 看 → 继续。

        【抖音检测什么】scroll 事件的 deltaY 序列和时间间隔序列。
        脚本滚动的每次位移量、间隔都一样 → 方差趋近于0 → 一眼假。

        【为什么这样模拟】真人滚轮是物理动作：起步加速、疲劳减速、
        中途停下来看内容（停顿 0.3~1.5 秒）、看完继续往下划。
        这里用正弦曲线做"加速-匀速-减速"，并随机插入"停下来看"。
        """
        sign = 1 if direction == "down" else -1
        steps = max(5, min(20, distance // 30))  # 步数随距离增加（真人不会一步滚很远）
        for i in range(steps):
            # 正弦加减速：progress 从 0→1，中间快两端慢（滚轮物理节奏）
            progress = (i + 1) / steps
            weight = math.sin(progress * math.pi) + 0.3
            amount = max(1, int(distance * weight / steps))
            await self.page.mouse.wheel(0, sign * amount)

            if random.random() < 0.15:
                # 15% 概率"停下来看"0.3~1.5 秒（真人看到感兴趣的内容）
                await asyncio.sleep(random.uniform(0.3, 1.5))
            else:
                # 步间隔带随机抖动，避免等差数列特征
                await asyncio.sleep(random.uniform(0.03, 0.12))

    # ================================================================
    # 2. 真人打字
    # ================================================================
    async def human_like_type(self, text: str, selector: str = None):
        """
        真人打字：间隔不匀速 + 10% 概率犹豫长停 + 5% 概率打错再删。

        【抖音检测什么】keydown 事件的时间间隔分布。
        type(text, delay=100) 这种写法的间隔是常数 100ms → 方差为0 → 一眼假。
        真人的击键间隔是随机分布，标点后停顿更久，偶尔卡壳想词。
        """
        if selector:
            await self.page.click(selector)
            await asyncio.sleep(random.uniform(0.2, 0.5))  # 点击后"准备"打字

        for ch in text:
            # 5% 概率：打错一个字 → 犹豫 → 删除 → 重打（真人肌肉记忆失误）
            if random.random() < 0.05:
                await self.page.keyboard.type(random.choice("的一是不了人在有这中大"))
                await asyncio.sleep(random.uniform(0.15, 0.4))  # 意识到打错了
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.1, 0.25))

            await self.page.keyboard.type(ch, delay=0)

            # 基础间隔 50~180ms 随机（真人击键间隔本身就是随机分布）
            delay = random.uniform(0.05, 0.18)
            # 标点后停更久（正在组织下一句话）
            if ch in "，。！？；：、":
                delay += random.uniform(0.2, 0.6)
            # 10% 概率长停顿：在想措辞 / 分心（真人高频行为）
            if random.random() < 0.10:
                delay += random.uniform(0.3, 1.0)
            await asyncio.sleep(delay)

    # ================================================================
    # 3. 操作前浏览
    # ================================================================
    async def pre_action_browse(self, duration: float = None):
        """
        操作前先"随便看看"再动手（发消息/点赞/关注之前调用）。

        【抖音检测什么】DOMContentLoaded → 首次操作的时间间隔。
        真人打开页面会先浏览 2~6 秒再操作；脚本毫秒级就点击 → 一眼假。
        【模拟内容】随机滚动几屏 + 鼠标微动，持续约 2~6 秒。
        """
        duration = duration or random.uniform(2, 6)
        # 随机滚 1~3 屏，每屏之间停顿（看内容）
        for _ in range(random.randint(1, 3)):
            await self.human_like_scroll(random.randint(100, 400))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        # 剩余时间做鼠标微动（人在看内容时手不会完全静止）
        for _ in range(2):
            await self.random_micro_movement()
            await asyncio.sleep(random.uniform(0.5, 1.5))

    # ================================================================
    # 4. 鼠标微小抖动
    # ================================================================
    async def random_micro_movement(self, radius: int = 20):
        """
        鼠标微小抖动：模拟真人的手无法完全静止。

        【抖音检测什么】mousemove 序列的"静止时长"。
        连续几秒零移动 = 要么没人、要么脚本；真人手一直有微幅漂移。
        【幅度】每次在 20px 半径内漂移，分多小步走过去（不是瞬移）。
        """
        for _ in range(random.randint(3, 6)):
            dx = random.uniform(-radius, radius)
            dy = random.uniform(-radius, radius)
            await self.page.mouse.move(self._mouse_x + dx, self._mouse_y + dy, steps=2)
            self._mouse_x += dx
            self._mouse_y += dy
            await asyncio.sleep(random.uniform(0.05, 0.2))

    # ================================================================
    # 5. 贝塞尔曲线鼠标移动
    # ================================================================
    async def bezier_mouse_move(self, target_x: float, target_y: float):
        """
        贝塞尔曲线鼠标移动（带随机控制点）。

        【抖音检测什么】鼠标轨迹的几何特征。
        脚本 mouse.move() 是直线（甚至瞬移）；真人手腕转动出来的轨迹
        是光滑曲线，而且每次的弯曲程度都不同。

        【原理】三阶贝塞尔曲线 P0(起点) + P1、P2(随机控制点) + P3(终点)：
        控制点在垂直于起终点连线的方向随机偏移 → 每次轨迹独一无二，
        但都是自然的弧线（不是抖动的折线）。
        """
        x0, y0 = self._mouse_x, self._mouse_y
        mid_x, mid_y = (x0 + target_x) / 2, (y0 + target_y) / 2
        # 两个控制点随机偏移 → 弧度随机
        offset = random.uniform(-150, 150)
        c1x = x0 + (mid_x - x0) * 0.5 + offset
        c1y = y0 + (mid_y - y0) * 0.5 + random.uniform(-80, 80)
        c2x = mid_x + offset * 0.5
        c2y = mid_y + random.uniform(-80, 80)

        # 步数随距离增加（远距离分更多步，移动更慢更自然）
        steps = max(15, int(math.hypot(target_x - x0, target_y - y0) / 25))
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            # 三阶贝塞尔公式：B(t) = (1-t)³P0 + 3(1-t)²t·P1 + 3(1-t)t²·P2 + t³P3
            x = u**3 * x0 + 3 * u**2 * t * c1x + 3 * u * t**2 * c2x + t**3 * target_x
            y = u**3 * y0 + 3 * u**2 * t * c1y + 3 * u * t**2 * c2y + t**3 * target_y
            await self.page.mouse.move(x, y)
            # 步间微小随机间隔（完全等间隔也是机器人特征）
            await asyncio.sleep(random.uniform(0.005, 0.02))
        # 更新鼠标逻辑位置，作为下一次移动的起点
        self._mouse_x, self._mouse_y = float(target_x), float(target_y)
