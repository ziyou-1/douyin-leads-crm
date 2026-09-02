# 高级反检测代码包 - 开发必读

> 面向开发的集成说明文档。拿到这个代码包请**先读完本文档**再开始集成。

---

## 一、模块总览

本代码包包含 6 个核心 Python 文件，各自负责反检测的一个维度：

| 文件 | 一句话概括 |
|------|-----------|
| `fingerprint_manager.py` | 浏览器指纹固定化管理器：每个账号生成一套固定指纹（分辨率/UA/显卡/字体等），JSON 存储永久不变 |
| `behavior_simulator.py` | 高级行为模拟器：真人滚动（快-慢-停-看）、真人打字（犹豫/错字）、贝塞尔曲线鼠标移动 |
| `proxy_manager.py` | IP 代理管理器：账号-IP 永久绑定、定期健康检查、被封后自动换同城住宅 IP |
| `session_manager.py` | Cookie/Session 持久化：登录一次保存会话，每 4 小时保活续期，免重复登录 |
| `smart_scheduler.py` | 智能调度+熔断：综合判断能不能发消息；验证码→休息、限流→降速、锁号→停用通知 |
| `stealth_scripts.py` | 深度指纹伪装 JS 注入：Canvas 噪声/WebRTC 防泄露/AudioContext/WebGL/Navigator 全覆盖 |

---

## 二、集成优先级（先做哪个效果最大？）

按投入产出比排序，**强烈建议按此顺序集成**：

| 优先级 | 模块 | 效果说明 |
|-------|------|---------|
| 1 | 指纹固定化 | **效果最大**。防止每次登录指纹变化被检测——指纹跳变是最容易被抓的自动化特征 |
| 2 | Cookie 持久化 | **减少 80% 的掉线次数**。免重复登录 = 少触发验证码 = 账号更安全 |
| 3 | 住宅代理 IP 绑定 | 防止 IP 关联封号（同 IP 多号 = 批量封） |
| 4 | 行为模拟升级 | 让操作更像真人（滚动/打字/鼠标轨迹全真人化） |
| 5 | 深度指纹伪装 | 防止高级检测（Canvas/WebGL/AudioContext 等维度） |
| 6 | 智能调度熔断 | 出问题时自动保护（验证码休息/限流降速/锁号停用） |

---

## 三、依赖安装

```bash
pip install playwright aiohttp

# 安装 Playwright 浏览器内核（必须）
playwright install chromium

# 如使用 socks5 代理做健康检查，还需：
pip install aiohttp-socks
```

---

## 四、代理服务商推荐对比表

**必须使用住宅代理（Residential），严禁数据中心代理（Datacenter）**——数据中心 IP 在公开黑名单里，几乎必被识别为代理，封号率极高。省下的代理费会加倍赔回在封号损失上。

### 国内住宅代理（做抖音必用）

| 服务商 | 网址 | 价格 | 特点 |
|--------|------|------|------|
| 快代理 | kuaidaili.com | 约 2-3 元/IP/天 | 国内最大住宅 IP 池，稳定性最好（**首选**） |
| 芝麻代理 | zhimahttp.com | 约 2-3 元/IP/天 | 住宅质量好，按天/按量计费灵活 |
| 品易代理 | pyhttp.com | 约 1.5-2 元/IP/天 | 性价比高，适合中小规模 |
| 讯代理 | xdaili.cn | 约 1-2 元/IP/天 | 老牌服务商，有短效和长效 IP |

### 海外住宅代理（做 TikTok 海外版用）

| 服务商 | 网址 | 价格 | 特点 |
|--------|------|------|------|
| BrightData | brightdata.com | $10-15/GB | 全球最大（7200万+ IP），贵但质量最好 |
| Oxylabs | oxylabs.io | $8-12/GB | 第二梯队，价格略低 |
| SmartProxy | smartproxy.com | $5-8/GB | 入门级，适合小规模测试 |

**购买建议**：10 个号以内买短效住宅 IP（约 30 元/天）；10-50 个号买长效按月（500-1500 元/月）；50 个号以上买独享 IP（2000-5000 元/月）。代理数量建议 = 账号数量 × 1.5（留 50% 备用余量）。

---

## 五、集成到现有项目的步骤（3 步）

