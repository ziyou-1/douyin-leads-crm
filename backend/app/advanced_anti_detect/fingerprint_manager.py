"""
浏览器指纹固定化管理器
======================

【核心思想】每个账号第一次运行时生成一套指纹 → 保存到 JSON 文件 → 以后永远用这套不变。

【为什么要"固定"而不是"每次随机"？（新接手开发的必读原理）】
真实设备的指纹永远不会变：你家的电脑今天和明天的分辨率、显卡、字体都一样。
抖音风控会把同一账号多次登录的指纹做对比，一旦发现"指纹跳变"：
    昨天 1920x1080 + Chrome/121 + GTX1060 + 上海时区
    今天 2560x1440 + Chrome/126 + RTX3060 + 纽约时区   ← 可疑！
→ 判定"账号被盗"或"在用自动化工具" → 触发验证码甚至封号。
结论：随机化 ≠ 反检测。指纹的【一致性】才是真人特征，一个号一套指纹用到死。

【指纹是怎么被采集的】
抖音前端 JS 读取 navigator / screen / WebGL / Canvas / AudioContext / 字体等
几十个属性，组合成一个"指纹哈希"用于追踪用户。即使清了 Cookie，
指纹不变它就还能认出你——所以反过来，指纹稳定 = 身份稳定 = 安全。

【存储】JSON 文件：/app/data/fingerprints/{account_id}.json
（/app/data 是 Docker 挂载的持久化目录，容器重建后指纹不丢失）
"""

import json
import random
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 指纹文件存储目录（Docker 数据卷内，持久化）
FINGERPRINT_DIR = Path("/app/data/fingerprints")


@dataclass
class BrowserProfile:
    """
    一套完整的浏览器指纹（每个账号一份，永久固定不变）。

    每个字段都对应一个抖音能通过 JS 检测到的浏览器属性：
    - screen_width/height : window.screen 读取，必须是常见分辨率（1234x567=假）
    - user_agent          : UA 字符串，Chrome 版本要跟主流一致（太老=假）
    - timezone            : 时区，必须和代理 IP 城市匹配（北京IP+纽约时区=必死）
    - webgl_vendor/renderer: 显卡型号，虚拟机返回 llvmpipe 会被直接识破
    - canvas_noise_seed   : Canvas 噪声种子，必须固定（同号永远同噪声）
    - audio_context_hash  : AudioContext 音频指纹哈希
    - font_list           : 系统字体列表，要和 platform 匹配（Win字体+Mac系统=假）
    - hardware_concurrency: CPU 核数，1 核会被怀疑是虚拟机
    - device_memory       : 内存 GB，常见 4/8/16（1GB=假）
    """
    account_id: int                  # 账号ID（与指纹一对一绑定）
    screen_width: int = 1920         # 屏幕宽（像素）
    screen_height: int = 1080        # 屏幕高（像素）
    user_agent: str = ""             # 浏览器 UA
    timezone: str = "Asia/Shanghai"  # 时区（与住宅代理IP城市匹配）
    language: str = "zh-CN"          # navigator.language
    webgl_vendor: str = ""           # WebGL 显卡厂商
    webgl_renderer: str = ""         # WebGL 显卡型号
    canvas_noise_seed: int = 0       # Canvas 噪声种子（固定！）
    audio_context_hash: str = ""     # AudioContext 指纹哈希
    font_list: List[str] = field(default_factory=list)  # 系统字体列表
    platform: str = "Win32"          # navigator.platform（与UA系统一致）
    hardware_concurrency: int = 8    # CPU 逻辑核数
    device_memory: int = 8           # 设备内存（GB）
    created_at: str = ""             # 指纹创建时间（创建后永不变）


