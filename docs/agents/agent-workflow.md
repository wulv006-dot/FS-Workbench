# FS 开工与执行

<a name="fs-principles"></a>

## FS 核心原则（2026-11-03 创建者确认）

FS 由创建者吴律统一掌控，是以 Hermes 为智能中枢的 AI 驱动运营决策与执行系统。以实现吴律的最终目标为目的，判断限制是否服务于这一目标及系统定位；发现不符合的规则，应依据吴律的授权和实际证据提出或实施针对性调整，不为保留历史限制而阻碍目标。

在吴律明确授予的权限、业务目标与规则范围内，Hermes 享有最高执行及决策权，统一感知业务、积累知识、自主分析和决策，并调用 FS 能力执行、监控及复查。吴律拥有最终管理权，可随时调整目标、授权范围与规则，监督、暂停或接管任何任务。Codex、ChatGPT 和其他协作方按同一原则执行已授权工作；系统实际能力、身份传递与生产生效以代码和验收证据为准。

各入口和任务使用统一管理、可追溯、可更新、可回退的业务知识、技能与规则；成员通过 FS 获得经授权的使用能力，并保留各自的会话和数据访问边界。本原则不自动创建凭据、扩大个人数据或成员权限，也不取消实际适用的工具与平台安全限制；具体权限或安全设置的变化按吴律授权范围及相关合同处理。

<a name="start-work"></a>

## 重要｜开工必看

### 任务归属、Worktree 与交付（2026-11-09 用户确认）

本约定适用于所有 FS 开发任务及执行客户端；本仓库 `AGENTS.md` 是项目级开工入口，后续新会话也须读取。

- 开工先检查当前工作区绝对路径、仓库 origin、分支、未提交变更，以及本会话对应的任务和负责人，确认当前目录属于本任务后再操作。
- 继续旧任务时沿用原会话及本任务原有分支、Worktree，保留未完成工作；不得默认复用另一个任务的开发目录。
- 新开发任务由执行者自动获取最新 `origin/main`，记录实际基线提交，从该基线建立本任务独立分支和 Worktree。Codex 优先使用原生 Worktree 能力；DSH 使用独立明确的任务目录，不放入 Codex 管理或清理的临时目录。每个任务只有一个负责人。
- DSH 的任务目录与分支固定为 `D:/FS/DSH-worktrees/<task-id>` 和 `dsh/<task-id>`；创建前先查是否已有同任务分支及 Worktree，存在则沿用并核对 HEAD，不另起副本、不为对齐基线重置旧任务。
- 每个开发 Worktree 接入自己的 CodeGraph 索引。首次使用由执行者自动初始化，已有索引先核对项目路径和状态；每次查询显式传入本任务 Worktree 的绝对路径 `projectPath`。索引、缓存及临时锁只留本机并被 Git 忽略，不跨任务复制索引数据库；索引故障按下文规则处理，不阻断可继续的源码分析。
- 初始化新索引前，若正式 clone 存在本机 `codegraph.json`，仅在任务配置缺失时复用其排除配置并核对已被 Git 忽略；已有索引先查 `status`，必要时同步。MCP 接入以本会话实际 `codegraph_explore(projectPath=<本任务绝对路径>)` 返回源码及行号为准，仅配置存在或命令行查询成功不能代替该实调。
- 不覆盖、清理或提交其他 Agent 的未提交代码，不为准备新任务而重置其他任务的分支或工作区；Git 与共享发布操作继续串行。
- 完成后按照 `docs/ops/HOTFIX.md` 及实际仓库规则提交 PR，明确报告提交 SHA、PR、检查结果、合并状态和部署状态。未检查、未合并或未部署须如实标明；提交或合并不代表已部署，也不新增生产发布授权。

<a name="skill-selection"></a>

### 开工技能与技能选择（2026-11-16）

开发任务的开工与收尾清单见 `fs-task` 技能（`.agents/skills/fs-task/` 供 Codex，`.claude/skills/fs-task/` 供 Claude，两份保持同内容）。它只按顺序落实本节与 HOTFIX 的既有规则，不新增规则；冲突以仓库根 [AGENTS.md](../../AGENTS.md) 和 `docs/ops/HOTFIX.md` 为准。开始改仓库前先用它。

技能按描述自动匹配，匹配不稳时按下表手动点名（Claude 侧技能名带 `mattpocock-skills:` 前缀）：

