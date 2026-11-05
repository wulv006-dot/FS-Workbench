# FS 游戏情报台

目标是先回答“今天哪些游戏值得行动，以及为什么”。这是独立的新经营视图；原工作区、十栏目、资料/工具、历史、现役官方与 MMOEXP 新闻采集、静态内容自动维护继续保留。

## 源码与数据

- `web/`：原生界面、现役 FS 主题、29 游戏目录、原有 18 条 FC 原表日历。
- `web/source-model.js`：读取现役 `daily.json`、`seo-news.json`，以及补充的 `intelligence.json`、`intelligence.status.json`。相同事件选采集时间较新的记录；保留记录不续期；原表截图来源保留为说明，不伪造网址。
- `backend/discovery.py`：供 Hermes 运维编排调用的固定公开情报任务。读取宿主既有 DeepSeek 账户；Search/Fetch 结果按游戏、公告路径/版块和原文校验。无合格搜索结果时复用现役官方读取器，并保留搜索缺项。模型调用复用现役 `direct_provider`，没有新试点额度。不是向所有 Hermes 会话全局开启任意搜索或写入权限。
- `prepare_ui.py`：仅准备候选，复用现役不可变 publisher、锁、CAS、保护路径、备份和读回，不执行 apply。新增 `/dashboard/game-monitor/operations.html`；原 `/dashboard/game-monitor/index.html` 保留并增加新版入口。

Search/Fetch 使用官方端点，成功非空请求分别为 $0.75/1,000 次；模型 token 仍按现役账户计费。本次用户已明确允许这部分费用，不新增内部试点预算或额度。

来源：<https://api-docs.deepseek.com/guides/search/>。发布日、事件日、采集时间分别保留。官方域名内的玩家帖子不是官方公告；Steam 必须匹配已登记应用公告路径。未核实来源不作为官方事件发布。业务建议和官方事实分开，不触发价格、订单、活动或消息 writer。

## 更新与范围

补充任务模板为每小时运行、数据有效期 4 小时；页面每分钟重读同源数据。原周度采集周期不变。`--publish` 才原子更新新增数据文件，失败保留原快照并更新状态；默认命令仅返回公开采集批次。模型、日期、引文、游戏归属沿 `news-weekly-schedule-20261016/source/game_intelligence.py` 的既有合同。

本轮首先接回情报与行动页。竞品行情和需求信号尚未内嵌现役专用接口，页面保留原金币控制台、经营分析和资料工具入口，不显示模拟实时价或模拟趋势。钉钉只预览文案；本轮不启用发送。

## 构建和相关检查

在仓库根目录：

```powershell
python ui-system/modules/game-monitor/build.py --output <候选目录>/operations.html
python -m unittest discover -s ui-system/modules/game-monitor/tests -p "test_*.py" -v
node ui-system/modules/game-monitor/tests/source-model.cjs
```

构建产物是单 HTML，复用 `ui-system/adapters/fs-theme.js`。浏览器检查使用宿主已装的 Playwright，`node tests/browser.cjs <包含 operations.html 和现役公开 daily.json 的目录>`。该检查的旧工作区路由为测试替身，不证明生产原页面视觉或自然周期。

`tools/pr_fast.py` 增加专用 `fs-game-monitor` 组，运行本模块 Python/Node 回归；不新增或关闭 workflow。

## 上线候选与回退

当前只允许准备清单，不把本 README 当上线授权：

1. 核当前活动旧页面、原 publication 适配器和共享发布清单；任一漂移先对账。
2. 现场片段含 CRLF，原 `publication.blocks` 只认 LF，已复现准备失败；本批在现役适配器只加 `\r?`，不改最终冻结 publisher。上传已审查的单 HTML、准备器与该适配器候选到临时目录，调用 `prepare_ui.py --asset ... --stage ... --adapter .../publication.py`。准备器只接受固定源码摘要并调用原 publisher 的 inspect，不安装适配器。
3. 正式批准后，沿同一 stage 的原 `release_workspace.py apply` 发布，再逐文件/路由读回；原 index 的纯数据维护合同仍适用。
4. 补充采集器安装目标 `/opt/fs-game-monitor-intelligence/discovery.py`；复用已有 backend 与 Hermes provider 的 Python 路径，不复制凭据。模板位于 `deploy/`，尚未安装/启用。服务端新增情报自动更新与 Hermes 原生会话工具可见性是两件事，本轮不声称已给所有会话注册搜索工具。
5. 新增 JSON 仅复用已鉴权的原数据路由。原价格、Order、账号、权限、P0 采集器及原任务不变。
6. 失败时使用本次原 publisher 备份逆序回退本批 UI 路由；新采集器和 timer 单独处理，保留数据、请求、状态与回执，不覆盖旧整包或清理原队列。

真实入口、首次手动运行、后续自然小时周期分别验收。代码与 CI 通过不代表已上线，也不代表提醒已送达。

相关回归同时修正两处旧夹具：历史候选按其来源时间验机制，运行时仍保留14日新鲜度检查；Windows 读取 UTF-8 JSON 明确指定编码。未放宽断言或生产来源校验。
