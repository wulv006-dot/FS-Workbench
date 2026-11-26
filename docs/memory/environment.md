# 环境事实

- FS-Workbench 是公开源码仓库，正式 Windows clone 为 `D:/codex/FC27/codegraph-sources/FS-Workbench`。新开发使用任务专属 Worktree。[仓库说明](../../README.md) · [开工规则](../agents/agent-workflow.md#start-work)
- Order 后台只有 `wulv`、`chenchao` 免谷歌验证器。187 上由 `fs-order-session` 使用 `wulv` 维持共享会话，其他消费者沿用 `fs_order_client` / `order_http`。[会话规则](../agents/backend-access.md#order-single-session) · [2026-11-25 交付记录](../planning/order-http-access-20261125/DELIVERY.md#事故与规则)