| 场景 | 用 |
|---|---|
| 开工、提交、开 PR、交付报告 | `fs-task` |
| 报错、异常、变慢 | `diagnosing-bugs` |
| 有明确输入输出的逻辑（如定价、计算） | `tdd` |
| FC 定价规则变更、迁移后复盘、自动改价故障 | `fc-pricing-change-review`（`.agents/skills/` 供 Codex，`.claude/skills/` 供 Claude，两份同内容） |
| PR 前审查 | `code-review`，需要精简时加 `simplify` |
| 涉及登录、凭据、writer、权限 | `security-review` |
| 合并或 rebase 冲突 | `resolving-merge-conflicts` |
| 术语、ADR | `domain-modeling` |
| FC27 月报 | `fc27-monthly-report` |
| 核对经营数据口径 | `data:validate-data` |
| 活动页的发券、登录态、结账交接、页面追踪、优惠码/券归因，及发布到 187 与线上验收 | `fc-activity-wiring`（`.claude/skills/` 供 Claude，`.agents/skills/` 供 Codex，两份同内容） |
| 活动页、落地页设计（含发布到主站 MMOEXP 的跨域页面） | `design:design-critique`、`design:accessibility-review`、`design:ux-copy`，交接时用 `design:design-handoff` |

活动页的内容与结构以 `docs/standards/fc27/DESIGN-TEMPLATE.md` 和对应活动合同（如 `docs/planning/activity-center-v3/`）为准；FS 工作台内部界面以 `ui-system/README.md` 为准，两者不混用样式。设计技能只提供评审与写作辅助，不改变上述文档、业务规则、跨域接入合同或发布流程；跨域页面的手机宽度、主题和实际嵌入效果仍须在真实入口核对。营销类等其余插件技能与本项目开发无关，不主动使用。

<a name="codegraph"></a>

### CodeGraph 与源码核对

在 FS 项目开始功能开发、修复或重构任务时，先调用 CodeGraph MCP 的 `codegraph_explore`，查询相关模块、调用关系和影响范围，再回看当前源码、测试与实际发布映射后实施修改。查询限于本任务 FS Worktree，每次显式指定其绝对路径 `projectPath`；代码图只提供导航，不证明生产版本、权限或业务运行状态。

CodeGraph 是本地程序与 MCP 服务，不是 Skill。工具不可用或索引过期时说明原因，使用源码检索继续，不为工具故障阻塞开发；索引和临时锁文件留在本地，不入库。纯文案、简单配置或范围明确的微小改动不必全仓建图。原业务规则继续适用。

CodeGraph 只覆盖本任务 Worktree 当前磁盘上的已索引源码，不含 git 历史、其他分支或 PR；这些用 `git log/blame/show`、`git grep <pat> origin/main` 或 `gh`。配置与 `docs/` 仍用 Grep/Read。

<a name="execution"></a>

# AI 执行入口

2026-11-10用户补充：历史UNKNOWN有后续有效真实现态覆盖后退出当前阻断，保留旧记录而不冒充旧POST成功；仍在途、现态缺失或新UNKNOWN才沿原ID核验。覆盖绑定原商品身份、真实Admin现态和时间及原任务已结束的证据，理论预览不算。未来新写继续当前来源、CAS和原写后核验，不让历史记录反复卡住新逻辑。

先读 [全仓唯一执行规则](../../docs/ops/HOTFIX.md)，据用户当前任务连续完成已授权工作。不要从其它快照重建逐SHA审批、双人Approve或全套QA前置。

只再读本任务受影响的源码、模块合同、[负责人](../../docs/collaboration/OWNERS.json)及[来源映射](../../docs/collaboration/SOURCE-MAP.json)。它们提供范围和事实，不另设全局流程。Git窗口及发布串行。

[旧版记录](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/AGENTS.md)保留在Git历史，旧服务器故障、未上传和审批状态不代表当前事实。平台拒绝仍独立有效，不能以本文件绕过。

FC27 和绿茵计划的产品、技术、接口及交付文档使用 [统一标准与模板](../../docs/standards/fc27/README.md)。这是内容组织约定，按任务规模选用；不改变 HOTFIX 执行流程、模块合同、业务参数或授权，不导入额外审批。

<a name="rule-layers"></a>

## 全局偏好与项目规则分层

通用偏好参考 [全局指令稿](../../docs/planning/codex-instructions-20261021/GLOBAL-INSTRUCTIONS.md)，适用范围、冲突情境与核验见 [说明](../../docs/planning/codex-instructions-20261021/README.md) 和 [核验记录](../../docs/planning/codex-instructions-20261021/AUDIT.md)。这是可复用文本与记录，仓库链接不自动安装用户全局配置。

全局约定协作方式，模块合同约定业务边界，具体执行仍只见 HOTFIX。按任务读取相关资料、复用有效证据；旧逐 SHA/双人审批与全套前置不能由历史快照恢复。文档任务以内容和读回验收，不触发业务采集或生产发布；UI/来源/价格等已确认业务特例保持。

<a name="agent-skills"></a>

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`wulv006-dot/FS-Workbench`) and are driven with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles keep their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`); wayfinding uses `wayfinder:map` plus `wayfinder:research` / `wayfinder:prototype` / `wayfinder:grilling` / `wayfinder:task`. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context layout: the root `GLOSSARY-MAP.md` points to per-context `GLOSSARY.md` files, with system-wide ADRs in `docs/adr/`. See `docs/agents/domain.md`.
