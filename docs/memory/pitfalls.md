# 已知问题

- **2026-11-25，Order 会话被顶掉。** 同一账号重新登录会顶掉已有会话，当日独立登录试验中断了 P0 写价。排查时先检查共享会话的原有回执和现场状态。[事故与规则](../planning/order-http-access-20261125/DELIVERY.md#事故与规则)
- **2026-11-26，Order 验证器白名单误删。** 会话续期被拒，白名单恢复后仍有两轮 P0 受阻。修复后的会话服务在登录被明确拒绝时冷却 30 分钟，再自动重试一次。[修复与回归](https://github.com/wulv006-dot/FS-Workbench/commit/5194dfe34c713b17377a3b08d81a8edc9806ebfe)
- **2026-11-26，AGENTS.md 加载截断。** T3 中的 Antigravity 实测只加载约前 25 KB，31,491 字节的旧文件末尾规则缺失。Codex 默认项目文档预算为 32 KiB，文件过长也会截断。[瘦身与 CI 变更](https://github.com/wulv006-dot/FS-Workbench/pull/1386)