class FingerprintManager:
    """
    指纹管理器：负责"读取或创建"账号指纹的唯一入口。

    用法：
        mgr = FingerprintManager()
        profile = await mgr.get_or_create_profile(account_id=123)
        # 之后把 profile 用于 browser.new_context() 参数 和 stealth_scripts 注入
    """

    # 常见分辨率（按真实市占率选取，1920x1080 最常见）
    RESOLUTIONS = [(1920, 1080), (1366, 768), (1536, 864), (2560, 1440), (1440, 900)]

    # 常见显卡（真实 Windows Chrome 设备的 WebGL vendor/renderer）
    # 虚拟机/无头环境返回 "llvmpipe"/"SwiftShader" 会被直接识别 → 必须覆盖
    GPUS = [
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ]

    # Windows 中文系统常见字体（缺微软雅黑/宋体 = 国内环境造假，会被识破）
    FONTS = ["Arial", "Calibri", "Consolas", "Courier New", "Georgia", "Segoe UI",
             "Tahoma", "Times New Roman", "Verdana", "Microsoft YaHei", "SimSun", "SimHei"]

    def __init__(self, storage_dir: Path = FINGERPRINT_DIR):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict = {}  # 内存缓存：避免每次操作都读磁盘

    async def get_or_create_profile(self, account_id: int) -> BrowserProfile:
        """
        获取（或首次创建）账号指纹 —— 本模块最核心的方法。

        流程：内存缓存 → JSON 文件 → 都没有才生成新的。
        第一次调用是 create，之后永远都是 get，【绝不重新生成】。
        """
        # 第1步：查内存缓存（最快）
        if account_id in self._cache:
            return self._cache[account_id]

        # 第2步：查 JSON 文件
        profile = self._load_from_file(account_id)

        # 第3步：文件也没有 → 首次使用，生成并立即落盘
        if profile is None:
            profile = self._generate(account_id)
            self._save_to_file(profile)
            print(f"[指纹] 账号{account_id} 生成新指纹: "
                  f"{profile.screen_width}x{profile.screen_height}, {profile.webgl_renderer[:35]}")
        else:
            print(f"[指纹] 账号{account_id} 复用已有指纹（永久固定不变）")

        self._cache[account_id] = profile
        return profile

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _generate(self, account_id: int) -> BrowserProfile:
        """
        生成一套"看起来像真实电脑"的指纹（仅在账号首次使用时调用一次）。

        【关键设计】用 account_id 做随机种子（确定性随机）：
        → 即使 JSON 文件意外丢失，重新生成的指纹与原来一模一样，
          不会发生"指纹跳变"（兜底机制；正常情况永远走文件读取）。
        生成的各属性之间保持一致性（高配显卡不配1G内存等合理组合）。
        """
        rng = random.Random(account_id)  # 同账号 → 永远生成同一套指纹

        width, height = rng.choice(self.RESOLUTIONS)
        chrome_ver = rng.randint(121, 126)  # 跟随主流 Chrome 版本（需定期维护此范围）
        vendor, renderer = rng.choice(self.GPUS)
        canvas_seed = rng.randint(1, 10 ** 9)      # 噪声种子：生成后永不改变
        audio_hash = hashlib.md5(f"audio-{account_id}-{canvas_seed}".encode()).hexdigest()[:16]
        fonts = rng.sample(self.FONTS, rng.randint(8, len(self.FONTS)))  # 字体子集

        return BrowserProfile(
            account_id=account_id,
            screen_width=width,
            screen_height=height,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36"
            ),
            timezone="Asia/Shanghai",       # 与国内住宅代理 IP 匹配
            language="zh-CN",
            webgl_vendor=vendor,
            webgl_renderer=renderer,
            canvas_noise_seed=canvas_seed,
            audio_context_hash=audio_hash,
            font_list=fonts,
            platform="Win32",               # 与 UA 里的 Windows 保持一致
            hardware_concurrency=rng.choice([4, 8, 8, 12, 16]),  # 8核最常见
            device_memory=rng.choice([4, 8, 8, 16]),             # 8GB最常见
            created_at=datetime.now().isoformat(),
        )

    def _file_path(self, account_id: int) -> Path:
        """指纹文件路径：/app/data/fingerprints/{account_id}.json"""
        return self.storage_dir / f"{account_id}.json"

    def _load_from_file(self, account_id: int) -> Optional[BrowserProfile]:
        """从 JSON 文件读取指纹（文件不存在返回 None）"""
        path = self._file_path(account_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BrowserProfile(**data)
        except Exception as e:
            # 文件损坏时不静默重新生成（防止指纹跳变），报错让人工介入修复
            raise RuntimeError(f"账号{account_id}的指纹文件损坏，请人工修复而非删除: {e}")

    def _save_to_file(self, profile: BrowserProfile) -> None:
        """把指纹写入 JSON 文件（先写临时文件再替换，防止写一半宕机损坏）"""
        path = self._file_path(profile.account_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

