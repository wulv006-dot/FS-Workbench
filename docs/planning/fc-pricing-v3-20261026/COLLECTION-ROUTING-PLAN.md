# ArabUT 原入口接线计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，当前会话逐项实施，最终独立审查。

**Goal:** 完成 P3 可关闭候选，187 按原 run 消费183同轮 ArabUT，默认关闭。

**Architecture:** 复用现有 SQLite、受限 SSH 和公开报价 adapter；只接 sources.py 两个 ArabUT 调用点。未配置/off、原 local 钉住及 shadow 保留原分支；consume 不暗中并发直采或失败后换出口。P4 已完成的独立影子驱动继续承担 shadow 采集，本接线不新增影子轮询器。

**Tech Stack:** Python3.9 标准库、SQLite、现有 SSH 协议，无新依赖。

**Spec:** 用户最新施工包01 P3、03验收及本目录 COLLECTION-TRANSPORT.md。

## Global Constraints

- 900秒 TTL、300秒同批跨度；原时间、run、截止和回执不可刷新。
- 原财务、Saudi PC缺价、原writer、UNKNOWN、RPG不变。
- 默认 off；本阶段不部署原业务文件、不启用生产消费。
- 183默认隔离Linux验证；完整原FC相关回归及正式pr-fast。

## Review Focus

- 缺来源元数据的旧影子观察可补ACK，但不得冒充完整原报价。
- 同一run重入、SSH中断、丢ACK不得另建任务或重复GET。
- 关闭/改代发生在途时，不可穿透最新消费开关。
- 其他排队任务不得被当前来源调用顺手领取。
- PC-only/来源不需要/显式提供旧结果时不得增加外站请求。

### Task1：报价字段兼容

Files: source/fc_collection/contracts.py、public_sources.py；tests/test_collection_routing.py。

- [ ] 先测试原SAR金额、priceVersion类型、pricedAt、完整旧字段及无metadata拒绝消费。
- [ ] 增加可选且严格校验的source_metadata；旧观察仍可验签/补ACK，消费要求完整Console组。
- [ ] 运行定向合同与来源测试。

### Task2：187候选接线

Files: source/fc_collection/client.py、coordinator.py、source/fc_pricing_v3/sources.py、deploy/build_collection_node.py、test_collection_183.py；相关测试。

- [ ] 先测试off/shadow/local钉住、同run重入、过期、在途关闭、目标任务领取、失败不隐式直采。
- [ ] 从collect_context传最小parent上下文，保持240秒原子进程上限，持久化首次派发截止，不重入延长。
- [ ] root私有路由文件缺省off；consume仅匹配既存协调策略/代际，复用SSH健康/manifest/原ACK；只领取本job。
- [ ] 更新角色导出与Linux白名单，不向183导出client或业务源。
- [ ] 相关测试、全FC回归、183 Python3.9隔离测试、知识收尾、独立审查、正式CI；沿现有授权PR合并，不把合并当生产发布。

## Execution ledger

- BASE 17c00bf1ddbde93bcf21b5364ecde896880ec0bb；工作树初始干净。
- Ruling: P3只做可关闭候选，P6本机接替仍待专项验证；不会用未验证fallback启用生产。
