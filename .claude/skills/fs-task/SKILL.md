---
name: fs-task
description: FS-Workbench 开发任务的开工与收尾流程。开始功能开发、修复、重构、改文档或配置并需要改仓库前使用；也用于提交、开 PR、检查 CI 和写交付报告。只回答问题、查历史数字、不改仓库时不触发。
---

# FS 任务：开工与收尾

从仓库根 [AGENTS.md](AGENTS.md) 进入，按[任务归属、Worktree 与交付](docs/agents/agent-workflow.md#start-work)、[CodeGraph 与源码核对](docs/agents/agent-workflow.md#codegraph)及 [HOTFIX](docs/ops/HOTFIX.md) 执行。本技能的跨目录链接从仓库根解析。

## 开工

1. **定任务**：用一句话写明要恢复或新增的行为、直接相关模块、已授权范围和唯一负责人。取一个 `task-id`，格式 `<主题>-<YYYYMMDD>`。
2. **看现场**：报告当前绝对路径、`git remote -v`、当前分支、`git status`。正式 clone（`D:/codex/FC27/codegraph-sources/FS-Workbench`）只用于收尾快进同步，开发和提交在任务 Worktree 中完成。
3. **旧任务还是新任务**：先 `git worktree list` 和 `git branch --list "*<关键词>*"`。已有同任务分支或 Worktree 就沿用，核对 HEAD，保留未提交内容；不借用别的任务目录，不为对齐基线重置旧分支。
4. **新任务建 Worktree**：`git fetch origin main`，记下 `origin/main` 的 SHA 作为基线，再建：
   - Claude：`git worktree add -b claude/<task-id> D:/FS/claude-worktrees/<task-id> origin/main`
   - Codex：优先用原生 Worktree 能力。
   - Antigravity：优先用 T3 原生 Worktree。否则使用 `D:/FS/agy-worktrees/<task-id>`，分支 `agy/<task-id>`。
   - DSH：`D:/FS/DSH-worktrees/<task-id>`，分支 `dsh/<task-id>`。
5. **CodeGraph**：纯文案、简单配置、范围明确的微小改动跳过。其余先 `codegraph_explore`，且每次显式传本任务 Worktree 的绝对路径 `projectPath`；必须有一次实调返回源码与行号才算接入（配置存在或命令行成功都不算）。无索引就在该 Worktree 初始化，不复制其他任务的索引库；初始化前先确认 `.codegraph/` 已被 Git 忽略。工具故障或索引过期时说明原因，改用源码检索继续。图只用于导航，不证明生产版本、权限或业务状态。
6. **读合同**：按任务读取受影响的合同。FC 定价看[定价合同入口](docs/agents/fc-pricing.md#pricing-contracts)，其余看对应模块合同、`docs/collaboration/OWNERS.json` 和 `SOURCE-MAP.json`。
7. **实施**：最小改动，修到根因和必要调用链；只运行相关回归；不碰其他 Agent 的未提交内容。

## 收尾

1. 提交前核对改动只含本任务文件；未获用户要求不 commit、不 push。
2. 按 HOTFIX 提交 PR，复用 `pr-fast`；用所在客户端的 PR 工具或后台轮询等 CI 终态。auto-merge 只对用户逐个授权的低风险 PR 启用。
3. PR 合并且部署验收均完成后，进入正式 clone，确认当前为 `main` 且工作区干净，再执行 `git fetch origin && git merge --ff-only origin/main`。只允许快进，不在正式 clone 开发、提交、reset、rebase 或强推，也不覆盖未提交改动。工作区有改动或无法快进时停止并报告。
4. 交付报告固定写这些，缺哪项就如实写「未检查／未合并／未部署」：
   - 基线 SHA 和提交 SHA
   - PR 链接
   - 检查结果及其覆盖范围
   - 合并状态
   - 部署状态
   - 真实入口读回结果；未做就写 unknown 或部分成功，不宣布成功
5. merge、CI 绿、HTTP 200 都不是终点，也不授予生产发布权限。涉及知识或业务规则的变更，按 `docs/planning/knowledge-layering-20261023/CLOSEOUT.md` 的统一入口收尾。