### 第 1 步：把代码包放进项目

把整个 `advanced_anti_detect/` 文件夹复制到你的项目里（与业务代码同级），确保目录下有 `__init__.py`。

### 第 2 步：改造浏览器启动代码

在现有创建 BrowserContext 的地方，替换为"指纹 + 代理 + 会话 + 伪装脚本"的完整启动流程：

```python
from advanced_anti_detect import (
    FingerprintManager, SessionManager, ProxyManager,
    BehaviorSimulator, SmartScheduler, apply_stealth_scripts,
)

# --- 程序启动时初始化一次 ---
fp_mgr = FingerprintManager()                       # 指纹存在 /app/data/fingerprints/
session_mgr = SessionManager()                      # 会话存在 /app/data/sessions/
proxy_mgr = ProxyManager(proxy_pool=load_proxies()) # 代理池从服务商 API 拉取
scheduler = SmartScheduler()
scheduler.register(account_id=123, daily_limit=40)

# --- 每个账号的浏览器启动流程 ---
proxy_url = await proxy_mgr.get_proxy(account_id=123)          # ① 拿固定IP
profile = await fp_mgr.get_or_create_profile(account_id=123)   # ② 拿固定指纹

browser = await p.chromium.launch(proxy={"server": proxy_url}, headless=False)
context = await browser.new_context(
    viewport={"width": profile.screen_width, "height": profile.screen_height},
    user_agent=profile.user_agent,
    timezone_id=profile.timezone,
    locale=profile.language,
)
await apply_stealth_scripts(context, profile)                   # ③ 注入伪装脚本（必须在 new_page 之前！）

# ④ 恢复会话（免登录）
restored = await session_mgr.restore_session(account_id=123, context=context)
page = await context.new_page()
await page.goto("https://www.douyin.com")
if not restored or not await session_mgr.check_login_state(page):
    await do_login(page)                                        # 需要时才登录
    await session_mgr.save_session(account_id=123, context=context)  # 登录后立即保存

# ⑤ 启动后台保活（每4小时自动续期 Token）
await session_mgr.start_keep_alive_loop(123, get_page=lambda: page)
```

### 第 3 步：改造发送动作（调度判断 + 真人行为）

把现有"直接发送"的地方改为"先问调度器 + 用行为模拟器"：

```python
sim = BehaviorSimulator(page)

for target in targets:
    # ① 问调度器：现在能发吗？（日限/频率/时段/风控/健康度综合判断）
    if not scheduler.should_send(account_id=123):
        print("暂停:", scheduler.get_block_reason(account_id=123))
        break

    # ② 真人化操作：先浏览 → 曲线移鼠标 → 真人打字
    await sim.pre_action_browse()                    # 打开先看几秒，别秒操作
    await sim.bezier_mouse_move(x, y)                # 贝塞尔曲线移到输入框
    await sim.human_like_type("你好，想了解一下~", selector="textarea")
    # ... 点击发送 ...

    # ③ 回填结果（供健康度统计）
    scheduler.record_send(account_id=123, success=True)

# ④ 收到风控信号时通知调度器（在异常处理里加）
# scheduler.on_risk_signal(account_id=123, signal_type="captcha")
```

> 每天凌晨 0 点记得调 `scheduler.reset_daily()` 重置日计数（可用 APScheduler 定时）。

---

## 六、预期效果

| 指标 | 集成前（裸跑） | 集成后（全套） |
|------|--------------|--------------|
| 每日掉线次数 | 8 次 | **1-3 次** |
| 封号率 | 30% | **5%** |
| 每日登录次数 | 8-12 次 | 0-1 次 |
| 登录有效期 | 12 小时 | 3-7 天 |

### 注意事项

1. **没有 100% 不被检测的方案**：反检测是持续攻防战，本方案做的是大幅提高对方的检测成本
2. **灰度上线**：先在 3-5 个号上跑 1 周，稳定后再全量
3. **定期维护**：`fingerprint_manager.py` 里的 Chrome 版本范围（121-126）需要每隔几个月更新跟进主流版本
4. **数据目录**：`/app/data/`（指纹、会话文件所在）必须挂载为 Docker 数据卷，否则容器重建即"指纹跳变"
