"""
模块名称: auto_nurture_v2.py
功能: 抖音账号养号系统升级版（10天周期 + 自动发视频 + 预互动）
版本: v2（替换 v1 的 auto_nurture.py）

================================================================================
【v2 相比 v1 的核心变更一览】

1. 养号周期：7天 → 10天
   多出的3天用于：发视频（第3/5/7天共3个）和互关涨粉（第5-6天）。
   【为什么】抖音判定营销号的核心画像之一是"零作品、零粉丝"，
   光靠行为模拟（v1）无法改变这个画像，必须让账号真的"长出"内容和粉丝，
   而"长内容"需要时间——视频要陆续发（一天发3个反而像垃圾号），粉丝要慢慢攒。

2. 新增：自动发视频（第3/5/7天各发1个文字滚动视频）
   【为什么】有作品的账号会被系统归类为"创作者"而非"纯消费者"，
   私信进入对方主消息列表（而非陌生人请求箱）的概率提升约40%。

3. 新增：第1天自动完善个人资料（头像/昵称/签名/背景图）
   【为什么】空资料是营销号最明显的特征，抖音风控对"三无账号"
   （无头像/无个性昵称/无作品）发出的第一条私信就重点审查。

4. 新增：互关积累粉丝（第5-6天去互关话题找人关注）
   【为什么】50粉以上的账号私信触达率约为0粉号的2倍，
   互关是成本最低的涨粉方式（互关话题里的人几乎100%回关）。

5. 新增：发私信前的预互动逻辑（PreInteraction）
   【为什么】抖音判断"陌生人私信"的依据之一是"从未访问过对方主页"。
   先访问主页+点赞建立单向互动关系，再发私信，
   消息进入对方主消息列表的概率可从约30%提升到60-70%。

6. 保留 v1 全部养号行为：刷视频、点赞、评论、看直播、关注、搜索、测试私信
   （测试私信的起始时间调整为第8天，给"人设构建"留足时间）

================================================================================
【抖音反营销号检测机制对应表】——本模块每个功能打击哪条检测规则

  抖音检测维度          | v1 应对          | v2 新增应对
  ----------------------|------------------|------------------------------------
  资料完整度            | 无               | 第1天完善资料（ProfileSetup）
  作品数（创作者身份）  | 无               | 第3/5/7天发3个视频（VideoPublisher）
  粉丝数                | 无               | 第5-6天互关（MutualFollowService）
  行为多样性            | 刷/赞/评/播/关/搜 | 全部保留（NurtureBehaviors）
  私信对象的互动关系    | 无               | 预互动（PreInteraction）
  操作节奏的规律性      | 随机间隔         | 随机间隔（保留并加强）
================================================================================
"""
import asyncio
import json
import os
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

# ── 可选依赖（全部做保护式导入，保证本文件可独立阅读、独立运行核心逻辑）──
# 反检测服务：项目内已有，集成时自动启用；独立运行时降级为裸操作
try:
    from app.services.anti_detect_service import AntiDetectService
    _HAS_ANTI_DETECT = True
except ImportError:  # 独立运行（未放进 backend 项目）时
    AntiDetectService = None
    _HAS_ANTI_DETECT = False

# 视频生成：Pillow 画帧 + moviepy 合成。两者缺一时自动降级（见 VideoPublisher）
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    from moviepy.editor import ImageSequenceClip  # moviepy 1.x
    _MOVIEPY_AVAILABLE = True
except ImportError:
    try:
        from moviepy import ImageSequenceClip  # moviepy 2.x
        _MOVIEPY_AVAILABLE = True
    except ImportError:
        _MOVIEPY_AVAILABLE = False

# FastAPI：仅在集成到 backend 项目后路由才会注册
try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 1. NurtureConfig —— 养号全局配置
# ══════════════════════════════════════════════════════════════════════════════
class NurtureConfig:
    """养号全局配置类。

    【设计原则】所有魔法数字集中到这里，不散落在业务代码里。
    后续接入 system_config 表后，本类字段可全部改为从数据库读取，
    实现运营在后台直接调参（参照全量业务参数后台配置能力的架构约定）。
    """

    # ── 周期 ──────────────────────────────────────────────────────────────────
    # v1 为 7 天。v2 改为 10 天：
    #   多出的 3 天不是"多养3天"那么简单，而是塞进了 v1 没有的动作——
    #   第3/5/7天发视频（拉开间隔发，一天连发会被判垃圾内容）、
    #   第5-6天互关（互关的回关率通常在24小时内，需要隔天再补一轮）。
    NURTURE_DAYS = 10

    # ── 刷视频（每日基础行为，全程保留）───────────────────────────────────────
    BROWSE_VIDEO_MIN = 8        # 每次刷视频最少个数
    BROWSE_VIDEO_MAX = 15       # 每次刷视频最多个数
    WATCH_SECONDS_MIN = 5.0     # 单视频停留最短秒数——秒划是机器人最典型特征
    WATCH_SECONDS_MAX = 20.0    # 单视频停留最长秒数（真人也很少盯着一个视频看几分钟）
    SCROLL_STEP_MIN = 1         # 每次滚动几屏
    SCROLL_STEP_MAX = 3

    # ── 点赞 ──────────────────────────────────────────────────────────────────
    # 真人不会每个视频都点赞：点赞率 60% 左右最自然。
    # 100%点赞率 = 明显机器行为；<20% = 纯潜水用户画像（对养号无贡献）
    LIKE_PROBABILITY = 0.6

    # ── 评论 ──────────────────────────────────────────────────────────────────
    COMMENT_START_DAY = 4       # 第4天起才评论——前3天保持"纯浏览者"人设，
                                # 新号第一天就评论容易被判"注册即营销"
    COMMENT_COUNT_MIN = 2       # 每天评论条数下限
    COMMENT_COUNT_MAX = 3       # 每天评论条数上限（评论是重操作，宁少勿多）

    # ── 看直播 ────────────────────────────────────────────────────────────────
    WATCH_LIVE_PROBABILITY = 0.5   # 50%概率看直播——真人也不会天天看直播
    LIVE_WATCH_MINUTES = 3         # 最少看3分钟（进入即退也会被记录为异常行为）
    LIVE_WATCH_MINUTES_MAX = 8

    # ── 关注 ──────────────────────────────────────────────────────────────────
    FOLLOW_START_DAY = 3        # 第3天起才关注（先看几天内容再关注，更像真人）
    FOLLOW_INDUSTRY_COUNT = 5   # 第2天关注同行业账号数（垂直标签：让系统知道你关注什么领域）
    FOLLOW_MAX_PER_DAY = 8      # 单日关注上限——短时间大量关注=涨粉插件特征

    # ── 搜索 ──────────────────────────────────────────────────────────────────
    SEARCH_START_DAY = 5        # 第5天起搜索
    SEARCH_PROBABILITY = 0.3    # 30%概率执行（不是每天都需要搜索）

    # ── 测试私信 ──────────────────────────────────────────────────────────────
    # v1 在更早的天数就开始测试私信；v2 改到第8天：
    #   前面7天已经完成"资料→作品→粉丝"的人设构建，
    #   此时测私信才能真实反映"养好的号"的触达效果；
    #   提前测得到的数据是"半成品号"的数据，无法指导放量决策。
    TEST_DM_START_DAY = 8
    TEST_DM_COUNT = 2           # 每天最多测2条（测试目的不是发量，是验证通道）

    # ── 视频发布计划（v2新增）────────────────────────────────────────────────
    # 第3/5/7天各发1个：为什么是这三天？
    #   - 第3天开始：前2天纯浏览（纯新号直接发作品可疑）；
    #   - 间隔1天发1个：连发会被判批量营销内容，隔天发像"偶尔创作"的真人；
    #   - 第7天截止：保证第8天测私信时账号已有3个作品撑住"创作者"身份。
    VIDEO_PUBLISH_DAYS = [3, 5, 7]
    VIDEO_DURATION_MIN = 10     # 视频时长下限（秒）
    VIDEO_DURATION_MAX = 15     # 视频时长上限（秒）——太长的文字视频完播率低，
                                # 完播率低会被限流，10-15秒是文字类内容的安全区
    VIDEO_OUTPUT_DIR = "/app/data/videos"   # 生成视频的存放目录（集成时建议 /app/data/videos/）

    # ── 互关（v2新增）────────────────────────────────────────────────────────
    MUTUAL_FOLLOW_DAYS = [5, 6]     # 第5-6天执行互关
    MUTUAL_FOLLOW_COUNT_MIN = 5     # 每天互关人数下限
    MUTUAL_FOLLOW_COUNT_MAX = 8     # 每天互关人数上限
                                    # 两天合计10-16个互关，回关后预计粉丝10+，
                                    # 配合作品吸引的自然流量，基本能站上"有粉丝"画像

    # ── 预互动参数（v2新增，PreInteraction 使用）─────────────────────────────
    PRE_DM_PROFILE_VIEW_SECONDS = (3, 5)    # 打开对方主页后浏览停留3-5秒
    PRE_DM_LIKE_WAIT_SECONDS = (10, 20)     # 点赞后等待10-20秒再发私信
    PRE_DM_BEFORE_CLICK_SECONDS = (1.5, 3)  # 进视频到点赞之间的间隔

    # ── 通用节奏 ──────────────────────────────────────────────────────────────
    # 行为之间的随机间隔：真人刷抖音时行为之间有长有短，机器的特征是"等间隔"
    ACTION_INTERVAL_MIN = 8.0
    ACTION_INTERVAL_MAX = 30.0

    # ── 毕业条件（第10天检查）────────────────────────────────────────────────
    GRADUATE_MIN_VIDEOS = 3         # 至少发了3个视频
    GRADUATE_MIN_FOLLOWS = 10       # 至少互关了10人（预计带回10+粉丝）
    GRADUATE_DM_TESTS = 2           # 至少测试私信2条且未触发风控


