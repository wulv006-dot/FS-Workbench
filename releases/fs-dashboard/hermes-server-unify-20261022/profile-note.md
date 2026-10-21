## 服务器普通聊天的现行业务口径（2026-10-22）

飞书和服务器客户端读取同一 `/profile`；`terminal.backend=local` 表示服务器容器。普通聊天已注册 `fs_get_data_catalog`、`fs_query_native_statistics`、`fs_query_es_order_structure`、`fs_query_discount_analysis`、`fs_query_product_orders`；需要时通过工具搜索发现后调用，不沿用旧会话“未注册”的结论。

当前业务基准入口为 `/fs-source/business-baseline.md`。经营总盘用 Admin 原生统计优先，Order 补缺和提供同期间参考利润率；`fs_query_native_statistics` 中的 Admin 原生统计不能称为 ES 明细，只有 ES 工具返回的结构才按 ES 标注。不要因 Order 总额与 Admin 不同就互相覆盖或拒绝有效参考值。

Admin 缺利润时，允许用对应期间 Admin 销售额 USD × Order 参考利润率 / 100，明确标为经营估算、非财务实结；缺失率保持未知。保留来源、范围、时区、捕获时间、完整性和原失败，闭日数据的后续订单状态仍可变化。新一轮任务先读现行业务基准，历史报告和对话中的旧规则不覆盖它。

巡检 ID `0018aa8c8439` 在本服务器主配置中运行，北京时间每日 23/02/05/08；旧独立配置的同 ID 已暂停。日程以实际 cron 读回为准。现有自动化、派单和自修白名单保持，不能重新启用旧配置形成双跑。
