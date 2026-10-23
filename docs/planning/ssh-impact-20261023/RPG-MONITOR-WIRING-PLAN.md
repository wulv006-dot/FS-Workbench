# RPG写入回执接入原Hermes监控：最小方案

状态：仅规划，2026-10-23现场只读核实；未改监控、未启用通知、未向群发送新消息。

## 当前事实

- 活动 `/opt/fc-ops-readonly-monitor/probe_worker.py` 的 `rpg_probe()` 只检查 `d4follow` / `p2pah-srv-exec` 服务和 `/api/state` 最近12条内存task。它不读持久化 `local_job`，不能发现“采集done但真实写价失败”、缓存失败或本次新增 `write_state=unknown/partial`。
- 监控服务现为root，RPG数据库目录755、数据库644。可以直接通过SQLite `mode=ro` / `query_only` / 有界读取接入，不需要新增API、复制业务库或扩权。
- 原5分钟monitor将 `rpg.issues` 合并进顶层issues；Hermes bridge再消费顶层issues，原watch按 `rpg_` 前缀路由RPG负责人。因此新增正确issue后，现有分类、签名去重和outbox原ID即可复用。
- bridge当前5分钟只导出snapshot，不调用watch发送；夜间23/02/05/08原巡检之外存在告警时效空档。新增回执字段本身不等于即时群告警已经启用。
- bridge当前导出保留issues但没有RPG回执摘要字段。若需要Hermes直接解释原工单，可增加严格白名单摘要；不导出plan、cookie、账号、完整日志或商品金额。

已核活动SHA：

| 活动文件 | SHA256 |
|---|---|
| probe_worker.py | `4a63d28db6ce03f93707bc5b0c987c9f23ee91576094b0c81b0f50189fcf0bec` |
| host.py | `d634de541868987d16126f6b74c7f61fdb8c4a6a34306593a3959f406b204a4f` |
| watch.py | `d6aca8463473c433423e15d8b261289358e2dedad1f9a62cfce6d2e014a2d58a` |

## 推荐最小接线

1. **原probe增加持久回执读取**：从原SQLite只读读取工单ID、kind、status、完成时间及结果白名单。核原 `operation_id` 与数据库ID一致、JSON合法、读取未截断。若数据库锁超时、损坏或覆盖不完整，发 `rpg_receipts_unavailable/coverage_incomplete`，不能当健康。
2. **沿原issues传递**：
   - `rpg_write_unknown:<原ID>`：未能确认写入结果，P0，保留原ID核对，禁止自动重放。
   - `rpg_write_partial:<原ID>`：已写部分行或复核不符，P0，只核对差异与原回执。
   - `rpg_cache_unconfirmed:<原ID>`：后台成功但缓存未确认，单独说明价格已写，不能提示重跑改价。
   - `rpg_order_session_unavailable:<原ID>`：持久阶段证明已结束且零写入；可以沿原恢复能力处置，仍保留失败事实。
3. **可选一项桥接摘要**：在原 `host.collect()` 输出 `rpg` 白名单：检查时刻、覆盖范围、各状态数量、原ID和状态、是否需要对账。现有watch负责人映射不改。
4. **通知复用原链**：若后续授权实施即时提醒，在执行器完成/失败事件上触发原监控链，原5分钟链作兜底。两条入口共用原watch-state/outbox及互斥，不能另建第二套群消息、另定负责人或更换失败请求ID。夜间4轮时间保持。

不能用“最新采集done”覆盖逐工单unknown/partial。它们仅在原ID取得明确对账证据后关闭；原状态和失败日志保留，补充对账结论及回执引用。

缓存恢复须读独立修复回执。本次 `rpg-cache-recovery-20261023-v1` 已真实code1且覆盖原42行成功单，不应将该旧cachefalse持续报成未恢复；也不能借一次清缓存解除未知价格写入。

历史没有阶段证明的旧工单，不凭错误字符串直接补成“零写入”。保留 `legacy_unclassified` 或已有的原ID核对证据。历史清理前要保留未决ID索引及证据引用，不能因8天清理/取最近N条而悄悄关闭未决事故。

## 验收

| 场景 | 必须得到的结果 |
|---|---|
| 采集done、原工单unknown/partial | 仍为P0，携带原ID；新采集成功不能消警 |
| 同一原ID、同一问题连续5分钟 | 去重静默；新问题/状态变化有新证据后提醒 |
| 零写入预写失败 | 不伪称已改价；保留原可恢复路径 |
| 后台成功、缓存失败 | 单列缓存问题，不重放价格；合法补缓存回执可关闭对应问题 |
| 发送超时/接受但无message_id | 原outbox为unknown，先核原请求，不换ID重发 |
| 监控无法读取/结果截断/证据过期 | 显式未验证或覆盖不足，不显示健康 |
| 真通知验收 | 另获发送范围授权后，用真实消息ID与原工单关联读回；本方案未执行 |

开发验证先用合成SQLite和假transport覆盖上述场景，再只读消费现场回执；真实通知、自然5分钟周期与长期告警覆盖分别验收。
