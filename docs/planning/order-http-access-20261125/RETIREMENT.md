# Order 浏览器路径退役盘点（5A）

基线 `1b724d1b`，187 只读取证于 2026-11-25。**本轮没有组件达到可退役证据要求。**

| 组件 | 判定及证据 |
| --- | --- |
| `price_writer.py` 旧标量 DOM 路径 | **暂不可退役。** 现役 V6.1 合同在 `docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md:35,96` 使用 Admin 完整价表。旧标量仍有独立合同（`AGENTS.md:3`），仓库 `releases/fc-coins/fc-pricing-v3-20261026/source/price_writer.py:151–220,471` 保有 Order DOM 实现，`execute_price.sh:27,45` 和 `reconcile_price.sh:19,39` 保有 CDP 及 DOM 挂载。187 coordinator active，目标文件哈希 `9a3ea3c6…`。活跃旧标量计划、在途请求、原 ID UNKNOWN 和 Hermes/API 的现网可达性均未核。 |
| `fc27_cloud_browser/repricing_dom.js` | **暂不可退役。** 执行与对账沿上述挂载，`fc27_cloud_browser/preview_backend.py:39,46` 和 `restore_price.sh:23` 还有预览与恢复引用。发布来源见 `docs/collaboration/SOURCE-MAP.json:1371–1376`。187 目标存在（`b704dd17…`）。活跃预览/恢复入口的路由和调用频率未核，须随旧标量逐项解除。 |
| `range_primary_reader` | **证据不足。** 映射 `docs/planning/business-shipping-profit-20261024/ACTIVE-SOURCE-MAP.json:129–133`，187 目标存在（`4b599c31…`）且第 14 行导入 Playwright。187 `fs-transaction-collect.timer` 每 120 分钟 active，范围服务亦 active。静态查找直接 Python import 无命中，尚缺定时单元到实际读取器的调用证明、HTTP/Hermes/MCP 动态分派及失败回退核验。 |
| `fc_order_reader` | **证据不足。** FC 导航发布要求带此文件（`releases/fc-coins/fc-pricing-v3-20261026/deploy/release_navigation_base.py:150,403`）。187 文件存在（`72f251f7…`），第 15–16 行导入 Playwright 和诊断模块，现网 `range_api.py:281` 导入诊断入口。静态查找直接 Python import 无命中，尚缺诊断到该读取器的实际运行路径、Hermes/MCP 按需注册、定时与回退读回。 |
| 成本容器的 `FC27_CDP_ENDPOINT` | **暂不可退役。** 187 coordinator 与浏览器容器 active，已见成本目标（`9a61aa4c…`）和 cost image。`releases/fc-coins/cost-timeout-20261025/source/collect_p2pah_cost.sh:11–18` 明确设 CDP，现有采集源码在页内读取发货及订单详情。须等阶段 2 六个有效且可比的自然轮及切换后自然轮验收，保留原版本回发所需依赖，随后按阶段 5B 处理。187 进程在取证时点是否正在采集未判定。 |

## 旧标量原操作

按根 `AGENTS.md` 的 2026-11-10 AI 执行入口规则，在途、现态缺失或新 UNKNOWN 沿原 ID 对账。历史 UNKNOWN 如有同一商品、已结束原任务、后续真实 Admin 现态和时间的有效覆盖，退出当前阻断，原账本历史继续保留。本次只读取服务、源码和哈希，未取得可关联的原 ID 与覆盖证据。活跃新旧计划数、在途数和未覆盖 UNKNOWN 数均为未知。服务活跃仅证明宿主入口在运行。独立原回执观察入口 `fs-pricing-alerts.path` 与 timer 在 187 均 active，未读取业务回执。

187 证据取自 `systemctl list-units/list-timers`、`systemctl show`、固定源码路径的 `grep` 与 `sha256sum`、`docker ps` 及镜像非敏感字段。按需调用和回退只核了可见代码与发布映射，真实入口调用未执行。
