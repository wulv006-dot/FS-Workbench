# 用户分析重构与客户分层维护（2026-11-24）

现行来源从[知识条目 fs.customer.lifecycle](../../../knowledge/customer-tracking/BUYER-ID-CANDIDATES.md)进入，下表为模块合同。2026-11-25 的用户分析存档、游戏范围、维护分组名单及 Hermes 对齐已合并为 [PR #1352](https://github.com/wulv006-dot/FS-Workbench/pull/1352)，生产能力以对应发布和读回为准。

项目建立时由用户逐条确认并分三份合同施工。

| 文件 | 内容 | 施工 |
|---|---|---|
| [SHARED-CONTRACT.md](SHARED-CONTRACT.md) | 两期共用口径：游戏阶段天数、价值档、新老客、有效订单、复购 | 先合并，两期都只读它 |
| [PHASE1-USERS.md](PHASE1-USERS.md) | 用户分析页重构：新客复购队列、客户阶段、查人；Hermes/连接器切 v4 | 独立 Worktree，Codex |
| [PHASE2-MAINTENANCE.md](PHASE2-MAINTENANCE.md) | 客户维护：在现有大客维护上加阶段维护范围、规则、自动发券、效果 | 独立 Worktree，Codex，与一期并行 |

基线：`origin/main` 8275c046c570fcefbdc9fe9f22be977ce2a5a4b3。

## 背景问题

用户要证明赛季制游戏（POE2、D4 等）的新客会在 1–2 个月沉默后，于新赛季回来复购；并在 FC 中按价值和阶段对客户分层维护。改造前用户分析页有 23 个口径，多数服务于数据完整性证明而不回答经营问题，期间复购率也不随首单后的时间窗变化。

## 施工顺序

1. 本合同定稿后，在本分支实现共享模块 `customer_segments.py`、默认配置与单测，合并并发布到 `/opt/fs-hermes-fc/`。
2. 两期各从合并后的 `main` 建独立 Worktree，并行开发。共享文件归属：`catalog.json` 中 `users.*` 归一期、`customer_tracking.*` 归二期；`navigation.json` 只归二期；共享模块与配置格式两期都只读。
3. 2026-11-24 Codex 审查（16 条）已按条修入三份合同。
4. 2026-11-24 Codex Astra 整体审查（8 阻断、11 重要）及其复查（10 条部分解决、3 处新问题）已修入合同；共享模块代码问题由提交 fe353155 修复。

## 交付与发布

- 两期分别提 PR、分别审查、分别验收。发布到 187 串行，一期先上；二期发布包以一期已部署版本为基础重新生成。
- 合并、CI 通过不等于部署；部署后在真实入口读回验收。
- 自动发券是真实写入。规则矩阵和 Admin 券模板由 Claude 起草，用户确认清单后再建券；每批券经程序复核（Hermes 复核为后续任务）、管理员在待发区确认后才发放；每条规则可由管理员开启「待发区 72 小时超时自动发放」，默认关闭。
