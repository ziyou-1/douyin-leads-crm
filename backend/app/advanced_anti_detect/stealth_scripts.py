"""
深度指纹伪装 JS 注入脚本
=======================

【核心思想】在页面加载前（addInitScript）注入 JS，覆盖浏览器暴露的指纹属性，
让抖音的检测脚本读到的是我们伪造的值。必须在页面脚本执行前完成注入。

【用法】
    script = get_stealth_script(profile)    # profile 来自 FingerprintManager
    await context.add_init_script(script)  # 必须在 new_page() 之前！

【本脚本防的检测手段】（每段JS都有对应注释说明原理）
1. navigator.webdriver = true  → 自动化最露馅的标志，一行代码就能识破
2. Canvas 指纹                → 不同硬件渲染差异构成唯一指纹
3. WebRTC 本地IP泄露          → 即使流量走了代理，仍可能暴露真实局域网IP
4. AudioContext 指纹          → 音频处理的硬件差异指纹
5. WebGL 显卡信息             → 虚拟机的 llvmpipe/SwiftShader 直接暴露无显卡环境
6. Navigator 属性             → Playwright 默认空插件列表 = 一眼假
7. window.chrome 缺失         → 真Chrome必有此对象，自动化环境没有
8. Permissions API            → 自动化环境的权限查询行为异常
"""

try:
    from .fingerprint_manager import BrowserProfile
except ImportError:
    # 支持把本文件单独复制出去用（不作为包导入时）
    from fingerprint_manager import BrowserProfile


def get_stealth_script(profile: BrowserProfile) -> str:
    """
    根据账号指纹配置生成定制化注入脚本。

    【为什么每个账号的脚本不一样？】
    脚本里的 Canvas 噪声种子、显卡型号、CPU 核数等值都来自该账号的固定
    指纹 → 每个号注入后呈现的指纹互不相同（像不同的电脑），且同一个号
    每次注入的结果完全一致（像同一台电脑）。

    【替换方式】用 __占位符__ + replace（不用 str.format，
    因为 JS 代码里有大量花括号会和 format 语法冲突）。
    """
    script = STEALTH_INJECTION_SCRIPT
    replacements = {
        "__CANVAS_SEED__": str(profile.canvas_noise_seed),
        "__AUDIO_HASH__": profile.audio_context_hash,
        "__WEBGL_VENDOR__": profile.webgl_vendor.replace("'", "\\'"),
        "__WEBGL_RENDERER__": profile.webgl_renderer.replace("'", "\\'"),
        "__PLATFORM__": profile.platform,
        "__LANGUAGE__": profile.language,
        "__CPU_CORES__": str(profile.hardware_concurrency),
        "__DEVICE_MEMORY__": str(profile.device_memory),
        "__SCREEN_W__": str(profile.screen_width),
        "__SCREEN_H__": str(profile.screen_height),
    }
    for key, value in replacements.items():
        script = script.replace(key, value)
    return script


