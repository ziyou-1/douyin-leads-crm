"""
高级反检测模块（advanced_anti_detect）
=====================================
六个子模块：指纹固定化 / 行为模拟 / 代理管理 / 会话持久化 / 智能调度 / 深度伪装。
详细用法和集成步骤见同目录 README-开发必读.md。
"""
from .fingerprint_manager import BrowserProfile, FingerprintManager
from .behavior_simulator import BehaviorSimulator
from .proxy_manager import ProxyManager, ProxyInfo, ProxyStatus
from .session_manager import SessionManager
from .smart_scheduler import SmartScheduler, AccountHealthScore, CAPTCHA, RATE_LIMIT, ACCOUNT_LOCKED
from .stealth_scripts import get_stealth_script, STEALTH_INJECTION_SCRIPT, apply_stealth_scripts

__all__ = [
    "BrowserProfile", "FingerprintManager",
    "BehaviorSimulator",
    "ProxyManager", "ProxyInfo", "ProxyStatus",
    "SessionManager",
    "SmartScheduler", "AccountHealthScore",
    "CAPTCHA", "RATE_LIMIT", "ACCOUNT_LOCKED",
    "get_stealth_script", "STEALTH_INJECTION_SCRIPT", "apply_stealth_scripts",
]
