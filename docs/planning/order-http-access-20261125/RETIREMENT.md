# Order 浏览器路径退役盘点（阶段 5）

187 只读取证于 2026-11-25 上海时间。仓库基线 `f5f1776f1e2806e3e52be5587986a45f84105973`（#1373）。前次盘点保留在 Git 历史。

**事务定时采集仍要求 `fs-order-browser` 在线，本轮保留容器。** P0 成本采集自己的 CDP 依赖已随此前 HTTP 发布退役。阶段 3B 的发货统计与渠道成本已切换，事务快照、原生范围及问题订单深查另有运行路径。

| 对象 | 阶段 5 判定 | 证据 |
| --- | --- | --- |
| `fs-order-browser` | **保留** | 187 容器在运行。`fs-transaction-collect.timer` 每 120 分钟调度 `/opt/fs-transaction-snapshot/collector.py`。其 `order_call` 为主源、类目、利润三类脚本调用 `order_reader_runner.run`。runner 检查容器 Running 状态，从其镜像启动短命读取器，并复用该容器网络命名空间访问 CDP。上轮 14:09 启动，journal 记录 `success` 和快照 `20261125T062039Z-a8ec38aa682bee64`。现役范围 API 也在 `fc27-categories` 分支调用这条 runner 路径。指定 systemd、cron 和 Nginx 配置中未找到容器名的直接引用，已通过应用分派确认间接依赖。 |
| `/opt/fs-order-session/raw_node_helper.js` | **保留作旧版回退依赖** | 现役 HTTP `service.py` 无 helper 调用。五份浏览器版回退 `service.py`（`/var/backups/order-http-20261125T031300Z/` 至 `order-http-20261125T045400Z/`）仍引用 helper 与 `fs-order-browser`，最近两份 HTTP 回退不引用。保留旧恢复材料与其依赖。本基线 Git 仅在交付文档中提及 helper，未找到待撤的活动发布映射。 |
| `fc27-cloud-cost:1` 的 CDP 依赖 | **已退役（此前发布）** | 现役 `collect_p2pah_cost.sh` 使用同一成本镜像，挂载 HTTP 会话模块和 socket，无 `FC27_CDP_ENDPOINT`、9225 或 9226；`collect_p2pah_cost.py` 导入 `OrderHTTP`，无 Playwright/CDP 读取。187 文件 SHA-256 前缀分别为 `3ed23e6e88b2`、`d97f22b8494c`。发布备份 `/var/backups/fs-navigation-20261006/nav-20261125T062730Z/` 仍在，15:15 自然轮结果见 [交付记录](DELIVERY.md)。列表正常单免详情复核由独立 PR 负责。 |
| `price_writer.py` 旧标量分支、`repricing_dom.js` | **保留** | 187 现役 coordinator 的适配器仍调用 `execute_price.sh`、`reconcile_price.sh`，旧标量复核会调用 `preview_backend.sh`。部署侧的 `restore_price.sh`、`preview_backend.sh` 同样挂载 DOM 模块。旧 worker 提供对应任务分派，服务 active。本轮已核运行计划、在途和 UNKNOWN 聚合状态，旧入口的实际按需调用频率和退场条件仍待核。 |
| `range_primary_reader`（含发布副本） | **保留** | 187 `/opt/fs-exact-range-20261001/range_api.py:52` 通过 `Path.read_bytes()` 载入读取器并将程序传入 `fc27-cloud-browser`，用于原生范围主源读取。模块接入共享会话并通过 Playwright/CDP 取数。当前 FS MCP 目录仍公开 `business.native_range`。活动映射保留，见 [发货利润来源映射](../business-shipping-profit-20261024/ACTIVE-SOURCE-MAP.json)。 |
| `fc_order_reader` | **保留** | 187 `range_api.py:281–290` 将问题单诊断交给 DeepService 和可选 Hermes 控制器。`fc_order_diagnostics.py:88` 在缓存失效时动态载入该文件，经 `fc27-cloud-browser` 执行。Hermes 能力目录中也有文件读取引用。当前 FS MCP 目录未见对应的独立问题单诊断 operation。保留 [导航发布器映射](../../../releases/fc-coins/fc-pricing-v3-20261026/deploy/release_navigation_base.py)。 |
| `fc27-cloud-browser` 对 Order 的使用 | **保留** | 现役原生范围和深查读取仍使用该容器。宿主 `127.0.0.1:9225` 映射至该容器的 9226，竞品采集也使用此端点。竞品浏览器整体不在退役范围。 |

## 旧标量原操作

- 定价 V3 账本 `/var/lib/fc27-cloud/v3/control.sqlite3` 以 SQLite 只读事务统计。两个旧标量计划的状态字段仍为 `ACTIVE`，其资源所有权均为空。单一 V6 计划持有全部六个资源。旧标量 346 条操作中，232 条 `COMPLETED`、111 条 `NO_CHANGE`、3 条 `CANCELLED_NOT_SENT`。该账本无资源租约、无在途定价操作、无 `UNKNOWN` 状态，另有一项 `outcomes` 汇总任务排队。
- 旧 worker 的 `/var/lib/fc27-cloud/queue` 为空，jobs 未见 queued/running。其 `executions` 状态聚合未见 `UNKNOWN`。另见 3 个历史 `interrupted` job，本次未逐 ID 关联执行结果或后续真实 Admin 现态，不能将这些 job 认定为已经覆盖的历史 UNKNOWN。任何后续从其他历史来源发现的 UNKNOWN 仍按 AGENTS.md 核同商品、真实 Admin 现态及时间、原任务终态。
- `fs-pricing-alerts.path` 和 timer 均 active，现役 `pricing_probe.py:318` 还读取独立 Order 容器内存。`browser_lifecycle.py:178–182` 仍依赖原隔离记录及会话源码 SHA。本轮保留监控及回退关系。

## 生产操作与验收

- 187 会话 `/health` 只读回 `ready=true`、`last_error=null`、`login_attempts=1`、`sessions_lost_externally=0`。销售定时任务 15:14:21 退出码为 0，状态 API 返回生成时间 15:14:20。销售状态 API 不返回 `order_alive`，此前单独的 `order_alive` 读回见 [交付记录](DELIVERY.md)。
- 本轮无生产变更，阶段 5 备份目录未创建。容器和文件保留，未禁用调度，现存历史回退及发布映射继续保留。
- 15:15 P0 自然轮及已验的 HTTP 消费者沿用 #1373 证据。本轮没有退役后自然轮，未触发采集、登录、改价或深查作业。再次评估容器退役前，须先消除事务定时读取器和范围类目对容器的直接运行依赖，并验证替代链路及回退。