# 完整的 JS 注入脚本（占位符由 get_stealth_script 按账号指纹填充）
STEALTH_INJECTION_SCRIPT = r"""
(() => {
    // ========== 0. 移除 webdriver 标志（最重要！） ==========
    // 【防】navigator.webdriver —— Playwright/Puppeteer/Selenium 默认为 true，
    // 检测方一行代码 if(navigator.webdriver) 就能识破所有自动化工具
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // ========== 1. Navigator 属性全覆盖 ==========
    // 【防】指纹脚本读取 plugins/mimeTypes（Playwright默认为空=异常）、
    // hardwareConcurrency（服务器真实核数如64核，与宣称的家用配置矛盾）等
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => __CPU_CORES__ });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => __DEVICE_MEMORY__ });
    Object.defineProperty(navigator, 'platform', { get: () => '__PLATFORM__' });
    // languages 必须返回数组且第一项与 Accept-Language 请求头一致
    Object.defineProperty(navigator, 'languages', { get: () => ['__LANGUAGE__', 'zh', 'en'] });
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 }); // 桌面端无触摸

    // 模拟 Chrome 内置插件（真浏览器有 PDF Viewer 等内置插件，空列表=假）
    const fakePlugins = [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer',
          description: 'Portable Document Format', length: 1 },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
          description: '', length: 1 },
        { name: 'Native Client', filename: 'internal-nacl-plugin',
          description: '', length: 2 },
    ];
    fakePlugins.item = (i) => fakePlugins[i];
    fakePlugins.namedItem = (n) => fakePlugins.find(p => p.name === n);
    fakePlugins.refresh = () => {};
    Object.defineProperty(navigator, 'plugins', { get: () => fakePlugins });

    // mimeTypes 与 plugins 匹配（两者不一致也是破绽）
    const fakeMimes = [
        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
    ];
    fakeMimes.item = (i) => fakeMimes[i];
    fakeMimes.namedItem = (t) => fakeMimes.find(m => m.type === t);
    Object.defineProperty(navigator, 'mimeTypes', { get: () => fakeMimes });

    // ========== 2. window.chrome 对象模拟 ==========
    // 【防】检测 window.chrome / chrome.runtime —— 真Chrome必有此对象，
    // 自动化环境缺失；部分检测还会调 chrome.runtime.sendMessage 探测
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
        window.chrome.runtime = { connect: function(){}, sendMessage: function(){} };
    }

    // ========== 3. Canvas 指纹噪声（基于固定种子） ==========
    // 【防】Canvas指纹 —— 检测脚本在canvas上画图形再哈希像素数据，
    // 不同显卡渲染存在微小差异，构成唯一指纹。
    // 【对策】注入±1亮度的噪声改变哈希值。种子来自账号固定指纹 →
    // 同一号噪声永远一致。【切忌用Math.random】：随机噪声会导致
    // "同一账号每次指纹都不同"，反而更像自动化工具！
    const SEED = __CANVAS_SEED__;
    function mulberry32(seed) {
        return function() {
            seed |= 0; seed = seed + 0x6D2B79F5 | 0;
            let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
            t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
            return ((t ^ t >>> 14) >>> 0) / 4294967296;
        };
    }
    const canvasRng = mulberry32(SEED);
    function addNoise(data) {
        for (let i = 0; i < data.length; i += 4) {
            const n = (canvasRng() - 0.5) * 2;  // ±1像素亮度，肉眼不可见
            data[i]   = Math.min(255, Math.max(0, data[i] + n));
            data[i+1] = Math.min(255, Math.max(0, data[i+1] + n));
            data[i+2] = Math.min(255, Math.max(0, data[i+2] + n));
            // Alpha通道不动
        }
    }
    // 覆盖 getImageData（直接读像素的最常用采集方式）
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function() {
        const img = origGetImageData.apply(this, arguments);
        addNoise(img.data);
        return img;
    };
    // 覆盖 toDataURL（另一种常用采集方式）
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function() {
        const ctx = this.getContext('2d');
        if (ctx && this.width > 0 && this.height > 0) {
            const img = origGetImageData.call(ctx, 0, 0, this.width, this.height);
            addNoise(img.data);
            ctx.putImageData(img, 0, 0);
        }
        return origToDataURL.apply(this, arguments);
    };

    // ========== 4. AudioContext 指纹伪装 ==========
    // 【防】音频指纹 —— OfflineAudioContext 渲染结果因音频硬件差异而唯一
    let audioSeed = 0;
    const AUDIO_HASH = '__AUDIO_HASH__';
    for (let i = 0; i < AUDIO_HASH.length; i++) {
        audioSeed = ((audioSeed << 5) - audioSeed) + AUDIO_HASH.charCodeAt(i);
        audioSeed |= 0;
    }
    if (window.OfflineAudioContext) {
        const origRender = OfflineAudioContext.prototype.startRendering;
        OfflineAudioContext.prototype.startRendering = function() {
            return origRender.apply(this, arguments).then((buffer) => {
                const rng = mulberry32(audioSeed);  // 种子固定 → 同号噪声一致
                for (let ch = 0; ch < buffer.numberOfChannels; ch++) {
                    const data = buffer.getChannelData(ch);
                    for (let i = 0; i < data.length; i++) {
                        data[i] += (rng() - 0.5) * 0.0000002;  // 极微噪声改变哈希
                    }
                }
                return buffer;
            });
        };
    }

    // ========== 5. WebGL 显卡信息覆盖 ==========
    // 【防】WEBGL_debug_renderer_info 读取真实显卡 —— 虚拟机/无头环境返回
    // "llvmpipe"/"SwiftShader"（软件渲染），直接暴露无显卡的机房环境
    const UNMASKED_VENDOR = 0x9245, UNMASKED_RENDERER = 0x9246;
    function hookGetParam(proto) {
        const orig = proto.getParameter;
        proto.getParameter = function(p) {
            if (p === UNMASKED_VENDOR) return '__WEBGL_VENDOR__';
            if (p === UNMASKED_RENDERER) return '__WEBGL_RENDERER__';
            return orig.apply(this, arguments);
        };
    }
    if (window.WebGLRenderingContext) hookGetParam(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) hookGetParam(WebGL2RenderingContext.prototype);

    // ========== 6. WebRTC 本地IP泄露防护 ==========
    // 【防】RTCPeerConnection 的 ICE candidate 泄露真实IP ——
    // 即使HTTP流量走了代理，WebRTC仍可能直接上报本机公网/内网IP导致穿帮
    const OrigPC = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    if (OrigPC) {
        window.RTCPeerConnection = function(config, constraints) {
            const pc = new OrigPC(config, constraints);
            // 拦截 icecandidate 事件：阻止携带真实IP的candidate回调给页面脚本
            pc.addEventListener('icecandidate', (e) => {
                if (e.candidate && e.candidate.candidate) {
                    const c = e.candidate.candidate;
                    // srflx(公网反射)/typ host(本机网卡) 的candidate都不允许泄露
                    if (c.indexOf('srflx') !== -1 || c.indexOf('typ host') !== -1) {
                        e.stopImmediatePropagation();
                    }
                }
            });
            return pc;
        };
        window.RTCPeerConnection.prototype = OrigPC.prototype; // 保持原型链
    }

    // ========== 7. Permissions API 伪装 ==========
    // 【防】permissions.query 行为差异 —— 普通浏览器 notifications 返回
    // 'default'（未询问），无头自动化环境常返回 'denied' 或直接抛异常
    if (navigator.permissions && navigator.permissions.query) {
        const origQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = function(desc) {
            if (desc.name === 'notifications' || desc.name === 'push') {
                return Promise.resolve({ state: 'default', onchange: null });
            }
            return origQuery(desc);
        };
    }

    // ========== 8. Screen 属性 ==========
    // 【防】screen 分辨率与账号宣称指纹不符（如1920x1080的号跑在4K服务器上）
    Object.defineProperty(screen, 'width', { get: () => __SCREEN_W__ });
    Object.defineProperty(screen, 'height', { get: () => __SCREEN_H__ });
    Object.defineProperty(screen, 'availWidth', { get: () => __SCREEN_W__ });
    Object.defineProperty(screen, 'availHeight', { get: () => __SCREEN_H__ - 40 }); // 减任务栏
    Object.defineProperty(screen, 'colorDepth', { get: () => 24 });

    console.debug('[Stealth] 深度指纹伪装已注入');
})();
"""


async def apply_stealth_scripts(context, profile: BrowserProfile) -> None:
    """
    一键应用伪装脚本到 BrowserContext（快捷入口）。

    【注意】必须在 new_page() 之前调用——add_init_script 只对
    之后创建的页面生效，晚了就注不进去了。
    """
    script = get_stealth_script(profile)
    await context.add_init_script(script)
    print(f"[伪装] 已注入深度指纹伪装脚本（账号: {profile.account_id}）")
