"""统一浏览器入口；云端隔离执行器的后台会话使用独立 Chrome 和全局身份。

MADDEN_ISOLATED_BACKEND=1 仅改变 session()：每次申请原共享身份，结束关闭
临时 Chrome。fresh() 仍只连接竞品 Chrome；以下 CDP 兼容行为供旧入口使用。

为什么要有这一层
----------------
本机跑法是「自己起一个 Chromium」（`launch` / `launch_persistent_context`），
但云端那台 CentOS 7 已 EOL，装不了 Chromium 及其系统库。
服务器上已经有一套跑通的浏览器（容器内的 google-chrome-stable，
通过 `--remote-debugging-port` 暴露 CDP）。

所以加一层开关：

    MADDEN_CDP_ENDPOINT=http://127.0.0.1:9232   设置了就连容器里的 Chrome
    不设置                                      完全沿用本机行为（一个字节都不变）

两种会话
--------
- `fresh()`   —— 干净会话，不需要登录态（采集竞品价）。
                CDP 下用 `browser.new_context()` 新建独立 context，用完直接关掉，
                **不污染共享 Chrome 的 profile**，也不会把登录态带去竞品站。
- `session()` —— 持久会话，需要后台登录态（采成本、写价）。
                CDP 下取 `browser.contexts[0]`，也就是容器 Chrome 启动时
                `--user-data-dir` 指向的那个 profile —— 登录态就在里面。

⚠️ CDP 模式下**绝不能关掉共享的 context 或 browser**：
   那台 Chrome 是容器常驻的，关掉等于把浏览器的会话（含登录态）弄没，
   而且会让容器重启策略误判。`session()` 返回的 closer 只关"本次打开的标签页"。

⚠️ 防标签页泄漏：CDP 下每次 `new_page()` 都会在常驻 Chrome 里开一个新标签，
   如果只断开连接而不关页面，标签会越积越多。`session()` 会记录基线，
   closer 只清理本次新增的那些。

本文件不含任何凭据。
"""
from __future__ import annotations

import os

CDP_ENDPOINT = os.environ.get("MADDEN_CDP_ENDPOINT") or ""

DEFAULT_VIEWPORT = {"width": 1500, "height": 950}


def using_cdp() -> bool:
    """当前是不是走 CDP（容器内的 Chrome）。"""
    return bool(CDP_ENDPOINT)


def _kwargs(viewport, locale):
    opts = {"viewport": dict(viewport or DEFAULT_VIEWPORT)}
    if locale:
        opts["locale"] = locale
    return opts


def fresh(pw, *, headless: bool = True, viewport: dict | None = None,
          locale: str | None = None, args: list[str] | None = None):
    """干净会话（无需登录态）。返回 `(context, closer)`。"""
    opts = _kwargs(viewport, locale)
    if CDP_ENDPOINT:
        browser = pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx = browser.new_context(**opts)
        # 只关这个临时 context；常驻 browser 不动
        return ctx, ctx.close

    browser = pw.chromium.launch(headless=headless, args=list(args or []))
    ctx = browser.new_context(**opts)

    def closer() -> None:
        try:
            ctx.close()
        finally:
            browser.close()

    return ctx, closer


def session(pw, profile, *, headless: bool = True, viewport: dict | None = None,
            locale: str | None = None, args: list[str] | None = None):
    """带持久登录态的会话。返回 `(context, closer)`。

    `profile` 只在**本机**路径下用到（那是 `launch_persistent_context` 的目录）；
    CDP 路径下 profile 由容器 Chrome 的 `--user-data-dir` 决定，这里忽略。
    """
    opts = _kwargs(viewport, locale)
    if os.environ.get('MADDEN_ISOLATED_BACKEND') == '1':
        # Same shared Order identity, separate short-lived Chrome and worker cgroup.
        import fs_order_client
        browser = pw.chromium.launch(
            executable_path='/opt/google/chrome/chrome', headless=True,
            args=list(dict.fromkeys([*(args or []), '--no-sandbox', '--disable-dev-shm-usage'])))
        try:
            ctx = browser.new_context(**opts)
            fs_order_client.apply(ctx)
        except BaseException:
            browser.close()
            raise

        def closer():
            try:
                ctx.close()
            finally:
                browser.close()
        return ctx, closer
    if CDP_ENDPOINT:
        browser = pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError(
                f"CDP {CDP_ENDPOINT} 上没有任何 context；"
                "容器里的 Chrome 是否带了 --user-data-dir 启动？")
        ctx = contexts[0]
        baseline = set(ctx.pages)

        def closer() -> None:
            for page in list(ctx.pages):
                if page in baseline:
                    continue
                try:
                    page.close()
                except Exception:  # noqa: BLE001 - 页面已关闭等情况忽略
                    pass

        return ctx, closer

    ctx = pw.chromium.launch_persistent_context(
        str(profile), headless=headless, args=list(args or []), **opts)
    return ctx, ctx.close
