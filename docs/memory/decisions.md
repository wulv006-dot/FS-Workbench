# 协作决策

- **2026-11-26，正式 clone 只做快进同步。** PR 合并且部署验收完成后，进入正式 clone 的干净 `main` 快进到 `origin/main`。工作区有改动或分叉时停止并报告。此规则取代旧的「不改正式 clone 的 main」说法。[执行步骤](../../.agents/skills/fs-task/SKILL.md#收尾)
- **2026-11-26，共用项目规则和技能源。** 核心规则置于 AGENTS.md 前部，场景细节按需读取。Claude 通过薄桥接发现同一入口，技能只编辑 `.agents/skills/`，Claude 副本由同步脚本生成。[入口与同步约定](../../AGENTS.md) · [瘦身与 CI 变更](https://github.com/wulv006-dot/FS-Workbench/pull/1386)
- **2026-11-26，确认公开仓库口径。** FS-Workbench 对外按公开源码仓库表述。早期记录中的私库指当时的状态与披露授权。[全仓执行规则](../ops/HOTFIX.md)