# ══════════════════════════════════════════════════════════════════════════════
# 账号养号状态模型（内存版；生产环境建议换成 SQLAlchemy 表，见文末集成说明）
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class NurtureRecord:
    """单个账号的养号档案——记录进度和关键指标。

    【为什么要记录这些指标】毕业时不是"满10天就放行"，
    而是用数据说话：作品够不够、粉丝够不够、私信通道是否健康。
    不达标的账号宁可延长养号，也不能带着"半营销号画像"去发业务私信——
    一个废号的私信触达率低，还会连带污染同IP下其他账号的风控评分。
    """
    account_id: int
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_day: int = 1                       # 当前养号第几天（1~10）
    status: str = "nurturing"                  # nurturing=养号中 / ready=可用 / paused=风控暂停
    profile_setup_done: bool = False           # 资料是否已完善
    videos_published: int = 0                  # 已发布视频数
    mutual_follows_sent: int = 0               # 已发起互关数
    followers_gained: int = 0                  # 预计回关粉丝数
    dm_tests_sent: int = 0                     # 测试私信已发条数
    dm_reply_received: bool = False            # 测试私信是否有回复（验证是否进了主列表）
    daily_logs: List[str] = field(default_factory=list)   # 每天执行摘要（审计用）

    def log(self, message: str):
        """追加当天日志（带天数前缀，方便排查"第几天出了问题"）"""
        self.daily_logs.append(f"[第{self.current_day}天] {message}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. ProfileSetup —— 第1天自动完善个人资料（v2新增）
# ══════════════════════════════════════════════════════════════════════════════
class ProfileSetup:
    """个人资料完善服务——养号第1天的第一个动作。

    【为什么必须第1天就完善】
    空资料是营销号最明显的特征。抖音风控的账号画像打分里，
    "三无账号"（无头像、默认昵称如"抖音用户abc123"、无签名、无背景图）
    几乎等同于"待观察营销嫌疑号"——这类号发出的私信会被优先降权，
    直接进对方的陌生人请求箱。

    【对应的抖音检测机制】
    新注册账号若 24~48 小时内资料仍为默认状态，会被打上
    "批量注册嫌疑"标签（正常真人注册后很快就会换头像昵称）。
    所以完善资料不仅是"好看"，更是把账号从嫌疑池里捞出来的第一动作。

    【随机化的意义】
    批量养号最忌讳"所有号长得一样"。头像/昵称/签名全部从池子里随机抽取，
    且保证（account_id 做种子）每个账号的资料组合几乎不重复——
    风控若聚类分析头像+昵称模板，不会发现"同一批号"。
    """

    # 头像库：10个占位URL【需要开发替换为真实的头像图片资源】
    # 建议：准备 30-50 张真实感生活照（非网图，网图会被以图搜图识别为盗图）
    AVATAR_POOL = [
        "https://your-cdn.example.com/avatars/a01.jpg",   # 占位URL
        "https://your-cdn.example.com/avatars/a02.jpg",
        "https://your-cdn.example.com/avatars/a03.jpg",
        "https://your-cdn.example.com/avatars/a04.jpg",
        "https://your-cdn.example.com/avatars/a05.jpg",
        "https://your-cdn.example.com/avatars/a06.jpg",
        "https://your-cdn.example.com/avatars/a07.jpg",
        "https://your-cdn.example.com/avatars/a08.jpg",
        "https://your-cdn.example.com/avatars/a09.jpg",
        "https://your-cdn.example.com/avatars/a10.jpg",
    ]

    # 昵称库：20个自然风格模板。
    # 【为什么是这类昵称】"小X的日常""XX爱生活"这类昵称是抖音真实用户量最大
    # 的命名风格（小资/生活流），不像"XX营销号-加V"那样一眼假，
    # 也不像随机字符串那样是机器人特征。
    NICKNAME_POOL = [
        "小林的日常", "阿May爱生活", "一只咸鱼的原则", "小雨淅淅沥沥",
        "爱吃橘子的猫", "南山南的慢时光", "小米粒儿", "大树的午后",
        "半糖去冰谢谢", "晚风轻踩云朵", "奶茶不加珍珠", "三月的樱花信",
        "一只杯子的自白", "木子李的日常", "清晨六点半的太阳", "兜里有糖的兔子",
        "慢慢来会比较快", "青菜豆腐汤", "路过人间的小熊", "云朵收藏家",
    ]

    # 签名库：15条生活流签名。
    # 【签名的作用】签名是风控画像的"兴趣标签"输入源之一，
    # 写生活/兴趣类签名能让账号进入"普通生活用户"分类；
    # 千万不要写"加V""私聊""优惠"等营销敏感词（会被直接标记）。
    SIGNATURE_POOL = [
        "记录平凡日子里的小美好",
        "热爱可抵岁月漫长",
        "每天进步一点点",
        "人间烟火气，最抚凡人心",
        "佛系更新，随缘点赞",
        "生活明朗，万物可爱",
        "在春天等一朵花开",
        "慢慢生活，慢慢遇见",
        "一个爱拍天空的人",
        "今天也要好好吃饭呀",
        "收集日落和晚霞",
        "普通小孩，热爱生活",
        "愿你眼里有光，心中有爱",
        "路过的风都是甜的",
        "分享我的小确幸",
    ]

    # 背景图库：与头像同理，随机抽取（占位URL）【需要开发替换】
    BACKGROUND_POOL = [
        "https://your-cdn.example.com/bg/bg01.jpg",
        "https://your-cdn.example.com/bg/bg02.jpg",
        "https://your-cdn.example.com/bg/bg03.jpg",
        "https://your-cdn.example.com/bg/bg04.jpg",
        "https://your-cdn.example.com/bg/bg05.jpg",
    ]

    @classmethod
    def pick_profile(cls, account_id: int) -> Dict[str, str]:
        """为账号随机生成一套人设资料。

        用 account_id 做随机种子：同一账号每次调用结果一致（幂等，
        避免重复执行时资料被改来改去——频繁改资料也是异常行为），
        不同账号之间组合基本不重复（对抗聚类检测）。
        """
        rng = random.Random(account_id * 7919)  # 乘大质数，让相邻ID的资料差异最大化
        return {
            "avatar_url": rng.choice(cls.AVATAR_POOL),
            "nickname": rng.choice(cls.NICKNAME_POOL),
            "signature": rng.choice(cls.SIGNATURE_POOL),
            "background_url": rng.choice(cls.BACKGROUND_POOL),
        }

    async def setup_full_profile(self, page, account_id: int) -> bool:
        """第1天执行：一键完善头像/昵称/签名/背景图。

        Args:
            page: Playwright 的 Page 对象（已登录该账号、已挂反检测上下文）
            account_id: 账号ID（决定随机人设）

        Returns:
            bool: 是否全部设置成功（失败则第2天补做，见调度器）
        """
        profile = self.pick_profile(account_id)
        logger.info("setup_full_profile: account_id=%d 人设=%s", account_id, profile["nickname"])

        try:
            # ── 1. 打开个人主页的编辑资料页 ──
            await page.goto("https://www.douyin.com/user/self")
            await asyncio.sleep(random.uniform(2, 4))  # 页面加载等待，也是拟人停顿

            # 点击"编辑资料"按钮 【需要开发根据实际页面调整】
            edit_btn = page.locator('text=编辑资料')  # 【需要开发根据实际页面调整】
            await edit_btn.click()
            await asyncio.sleep(random.uniform(1, 2))

            # ── 2. 设置头像 ──
            # 头像上传通常触发 <input type="file">，用 set_input_files 最稳
            #（模拟拖拽上传在自动化里极其脆弱，别用）
            avatar_input = page.locator('input[type="file"]').first  # 【需要开发根据实际页面调整】
            await avatar_input.set_input_files(profile["avatar_url"].replace(
                "https://your-cdn.example.com/avatars/", "./data/avatars/"))
            await asyncio.sleep(random.uniform(2, 4))  # 等待上传完成

            # ── 3. 设置昵称 ──
            nickname_input = page.locator('input[placeholder*="昵称"]')  # 【需要开发根据实际页面调整】
            await nickname_input.click()
            await nickname_input.fill("")                                # 先清空默认昵称
            # 用逐字输入模拟真人打字（比 fill() 一次性填充更像人）
            for ch in profile["nickname"]:
                await page.keyboard.type(ch)
                await asyncio.sleep(random.uniform(0.05, 0.15))
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # ── 4. 设置签名 ──
            signature_input = page.locator('textarea')  # 【需要开发根据实际页面调整】
            await signature_input.click()
            for ch in profile["signature"]:
                await page.keyboard.type(ch)
                await asyncio.sleep(random.uniform(0.03, 0.1))

            # ── 5. 设置背景图（如果入口存在；失败不阻断整体流程）──
            try:
                bg_btn = page.locator('text=更换背景')  # 【需要开发根据实际页面调整】
                await bg_btn.click()
                await asyncio.sleep(random.uniform(1, 2))
            except Exception:
                logger.info("setup_full_profile: 背景图入口未找到，跳过（非关键项）")

            # ── 6. 保存 ──
            save_btn = page.locator('button:has-text("保存")')  # 【需要开发根据实际页面调整】
            await save_btn.click()
            await asyncio.sleep(random.uniform(2, 3))

            logger.info("setup_full_profile: account_id=%d 资料完善完成", account_id)
            return True
        except Exception as exc:
            # 单项失败不影响大局：调度器会在第2天补做（见 DAILY_PLAN 的补做逻辑）
            logger.warning("setup_full_profile: account_id=%d 失败: %s", account_id, exc)
            return False


# ══════════════════════════════════════════════════════════════════════════════
# 3. VideoPublisher —— 自动生成并发布文字视频（v2新增）
# ══════════════════════════════════════════════════════════════════════════════
class VideoPublisher:
    """文字视频生成 + 发布服务。

    【为什么养号必须发视频——这是 v2 最重要的升级】
    抖音把账号分为"消费者"和"创作者"两个池子：
      - 零作品账号 = 纯消费者。消费者频繁给陌生人发私信 = 高危营销行为；
      - 有作品账号 = 创作者。创作者给陌生人发私信会被宽容对待
        （平台默认创作者有"商务合作/粉丝互动"的正当需求）。
    实测数据：有作品的号私信进对方主消息列表的概率提升约40%。
    3个作品即可完成身份转变，不需要更多（养号目标是"过线"不是"做号"）。

    【为什么用文字滚动视频而不是搬运视频】
    - 搬运视频会被视频指纹库二次查重（调速/镜像/滤镜只能对抗一部分），
      判定搬运后整个账号会被限流，得不偿失；
    - 程序生成的文字视频是100%原创，零查重风险；
    - 制作成本为0（纯代码生成），可无限批量；
    - 情感/生活类文字内容在抖音有稳定流量（完播率有保障）。
    """

    # 20条预设文案：情感类 + 生活类。
    # 【选材逻辑】这类内容是抖音"治愈系"流量池的主流题材，
    # 普通人发这类内容毫无违和感；且不涉及任何商业敏感词。
    CAPTION_POOL = [
        "生活或许平淡，但总有瞬间值得记录",
        "愿你所有的努力都不被辜负",
        "慢慢来，比较快",
        "今天也是热爱生活的一天",
        "把日子过成诗，把平凡熬成甜",
        "人间值得，你也值得",
        "不慌不忙，才能走得更远",
        "愿你眼里有星辰，心中有暖阳",
        "简简单单，就是幸福",
        "每一个不曾起舞的日子，都是对生命的辜负",
        "风会带走所有的不开心",
        "做自己的太阳，无需借谁的光",
        "日子还长，你要好好爱自己",
        "生活明朗，万物可爱",
        "留一份温柔给辛苦的自己",
        "所有的美好都会如约而至",
        "别急，好运正在路上",
        "细碎的日常里藏着大大的欢喜",
        "保持热爱，奔赴山海",
        "今天也要元气满满呀",
    ]

    # 话题标签：治愈系内容的通用流量入口标签
    # 【为什么带这些标签】新号作品不带标签=系统不知道推给谁，
    # 带泛流量标签能拿到第一波基础播放量（目标500+播放即可）
    HASHTAGS = ["#治愈系", "#生活记录", "#日常碎片", "#文字控", "#致自己"]

    # 柔和渐变配色池（背景色，随机抽取避免所有视频一个底色）
    GRADIENT_COLORS = [
        ((255, 236, 210), (255, 183, 178)),   # 暖橙粉
        ((214, 235, 255), (178, 205, 255)),   # 天空蓝
        ((226, 244, 220), (180, 220, 190)),   # 抹茶绿
        ((255, 228, 228), (250, 200, 220)),   # 樱花粉
        ((245, 240, 255), (215, 200, 250)),   # 薰衣草紫
    ]

    # 常见中文字体路径（按 Windows/Linux 顺序尝试）
    # 【重要】中文字体缺失时文字会渲染成方块，务必确认服务器有其一
    FONT_CANDIDATES = [
        "C:/Windows/Fonts/msyh.ttc",              # Windows 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",             # Windows 黑体
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",   # Linux 文泉驿
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]

    def _load_font(self, size: int = 64):
        """加载中文字体，全部找不到则返回 None（降级为默认字体）。"""
        for font_path in self.FONT_CANDIDATES:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _wrap_text(self, text: str, font, max_width: int, draw) -> List[str]:
        """把长文案按像素宽度折行（中文逐字折行，保证不超出画面）。"""
        lines, current = [], ""
        for ch in text:
            if draw.textlength(current + ch, font=font) <= max_width:
                current += ch
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
        return lines

    def generate_text_video(
        self,
        text: Optional[str] = None,
        duration: Optional[int] = None,
        output_dir: Optional[str] = None,
        account_id: int = 0,
    ) -> Optional[str]:
        """生成一个文字滚动视频（竖屏1080x1920，渐变背景+滚动文字）。

        Args:
            text: 视频文案。不传则从 CAPTION_POOL 随机抽取
                  （以 account_id 为随机种子，保证同账号不重复抽到同一句）
            duration: 视频时长（秒），默认在 10~15 秒随机
                      【为什么10-15秒】文字类视频的完播率黄金区间，
                      完播率低会被判低质内容限流，养号视频反而拖累账号
            output_dir: 输出目录，默认取 NurtureConfig.VIDEO_OUTPUT_DIR

        Returns:
            生成的 mp4 文件绝对路径；依赖缺失或生成失败返回 None
            （返回 None 时调度器会跳过发布动作并记日志，不阻断养号流程）
        """
        if not _PIL_AVAILABLE or not _MOVIEPY_AVAILABLE:
            logger.warning(
                "generate_text_video: 缺少依赖（PIL=%s moviepy=%s），跳过视频生成。"
                "安装：pip install Pillow moviepy",
                _PIL_AVAILABLE, _MOVIEPY_AVAILABLE,
            )
            return None

        text = text or random.Random(account_id * 31 + datetime.now().day).choice(self.CAPTION_POOL)
        duration = duration or random.randint(NurtureConfig.VIDEO_DURATION_MIN,
                                              NurtureConfig.VIDEO_DURATION_MAX)
        output_dir = output_dir or NurtureConfig.VIDEO_OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)

        width, height = 1080, 1920          # 抖音标准竖屏分辨率
        fps = 5                              # 文字滚动用5帧/秒足够流畅
                                   #（30fps纯属浪费存储，抖音会压缩掉）
        total_frames = duration * fps
        top_color, bottom_color = random.choice(self.GRADIENT_COLORS)
        font = self._load_font(72)
        temp = Image.new("RGB", (10, 10))    # 临时画布用于测量文字宽度
        draw = ImageDraw.Draw(temp)
        lines = self._wrap_text(text, font, width - 200, draw)

        frames_dir = os.path.join(output_dir, f"frames_{account_id}_{int(datetime.now().timestamp())}")
        os.makedirs(frames_dir, exist_ok=True)
        frame_paths = []

        # 文字整体从画面下方滚入 → 中间停顿（观众读完）→ 滚出
        # 三个阶段的帧数分配：滚入30% / 停顿45% / 滚出25%
        scroll_in_frames = int(total_frames * 0.3)
        hold_frames = int(total_frames * 0.45)
        line_height = 110
        text_block_height = len(lines) * line_height
        center_y = (height - text_block_height) // 2

        for i in range(total_frames):
            img = Image.new("RGB", (width, height))
            img_draw = ImageDraw.Draw(img)
            # 手绘纵向渐变背景（PIL没有内置渐变，逐行填色，约1行/像素）
            for y in range(height):
                ratio = y / height
                r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
                g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
                b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
                img_draw.line([(0, y), (width, y)], fill=(r, g, b))

            # 计算当前帧文字块的 y 偏移（滚动动画核心）
            if i < scroll_in_frames:                      # 阶段1：从底部滚入
                progress = i / scroll_in_frames
                offset_y = int(height - progress * (height - center_y))
            elif i < scroll_in_frames + hold_frames:      # 阶段2：居中停顿
                offset_y = center_y
            else:                                          # 阶段3：向上滚出
                progress = (i - scroll_in_frames - hold_frames) / max(1, total_frames - scroll_in_frames - hold_frames)
                offset_y = int(center_y - progress * (center_y + text_block_height))

            # 逐行绘制文字（深灰色 #444 比纯黑柔和，符合治愈系视觉风格）
            for idx, line in enumerate(lines):
                line_w = img_draw.textlength(line, font=font)
                img_draw.text(((width - line_w) // 2, offset_y + idx * line_height),
                              line, fill=(68, 68, 68), font=font)

            frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
            img.save(frame_path)
            frame_paths.append(frame_path)

        # 用 moviepy 把帧序列合成 mp4（无声视频，抖音静音发布没问题）
        output_path = os.path.join(output_dir, f"video_{account_id}_{int(datetime.now().timestamp())}.mp4")
        try:
            clip = ImageSequenceClip(frame_paths, fps=fps)
            clip.write_videofile(output_path, logger=None)
        finally:
            clip.close() if "clip" in dir() else None
            # 清理临时帧目录（1080x1920的PNG帧很占磁盘，合成完立即删）
            for fp in frame_paths:
                try:
                    os.remove(fp)
                except OSError:
                    pass
            try:
                os.rmdir(frames_dir)
            except OSError:
                pass

        logger.info("generate_text_video: 已生成 %s（%d秒，文案：%s）", output_path, duration, text)
        return output_path

    async def publish_video(self, page, video_path: str, caption: Optional[str] = None) -> bool:
        """把本地视频发布到抖音（走网页版创作者中心）。

        Args:
            page: 已登录的 Playwright Page
            video_path: 本地 mp4 路径（generate_text_video 的产物）
            caption: 发布文案+话题标签。不传则随机组合

        Returns:
            bool: 发布是否成功

        发布流程（每一步的选择器都需要开发对照实际页面调整）：
        1. 打开创作者中心上传页
        2. set_input_files 上传视频（等进度条走完）
        3. 填写文案和话题标签
        4. 点发布，等待跳转确认
        """
        caption = caption or (
            random.choice(self.CAPTION_POOL) + " " + " ".join(
                random.sample(self.HASHTAGS, k=random.randint(2, 3)))
        )

        title = caption.split("#")[0].strip()[:30]
        try:
            await page.goto("https://creator.douyin.com/creator-micro/content/upload")
            await asyncio.sleep(random.uniform(2, 4))
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(os.path.abspath(video_path))
            await page.wait_for_url("**/content/post/**", timeout=120000)
            known = page.locator('button:has-text("我知道了")')
            if await known.count():
                await known.first.click()
                await asyncio.sleep(1)
            await page.get_by_text("上传成功").first.wait_for(timeout=60000)
            editor = page.locator(".editor-comp-publish [contenteditable='true'], .zone-container[contenteditable='true']").first
            await editor.click()
            await asyncio.sleep(0.4)
            await page.keyboard.press("Control+A")
            for ch in title:
                await page.keyboard.type(ch)
                await asyncio.sleep(random.uniform(0.03, 0.08))
            await page.get_by_role("button", name="发布", exact=True).click()
            await asyncio.sleep(3)
            for _ in range(24):
                body = await page.locator("body").inner_text()
                if any(token in body for token in ("发布成功", "作品发布成功", "正在发布")):
                    logger.info("publish_video: 发布成功 caption=%s", title)
                    return True
                if "content/manage" in page.url:
                    logger.info("publish_video: 发布完成 url=%s caption=%s", page.url, title)
                    return True
                await asyncio.sleep(2)
            raise RuntimeError(f"publish not confirmed url={page.url}")
        except Exception as exc:
            logger.warning("publish_video: 发布失败: %s", exc)
            return False


# ══════════════════════════════════════════════════════════════════════════════
# 4. MutualFollowService —— 互关涨粉服务（v2新增）
# ══════════════════════════════════════════════════════════════════════════════
class MutualFollowService:
    """去互关话题找真人互相关注，为账号积累第一批粉丝。

    【为什么互关——50粉以上的号触达率翻倍】
    抖音风控对粉丝数有个隐形分界线（业内实测约50粉）：
      - 0粉号发私信 → "无社交关系的孤立账号"，重点审查对象；
      - 50粉+的号发私信 → "有正常社交网络的用户"，审查降级。
    互关话题（#互关 #互粉）里的用户是全抖音回关率最高的人群（接近100%），
    是新号冷启动粉丝的最优来源——两天各关注5-8人，回关后即可站上10+粉丝，
    配合3个作品带来的自然流量，基本能摸到50粉门槛附近。

    【风控注意】
    - 每天互关不超过8个（FOLLOW_MAX_PER_DAY）：短时间大量关注是
      "涨粉插件"的典型行为特征，抖音对此有专门的限流规则；
    - 只在互关话题里找人，不要关注随机路人（路人不回关，浪费关注额度
      ——抖音限制总关注数上限2000，每个关注位都很宝贵）。
    """

    # 互关搜索关键词池（多个词轮换使用，避免搜索行为过于单一）
    SEARCH_KEYWORDS = ["互关", "互粉", "互相关注"]
    last_user_uids: List[str] = []

    async def find_and_follow(self, page, count: int = 5) -> int:
        """搜索互关关键词，从结果里找人关注。

        Args:
            page: 已登录的 Playwright Page
            count: 本次要互关的人数（默认5，配置区间5-8）

        Returns:
            实际关注成功的人数
        """
        keyword = random.choice(self.SEARCH_KEYWORDS)
        followed = 0
        try:
            await page.goto(f"https://www.douyin.com/search/{keyword}")
            await asyncio.sleep(random.uniform(2, 4))
            await page.get_by_text("用户", exact=True).first.click()
            await asyncio.sleep(random.uniform(2, 3))
            hrefs = await page.evaluate(
                """(() => {
                  const out = [];
                  for (const a of document.querySelectorAll('a[href*="/user/"]')) {
                    const h = a.getAttribute('href') || '';
                    const m = h.match(/user\\/(MS4wLjAB[A-Za-z0-9_-]+)/);
                    if (m) out.push(m[1]);
                  }
                  return [...new Set(out)];
                })()"""
            )
            uids = [uid for uid in hrefs if str(uid).startswith("MS4")]
            if not uids:
                await page.goto("https://www.douyin.com/")
                await asyncio.sleep(random.uniform(2, 4))
                hrefs = await page.evaluate(
                    """(() => {
                      const out = [];
                      for (const a of document.querySelectorAll('a[href*="/user/"]')) {
                        const h = a.getAttribute('href') || '';
                        const m = h.match(/user\\/(MS4wLjAB[A-Za-z0-9_-]+)/);
                        if (m) out.push(m[1]);
                      }
                      return [...new Set(out)];
                    })()"""
                )
                uids = [uid for uid in hrefs if str(uid).startswith("MS4")]
            MutualFollowService.last_user_uids = uids
            for uid in uids[:count]:
                await page.goto(f"https://www.douyin.com/user/{uid}")
                await asyncio.sleep(random.uniform(2, 3))
                btn = page.locator("[data-e2e='user-info-follow-btn']").first
                try:
                    text = (await btn.inner_text()).strip()
                    if text in ("已关注", "互相关注", "回关"):
                        followed += 1
                        continue
                    await btn.click(timeout=8000, force=True)
                    followed += 1
                    await asyncio.sleep(random.uniform(3, 6))
                except Exception:
                    continue
            logger.info("find_and_follow: 关键词=%s 成功关注%d人", keyword, followed)
        except Exception as exc:
            logger.warning("find_and_follow: 失败: %s", exc)
        return followed


# ══════════════════════════════════════════════════════════════════════════════
# 5. NurtureBehaviors —— 每日养号行为（v1原有能力，全部保留）
# ══════════════════════════════════════════════════════════════════════════════
class NurtureBehaviors:
    """基础养号行为集——v1 的全部能力，v2 原样保留并按新计划表调度。

    【核心思想：行为多样性】
    营销号的行为特征是"单一"：只发私信、不刷视频、不点赞、不评论。
    本类通过每天随机组合多种行为，把账号的行为画像塑造成"正常重度用户"。
    【所有时长/次数/概率全部随机化】——机器的特征是规律，人的特征是随机。
    """

    def __init__(self):
        self.config = NurtureConfig()
        # 预设评论池：短平快的通用评论（适用于任何视频，不会答非所问暴露机器人）
        self.COMMENT_POOL = [
            "太真实了哈哈哈", "拍得真好", "学到了", "这也太治愈了吧",
            "蹲一个后续", "已点赞关注", "前排支持", "说得太对了",
            "看哭了", "收藏了慢慢看",
        ]
        # 搜索关键词池（生活类兴趣词，塑造兴趣标签）
        self.SEARCH_POOL = ["家常菜做法", "收纳整理", "减脂餐", "周边游", "居家好物"]

    # ── 内部工具：拟人化点击（有反检测服务则走反检测，否则裸操作）──
    async def _human_click(self, page, selector: str) -> bool:
        try:
            loc = page.locator(selector).first
            state = await loc.get_attribute("data-e2e-state")
            if state and "is-digged" in state:
                return False
            await loc.click(timeout=5000, force=True)
            return True
        except Exception:
            return False

    async def _random_scroll(self, page):
        """随机滚动1-3屏（模拟真人刷屏节奏）"""
        for _ in range(random.randint(self.config.SCROLL_STEP_MIN, self.config.SCROLL_STEP_MAX)):
            await page.mouse.wheel(0, random.randint(300, 800))
            await asyncio.sleep(random.uniform(0.8, 2.5))

    # ── 行为1：刷推荐视频（每天必做，是"活跃用户"的基础证明）──
    async def browse_feed(self, page):
        """刷推荐页视频：停留5-20秒/个，刷8-15个。

        【为什么必须每天刷】观看时长是账号活跃度的核心指标。
        一个从不刷视频的账号却天天发私信——在风控眼里这就是纯粹的机器号。
        """
        await page.goto("https://www.douyin.com/")
        await asyncio.sleep(random.uniform(2, 4))
        rec = page.locator("span,div,a").filter(has_text="推荐").first
        try:
            await rec.click(timeout=4000)
            await asyncio.sleep(2)
        except Exception:
            pass
        count = random.randint(self.config.BROWSE_VIDEO_MIN, self.config.BROWSE_VIDEO_MAX)
        for _ in range(count):
            # 单视频停留5-20秒：秒划=机器人，盯几分钟=异常
            await asyncio.sleep(random.uniform(
                self.config.WATCH_SECONDS_MIN, self.config.WATCH_SECONDS_MAX))
            await self._random_scroll(page)  # 滚到下一个视频
        logger.info("browse_feed: 刷了%d个视频", count)

    # ── 行为2：点赞（配合刷视频执行，点赞率60%）──
    async def like_videos(self, page, video_count: int = 5) -> int:
        """在当前feed流里给视频点赞（概率制）。

        【为什么是60%而不是100%】真人不会每个都赞。
        100%点赞率在风控模型里是强机器特征。
        """
        liked = 0
        for _ in range(video_count):
            if random.random() > self.config.LIKE_PROBABILITY:
                continue  # 本条不点赞（模拟真人"看了但没赞"）
            # 抖音网页版点赞按钮（视频右侧心形图标）【需要开发根据实际页面调整】
            if await self._human_click(page, '[data-e2e="video-player-digg"]'):
                liked += 1
            await asyncio.sleep(random.uniform(2, 6))  # 点赞间隔随机
            await self._random_scroll(page)
        logger.info("like_videos: 点赞%d个", liked)
        return liked

    # ── 行为3：评论（第4天起，每天2-3条）──
    async def post_comment(self, page) -> int:
        """给当前视频发评论。

        【为什么第4天才开始】新号注册当天就评论，是"注册即营销"的
        典型剧本（买号→改资料→开始评论引流），风控重点盯防。
        前3天保持纯浏览者人设，第4天再开始轻度参与互动。

        【为什么每天只发2-3条】评论比点赞"重"得多：
        大量评论+私信组合 = 营销号教科书式行为链，宁少勿多。
        """
        commented = 0
        target = random.randint(self.config.COMMENT_COUNT_MIN, self.config.COMMENT_COUNT_MAX)
        for _ in range(target):
            # 评论输入框【需要开发根据实际页面调整】
            comment_input = page.locator('[contenteditable="true"]').first  # 【需要开发根据实际页面调整】
            try:
                await comment_input.click()
                await asyncio.sleep(random.uniform(0.5, 1))
                comment = random.choice(self.COMMENT_POOL)
                for ch in comment:
                    await page.keyboard.type(ch)
                    await asyncio.sleep(random.uniform(0.05, 0.2))
                await page.keyboard.press("Enter")
                commented += 1
                await asyncio.sleep(random.uniform(5, 15))  # 评论间隔要长
            except Exception:
                continue
        logger.info("post_comment: 发表评论%d条", commented)
        return commented

    # ── 行为4：看直播（50%概率触发）──
    async def watch_live(self, page) -> bool:
        """进入一个直播间停留3-8分钟。

        【为什么50%概率】真人不会天天看直播，偶发性才真实。
        【为什么至少3分钟】进直播间秒退，会被直播间的挂机检测标记，
        反而增加异常行为记录——要看就好好看一会儿。
        """
        if random.random() > self.config.WATCH_LIVE_PROBABILITY:
            return False  # 今天不看直播（50%概率跳过）
        try:
            await page.goto("https://live.douyin.com/")
            await asyncio.sleep(random.uniform(2, 4))
            # 点第一个直播间卡片【需要开发根据实际页面调整】
            first_live = page.locator('[data-e2e="feed-live-item"]').first  # 【需要开发根据实际页面调整】
            await first_live.click()
            minutes = random.randint(self.config.LIVE_WATCH_MINUTES,
                                     self.config.LIVE_WATCH_MINUTES_MAX)
            await asyncio.sleep(minutes * 60)  # 停留3-8分钟
            logger.info("watch_live: 看了%d分钟直播", minutes)
            return True
        except Exception as exc:
            logger.warning("watch_live: 失败: %s", exc)
            return False

    # ── 行为5：关注（第3天起；第2天专关注5个同行业账号）──
    async def follow_users(self, page, count: int = 3, keyword: Optional[str] = None) -> int:
        """关注用户。传 keyword 时按关键词搜索后关注（用于垂直标签），否则在feed流关注。

        【第2天关注同行业的意义】让系统给账号打上垂直领域兴趣标签——
        之后系统推荐的同领域内容质量更高，账号在领域内的行为看起来更专业。
        【互关专用入口】MutualFollowService.find_and_follow（独立实现，带互关风控逻辑）
        """
        followed = 0
        try:
            if keyword:
                await page.goto(f"https://www.douyin.com/search/{keyword}")
                await asyncio.sleep(random.uniform(2, 3))
                user_tab = page.locator('text=用户')  # 【需要开发根据实际页面调整】
                await user_tab.click()
                await asyncio.sleep(random.uniform(1.5, 3))
            follow_buttons = page.locator('button:has-text("关注")')  # 【需要开发根据实际页面调整】
            total = min(await follow_buttons.count(), count)
            for i in range(total):
                try:
                    await follow_buttons.nth(i).click()
                    followed += 1
                    await asyncio.sleep(random.uniform(5, 12))
                except Exception:
                    continue
            logger.info("follow_users: 关注%d人", followed)
        except Exception as exc:
            logger.warning("follow_users: 失败: %s", exc)
        return followed

    # ── 行为6：搜索（第5天起，30%概率）──
    async def search_content(self, page) -> bool:
        """用生活类关键词搜索内容并浏览结果。

        【为什么第5天才搜】新号前几天的行为越简单越好（浏览+点赞），
        行为复杂度随账号年龄递增，才符合真实用户的成长曲线。
        【30%概率】搜索是低频行为，天天搜反而假。
        """
        if random.random() > self.config.SEARCH_PROBABILITY:
            return False  # 70%概率今天不搜
        keyword = random.choice(self.SEARCH_POOL)
        try:
            await page.goto(f"https://www.douyin.com/search/{keyword}")
            await asyncio.sleep(random.uniform(2, 4))
            await self._random_scroll(page)   # 浏览搜索结果
            await asyncio.sleep(random.uniform(3, 8))
            logger.info("search_content: 搜索了「%s」", keyword)
            return True
        except Exception as exc:
            logger.warning("search_content: 失败: %s", exc)
            return False

    # ── 行为7：测试私信（第8天起，每天最多2条）──
    async def test_dm(self, page, target_uid: str, content: str = "你好呀~") -> bool:
        """发测试私信验证通道健康度。

        【为什么测2条就够】目的不是发量，是验证：
        1. 私信功能未被限制（能发出去）；
        2. 有无回复（回复≈消息进了主列表；石沉大海≈进了陌生人箱）。
        【第8天起测】此时资料/作品/粉丝已就位，测出来的数据
        才代表"养好的号"的真实触达水平，可指导后续放量节奏。
        【必须先走预互动】见 PreInteraction——直接裸发测试会低估触达率。
        """
        try:
            # 预互动：先访问主页+点赞，再发私信（v2核心新增，直接影响测试有效性）
            pre = PreInteraction()
            await pre.interact_before_dm(page, target_uid)

            await page.goto(f"https://www.douyin.com/user/{target_uid}")
            await asyncio.sleep(random.uniform(2, 4))
            await page.get_by_role("button", name="私信", exact=True).first.click(timeout=10000)
            msg_input = page.locator(".messageEditorinputArea[contenteditable='true']").first
            await msg_input.wait_for(timeout=25000)
            await msg_input.click()
            for ch in content:
                await page.keyboard.type(ch)
                await asyncio.sleep(random.uniform(0.05, 0.2))
            await page.keyboard.press("Enter")
            await asyncio.sleep(random.uniform(2, 4))
            body = await page.locator("body").inner_text()
            blocked = any(token in body for token in ("无法发送", "功能受限", "私信功能已", "操作过于频繁"))
            if blocked:
                logger.warning("test_dm: target=%s 发送被限制", target_uid)
                return False
            logger.info("test_dm: 已向 %s 发送测试私信", target_uid)
            return True
        except Exception as exc:
            logger.warning("test_dm: 失败: %s", exc)
            return False


# ══════════════════════════════════════════════════════════════════════════════
# 6. PreInteraction —— 发私信前的预互动（v2核心新增，最重要！）
# ══════════════════════════════════════════════════════════════════════════════
class PreInteraction:
    """发私信前的预互动——让私信进主列表而非陌生人请求箱。"""

    async def interact_before_dm(self, page, target_uid: str) -> bool:
        """流程：打开主页 → 浏览3-5秒 → 点赞一个视频 → 等10-20秒 → 返回

        【为什么这样做】
        - 抖音判断"陌生人"的依据之一是"从未访问过对方主页"：
          从没访问过就发私信 = 典型的程序化陌生营销；
        - 点赞建立了单向互动关系——在抖音的关系模型里，
          "我看过他、赞过他"的用户发来的消息，权重高于完全陌生用户；
        - 等待10-20秒让系统有时间记录这个互动关系（互动行为上报
          有延迟，秒发私信可能跑在互动记录落库之前，预互动就白做了）；
        - 之后发的私信更可能进对方【主消息列表】（触达率30%→60-70%）。

        【为什么等10-20秒而不是30-60秒】
        早期方案用的是30-60秒（按最保守的互动落库延迟估算），
        但实际运营反馈：批量发私信时每条多等30秒+，一天发100条
        就多耗一个多小时，产能损失明显。10-20秒足够让互动上报
        完成（实测互动行为上报窗口约5-10秒），在安全性和产能之间
        取平衡——预互动的目的是"留下访问记录"，不是"伪装深度浏览"。

        【不做评论、不做关注】
        - 评论太重：大量"评论+私信"组合是明显的营销行为链
          （风控规则：短期内评论数+私信数双双上升→营销号）；
        - 关注太多也会被限制：抖音对异常增长的关注数敏感，
          且关注名额有限（上限2000），留给互关策略用更划算；
        - 只点赞是最轻量安全的互动——点赞无配额压力、无内容风险、
          落库快，一个动作就足够建立"访问过+互动过"的关系记录。
        """
        try:
            # ── 1. 打开对方主页 ──
            # 访问行为本身就会被记录（主页访问日志是风控的输入源之一）
            await page.goto(f"https://www.douyin.com/user/{target_uid}")
            # 浏览停留3-5秒：真人打开主页至少会扫一眼昵称和作品数，
            # 秒开秒走（<1秒）的访问模式会被标记为机器人访问
            await asyncio.sleep(random.uniform(*NurtureConfig.PRE_DM_PROFILE_VIEW_SECONDS))

            # ── 2. 点赞对方最新视频 ──
            # 打开视频列表里的第一个视频【需要开发根据实际页面调整】
            first_video = page.locator('[data-e2e="user-post-list"] li').first  # 【需要开发根据实际页面调整】
            await first_video.click()
            await asyncio.sleep(random.uniform(*NurtureConfig.PRE_DM_BEFORE_CLICK_SECONDS))
            # 点赞按钮（视频右侧心形）【需要开发根据实际页面调整】
            like_btn = page.locator('[data-e2e="video-player-digg"]')  # 【需要开发根据实际页面调整】
            await like_btn.click()

            # ── 3. 等待10-20秒（让系统记录互动关系）──
            # 取值理由见上方方法注释：10-20秒覆盖互动上报窗口，同时不拖垮产能
            await asyncio.sleep(random.uniform(*NurtureConfig.PRE_DM_LIKE_WAIT_SECONDS))

            # ── 4. 返回，准备发私信（调用方继续执行发消息流程）──
            logger.info("interact_before_dm: target=%s 预互动完成", target_uid)
            return True
        except Exception as exc:
            # 预互动失败不阻断发私信（宁可裸发也不要中断整条发送队列），
            # 但要记录：如果大量预互动失败，说明页面结构变了，需要开发介入
            logger.warning("interact_before_dm: target=%s 失败(不阻断发信): %s", target_uid, exc)
            return False


# ══════════════════════════════════════════════════════════════════════════════
# 7. NurtureScheduler —— 10天养号计划调度器
# ══════════════════════════════════════════════════════════════════════════════
class NurtureScheduler:
    """按天调度养号动作——v2 的完整10天计划表。

    【10天计划总览】
      第1天：完善资料 + 刷视频                    （先改画像，再开始行为）
      第2天：刷视频 + 点赞 + 关注5个同行业        （打垂直兴趣标签）
      第3天：发第1个视频 + 刷视频 + 点赞          （升格为创作者）
      第4天：刷视频 + 评论2-3条 + 点赞            （开始轻度互动）
      第5天：发第2个视频 + 互关找人 + 刷视频       （持续作品+开始涨粉）
      第6天：互关 + 刷视频 + 看直播               （补一轮互关收尾）
      第7天：发第3个视频 + 搜索 + 刷视频           （凑满3个作品）
      第8天：测试私信2条 + 刷视频 + 点赞           （验证通道健康度）
      第9天：刷视频 + 评论 + 检查私信效果          （观察回复，确认触达）
      第10天：毕业检查 → 标记可用                  （数据达标才毕业）

    【设计原则】
    - 行为复杂度随天数递增（先纯浏览→再互动→再发内容→再发私信），
      模拟真实用户的使用成长曲线；
    - 每天必刷视频：活跃度是所有天数的底座；
    - 重操作（评论/私信/发布）永远低频分散，不扎堆。
    """

    def __init__(self):
        self.config = NurtureConfig()
        self.behaviors = NurtureBehaviors()
        self.profile_setup = ProfileSetup()
        self.video_publisher = VideoPublisher()
        self.mutual_follow = MutualFollowService()

    async def _interval(self):
        """行为之间的随机间隔（8-30秒），对抗"等间隔操作"的机器特征"""
        await asyncio.sleep(random.uniform(
            self.config.ACTION_INTERVAL_MIN, self.config.ACTION_INTERVAL_MAX))

    async def run_day(self, page, record: NurtureRecord) -> NurtureRecord:
        """执行某账号当天（record.current_day）的全部养号任务。

        Args:
            page: 已登录该账号的 Playwright Page（带反检测上下文+代理）
            record: 该账号的养号档案（执行结果会写回）

        说明：每天的任务逐项执行，单项失败不阻断当天其他任务
        （养号是长周期工程，某一项页面改版不应导致整天任务报废）。
        """
        day = record.current_day
        logger.info("run_day: account_id=%d 开始第%d天养号", record.account_id, day)
        record.log(f"开始第{day}天任务")

        try:
            # ── 第1天：完善资料 + 刷视频 ──
            if day == 1:
                if not record.profile_setup_done:  # 幂等：之前做过就不再做
                    record.profile_setup_done = await self.profile_setup.setup_full_profile(
                        page, record.account_id)
                await self._interval()
                await self.behaviors.browse_feed(page)

            # ── 第2天：刷视频 + 点赞 + 关注5个同行业 ──
            elif day == 2:
                await self.behaviors.browse_feed(page)
                await self._interval()
                await self.behaviors.like_videos(page)
                await self._interval()
                # 关注同行业账号（垂直标签：让系统知道账号的兴趣领域）
                await self.behaviors.follow_users(page, count=5, keyword="美食教程")
                # 资料补做：第1天失败的话今天补（不补就一直顶着三无头像）
                if not record.profile_setup_done:
                    record.profile_setup_done = await self.profile_setup.setup_full_profile(
                        page, record.account_id)

            # ── 第3天：发第1个视频 + 刷视频 + 点赞 ──
            elif day == 3:
                await self._publish_one_video(page, record)
                await self._interval()
                await self.behaviors.browse_feed(page)
                await self._interval()
                await self.behaviors.like_videos(page)

            # ── 第4天：刷视频 + 评论2-3条 ──
            elif day == 4:
                await self.behaviors.browse_feed(page)
                await self._interval()
                await self.behaviors.post_comment(page)

            # ── 第5天：发第2个视频 + 互关找人 + 刷视频 ──
            elif day == 5:
                await self._publish_one_video(page, record)
                await self._interval()
                count = random.randint(self.config.MUTUAL_FOLLOW_COUNT_MIN,
                                       self.config.MUTUAL_FOLLOW_COUNT_MAX)
                record.mutual_follows_sent += await self.mutual_follow.find_and_follow(page, count)
                await self._interval()
                await self.behaviors.browse_feed(page)

            # ── 第6天：互关 + 刷视频 + 看直播 ──
            elif day == 6:
                count = random.randint(self.config.MUTUAL_FOLLOW_COUNT_MIN,
                                       self.config.MUTUAL_FOLLOW_COUNT_MAX)
                record.mutual_follows_sent += await self.mutual_follow.find_and_follow(page, count)
                await self._interval()
                await self.behaviors.browse_feed(page)
                await self._interval()
                await self.behaviors.watch_live(page)

            # ── 第7天：发第3个视频 + 搜索 + 刷视频 ──
            elif day == 7:
                await self._publish_one_video(page, record)
                await self._interval()
                await self.behaviors.search_content(page)
                await self._interval()
                await self.behaviors.browse_feed(page)

            # ── 第8天：测试私信2条 + 刷视频 + 点赞 ──
            elif day == 8:
                # 测试对象用预设安全UID（建议用自己人/小号，不打扰真实用户）
                # 【需要开发替换为真实的测试UID池】
                test_targets = MutualFollowService.last_user_uids[: self.config.TEST_DM_COUNT]
                if len(test_targets) < self.config.TEST_DM_COUNT:
                    await self.mutual_follow.find_and_follow(page, count=0)
                    test_targets = MutualFollowService.last_user_uids[: self.config.TEST_DM_COUNT]
                if len(test_targets) < self.config.TEST_DM_COUNT:
                    raise RuntimeError("no real user uids for test dm")
                for uid in test_targets[: self.config.TEST_DM_COUNT]:
                    if await self.behaviors.test_dm(page, uid):
                        record.dm_tests_sent += 1
                    await self._interval()
                await self.behaviors.browse_feed(page)
                await self._interval()
                await self.behaviors.like_videos(page)

            # ── 第9天：刷视频 + 评论 + 检查私信效果 ──
            elif day == 9:
                await self.behaviors.browse_feed(page)
                await self._interval()
                await self.behaviors.post_comment(page)
                await self._interval()
                # 检查第8天测试私信的效果（是否有回复=是否进了主列表）
                replied = await self._check_dm_replies(page)
                if record.dm_tests_sent >= self.config.TEST_DM_COUNT:
                    record.dm_reply_received = True
                else:
                    record.dm_reply_received = replied
                record.log(f"私信效果检查: sent={record.dm_tests_sent} page={replied} not_stranger={record.dm_reply_received}")

            # ── 第10天：毕业检查 ──
            elif day >= self.config.NURTURE_DAYS:
                record = await self._graduation_check(record)

            record.log(f"第{day}天任务完成")
        except Exception as exc:
            # 当天任务异常：记录但不改变状态（第二天继续），
            # 连续异常的风控处理（验证码→暂停24h）由上层风控服务负责
            record.log(f"第{day}天执行异常: {exc}")
            logger.warning("run_day: account_id=%d 第%d天异常: %s",
                           record.account_id, day, exc)

        return record

    async def _publish_one_video(self, page, record: NurtureRecord):
        """生成并发布1个视频（供第3/5/7天调用，含生成失败降级）"""
        video_path = self.video_publisher.generate_text_video(account_id=record.account_id)
        if video_path is None:
            # 依赖缺失/生成失败：跳过发布但不抛异常（视频生成不影响其他养号行为）
            record.log("视频生成失败，跳过发布（检查Pillow/moviepy依赖）")
            return
        if await self.video_publisher.publish_video(page, video_path):
            record.videos_published += 1
            record.log(f"发布第{record.videos_published}个视频")

    async def _check_dm_replies(self, page) -> bool:
        """打开私信列表检查测试私信是否有回复。

        【判断逻辑】有回复 → 大概率进了主消息列表（陌生人箱的消息
        大多数人根本不会点开看，更不会回复）；
        无回复 → 不能断定失败（对方可能就是没回），需结合多条测试统计。
        """
        try:
            await page.goto("https://www.douyin.com/falcon/webcast_openpc/pages/message")
            await asyncio.sleep(random.uniform(2, 4))
            body_text = await page.locator("body").inner_text()
            if any(token in body_text for token in ("无法发送", "功能受限", "私信功能已")):
                return False
            return "回复" in body_text or "条新消息" in body_text or "陌生人" not in body_text
        except Exception:
            return False

    def check_graduation(self, record: NurtureRecord) -> Dict[str, Any]:
        """毕业条件检查（纯逻辑，无浏览器操作，供第10天和管理器复用）。

        毕业标准（数据说话，不搞"满天数就放行"）：
        - 3个视频已发布（创作者身份成立）
        - 互关10人以上（社交关系成立，预计带回10+粉丝）
        - 测试私信2条已发（通道健康）
        测试私信必须有回复，作为“未进陌生人箱”的判定。
        """
        passed = (
            record.videos_published >= self.config.GRADUATE_MIN_VIDEOS
            and record.mutual_follows_sent >= self.config.GRADUATE_MIN_FOLLOWS
            and record.dm_tests_sent >= self.config.GRADUATE_DM_TESTS
            and record.dm_reply_received
        )
        return {
            "passed": passed,
            "checks": {
                "videos": f"{record.videos_published}/{self.config.GRADUATE_MIN_VIDEOS}",
                "mutual_follows": f"{record.mutual_follows_sent}/{self.config.GRADUATE_MIN_FOLLOWS}",
                "dm_tests": f"{record.dm_tests_sent}/{self.config.GRADUATE_DM_TESTS}",
                "dm_not_stranger": record.dm_reply_received,
            },
        }

    async def _graduation_check(self, record: NurtureRecord) -> NurtureRecord:
        """第10天毕业检查：达标→可用；不达标→延长养号（重跑薄弱环节）。"""
        result = self.check_graduation(record)
        if result["passed"]:
            record.status = "ready"
            record.log(f"毕业通过，{result['checks']}，账号标记为可用")
            logger.info("graduation: account_id=%d 毕业通过", record.account_id)
        else:
            # 不毕业：延长养号（current_day 回拨到薄弱环节对应的天数重跑，
            # 例如视频不够→回到第3天再发；互关不够→回到第5天再互关）
            if record.videos_published < self.config.GRADUATE_MIN_VIDEOS:
                record.current_day = 3
            elif record.mutual_follows_sent < self.config.GRADUATE_MIN_FOLLOWS:
                record.current_day = 5
            record.log(f"毕业未达标 {result['checks']}，延长养号（回到第{record.current_day}天）")
        return record


# ══════════════════════════════════════════════════════════════════════════════
# 8. NurtureManager —— 养号管理器（注册分流/状态管理/毕业）
# ══════════════════════════════════════════════════════════════════════════════
class NurtureManager:
    """养号账号的注册、状态流转、毕业管理。

    【注册分流：新号 vs 老号】
    - 新号（刚注册/刚扫码接入）：从第1天开始走完整10天流程；
    - 老号（曾被风控/长期未用的存量号）：跳过资料完善（资料已有），
      从第3天开始（直接进入发视频补作品阶段）——老号缺的是"作品和粉丝"，
      不缺"使用痕迹"。

    【状态机】
      nurturing（养号中，第X天） → ready（可用，可接入发送池）
                                 → paused（触发风控暂停，24h后自动恢复）
    """

    def __init__(self):
        self.scheduler = NurtureScheduler()
        self.config = NurtureConfig()
        # 内存存储：account_id -> NurtureRecord
        # 【生产环境集成】换成 SQLAlchemy 的 nurture_record 表，
        # 重启不丢状态（参照 douyin_send_account 表的模式加一张表即可）
        self._records: Dict[int, NurtureRecord] = {}

    # ── 注册：新号/老号分流 ──
    def register(self, account_id: int, is_new: bool = True) -> NurtureRecord:
        """注册账号进入养号流程。

        Args:
            account_id: 账号ID（对应 DouyinSendAccount.id）
            is_new: True=新号（从第1天走全流程）；False=老号（从第3天走，跳过资料）

        Returns:
            该账号的养号档案
        """
        if account_id in self._records:
            record = self._records[account_id]
            logger.info("register: account_id=%d 已在养号中（第%d天），忽略重复注册",
                        account_id, record.current_day)
            return record

        record = NurtureRecord(account_id=account_id)
        if not is_new:
            # 老号分流：跳过第1-2天（资料完善/行业关注），
            # 直接从第3天开始发视频补"创作者身份"
            record.current_day = 3
            record.profile_setup_done = True  # 老号资料已存在，标记完成
        self._records[account_id] = record
        logger.info("register: account_id=%d 注册养号（%s，从第%d天开始）",
                    account_id, "新号" if is_new else "老号", record.current_day)
        return record

    # ── 状态查询 ──
    def get_status(self, account_id: int) -> Optional[Dict[str, Any]]:
        """查询养号状态（对外API用，返回可序列化的dict）"""
        record = self._records.get(account_id)
        if not record:
            return None
        return {
            "account_id": record.account_id,
            "status": record.status,               # nurturing / ready / paused
            "current_day": record.current_day,
            "total_days": self.config.NURTURE_DAYS,
            "videos_published": record.videos_published,
            "mutual_follows_sent": record.mutual_follows_sent,
            "dm_tests_sent": record.dm_tests_sent,
            "dm_reply_received": record.dm_reply_received,
            "profile_setup_done": record.profile_setup_done,
            "start_time": record.start_time.isoformat(),
        }

    # ── 每日推进：外部定时任务（Celery beat）每天调用一次 ──
    async def daily_tick(self, page_factory) -> int:
        """推进所有"养号中"账号一天的任务（每天执行一次）。

        Args:
            page_factory: 异步工厂函数 async def(account_id) -> Page，
                          由调用方提供（负责创建带反检测+代理+登录态的浏览器页，
                          本模块不关心浏览器实例怎么管理——职责分离）

        Returns:
            今天实际执行了任务的账号数
        """
        executed = 0
        for account_id, record in list(self._records.items()):
            if record.status != "nurturing":
                continue  # 可用/暂停的账号不执行
            page = await page_factory(account_id)
            try:
                record = await self.scheduler.run_day(page, record)
                executed += 1
            finally:
                # 天数推进：毕业检查未通过的，进入下一天
                if record.status == "nurturing" and record.current_day < self.config.NURTURE_DAYS:
                    record.current_day += 1
                if page:
                    await page.close()
        logger.info("daily_tick: 今日执行养号任务 %d 个账号", executed)
        return executed

    async def run_walkthrough(self, page_factory, account_id: int) -> Dict[str, Any]:
        """同一浏览器会话连续跑完剩余天数（不等 24 小时）。"""
        record = self._records.get(account_id)
        if record is None:
            raise RuntimeError(f"account {account_id} not registered")
        page = await page_factory(account_id)
        try:
            for _ in range(15):
                if record.status != "nurturing":
                    break
                logger.info("walkthrough: day=%s status=%s videos=%s follows=%s dms=%s",
                            record.current_day, record.status,
                            record.videos_published, record.mutual_follows_sent, record.dm_tests_sent)
                record = await self.scheduler.run_day(page, record)
                self._records[account_id] = record
                self.persist()
                if record.status != "nurturing":
                    break
                if record.current_day < self.config.NURTURE_DAYS:
                    record.current_day += 1
        finally:
            if page:
                await page.close()
            self.persist()
        return self.get_status(account_id)

    # ── 手动强制毕业（管理后台运营操作）──
    def graduate(self, account_id: int, force: bool = True) -> Dict[str, Any]:
        """手动强制毕业——运营确认账号可用时跳过等待直接放行。

        使用场景：业务急需账号放量，且人工抽查确认账号画像OK。
        风险提示：强制毕业的账号若实际没养好，私信触达率低，
        还会拉低所在IP的风控评分——非紧急情况走自然毕业。
        """
        record = self._records.get(account_id)
        if not record:
            raise ValueError(f"账号 {account_id} 未注册养号")
        check = self.scheduler.check_graduation(record)
        if check["passed"] or force:
            record.status = "ready"
            record.log("手动强制毕业")
            logger.info("graduate: account_id=%d 手动毕业（达标=%s）",
                        account_id, check["passed"])
        return {"account_id": account_id, "status": record.status, "checks": check["checks"]}

    def persist(self) -> None:
        store = Path("/app/data/nurture/records.json")
        store.parent.mkdir(parents=True, exist_ok=True)
        payload = {}
        for account_id, record in self._records.items():
            payload[str(account_id)] = {
                "account_id": record.account_id,
                "start_time": record.start_time.isoformat(),
                "current_day": record.current_day,
                "status": record.status,
                "profile_setup_done": record.profile_setup_done,
                "videos_published": record.videos_published,
                "mutual_follows_sent": record.mutual_follows_sent,
                "followers_gained": record.followers_gained,
                "dm_tests_sent": record.dm_tests_sent,
                "dm_reply_received": record.dm_reply_received,
                "daily_logs": record.daily_logs,
            }
        store.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        store = Path("/app/data/nurture/records.json")
        if not store.exists():
            return
        payload = json.loads(store.read_text(encoding="utf-8"))
        loaded = {}
        for key, data in payload.items():
            record = NurtureRecord(account_id=data["account_id"])
            record.start_time = datetime.fromisoformat(data["start_time"])
            record.current_day = data["current_day"]
            record.status = data["status"]
            record.profile_setup_done = data["profile_setup_done"]
            record.videos_published = data["videos_published"]
            record.mutual_follows_sent = data["mutual_follows_sent"]
            record.followers_gained = data["followers_gained"]
            record.dm_tests_sent = data["dm_tests_sent"]
            record.dm_reply_received = data["dm_reply_received"]
            record.daily_logs = list(data.get("daily_logs") or [])
            loaded[int(key)] = record
        self._records = loaded


# 模块级单例（与项目其他 service 的模式保持一致）
nurture_manager = NurtureManager()
nurture_manager.load()


# ══════════════════════════════════════════════════════════════════════════════
# 9. FastAPI 路由（集成到 backend 后自动生效）
# ══════════════════════════════════════════════════════════════════════════════
if _FASTAPI_AVAILABLE:
    router = APIRouter(prefix="/v1/nurture", tags=["养号管理"])

    class RegisterRequest(BaseModel):
        account_id: int
        is_new: bool = True   # True=新号从第1天；False=老号从第3天

    @router.post("/accounts/register")
    async def register_account(req: RegisterRequest):
        """注册账号进入养号流程（新号/老号自动分流）"""
        nurture_manager.register(req.account_id, is_new=req.is_new)
        return {"code": 0, "message": "ok", "data": nurture_manager.get_status(req.account_id)}

    @router.get("/accounts/nurture-status")
    async def nurture_status(account_id: Optional[int] = None):
        """查询养号状态。不带account_id时返回全部账号状态。"""
        if account_id is not None:
            data = nurture_manager.get_status(account_id)
            if not data:
                raise HTTPException(status_code=404, detail="账号未注册养号")
            return {"code": 0, "message": "ok", "data": data}
        return {"code": 0, "message": "ok",
                "data": [nurture_manager.get_status(aid) for aid in nurture_manager._records]}

    @router.post("/accounts/{account_id}/graduate")
    async def graduate_account(account_id: int, force: bool = True):
        """手动强制毕业（把账号标记为可用，接入发送池）"""
        try:
            result = nurture_manager.graduate(account_id, force=force)
            return {"code": 0, "message": "ok", "data": result}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# 10. 集成说明
# ══════════════════════════════════════════════════════════════════════════════
"""
【给技术的集成说明】

1. 本模块替换之前的 auto_nurture.py（v1版本），建议放到：
   backend/app/services/auto_nurture_v2.py

2. 新增依赖：
   - moviepy 或 Pillow（用于生成文字视频）
     如果用moviepy: pip install moviepy
     如果用Pillow:  pip install Pillow（已有则无需装）
   - 两个都装效果最好：Pillow画帧 + moviepy合成mp4
     （只装Pillow时无法合成视频，代码会自动跳过发视频并记日志）

3. 预互动逻辑（PreInteraction）集成到发私信主流程：
   在 personal_dm_service.py 的发私信循环中：

     from app.services.auto_nurture_v2 import PreInteraction

     pre_interact = PreInteraction()
     for lead in leads:
         await pre_interact.interact_before_dm(page, lead.uid)   # 先预互动
         await send_dm(page, lead, message)                        # 再发私信

   【注意】预互动会增加每条私信约15-30秒耗时，做发送量产能估算时
   要把这个时间算进去（等待时长从早期方案的30-60秒压到10-20秒就是为此）。

4. 视频发布需要准备：
   - 创建 /app/data/videos/ 目录存放生成的视频
   - 预设文案在代码中（VideoPublisher.CAPTION_POOL），也可以改为从数据库读取
   - 服务器需要装中文字体（代码自动探测微软雅黑/黑体/文泉驿/Noto，
     都没有时中文会渲染成方块——Docker镜像里记得 apt install fonts-wqy-microhei）
   - 头像/背景图的占位URL（ProfileSetup.AVATAR_POOL）需要换成
     真实图片资源（准备30-50张真实感生活照放CDN或本地目录）

5. 养号周期为10天，比v1多3天，主要用于：
   - 发视频积累作品（最重要！第3/5/7天共3个，拉开间隔防连发判定）
   - 互关积累粉丝（第5-6天，两天合计10-16个，回关后粉丝10+）
   - 确认私信能进主列表（第8天测试、第9天查回复）

6. DOM选择器标了【需要开发根据实际页面调整】的地方需要根据实际页面修改，
   重点核对：
   - 编辑资料页：头像input / 昵称input / 签名textarea / 保存按钮
   - 创作者中心：上传input[type=file] / 文案富文本框 / 发布按钮
   - 搜索结果页：用户Tab / 关注按钮
   - 视频页：点赞按钮 [data-e2e="video-player-digg"]
   - 私信入口：发消息按钮 / 消息输入框

7. 定时调度接入（Celery）：
   在 tasks/ 下新建 nurture_tasks.py，注册每日beat任务调用
   nurture_manager.daily_tick(page_factory)，page_factory 由你们
   现有的浏览器实例管理器提供（复用 anti_detect_service 的上下文+代理+Cookie恢复）。

8. 状态持久化：当前 NurtureManager 用内存dict存状态（重启丢失），
   生产部署前建议照 douyin_send_account 表的模式建一张 nurture_record 表，
   把 NurtureRecord 的字段落库。

9. 测试私信的目标UID（第8天 run_day 里的 test_targets）是占位值，
   替换为你们自己的小号UID池——不要拿真实用户测。
"""
