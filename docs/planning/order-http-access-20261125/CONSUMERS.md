# Order HTTP 消费者映射（3A）

基线 `1b724d1b`，187 只读核验于 2026-11-25 上海时间。下列维护来源依据发布映射，现网文件与仓库候选需按原 publisher 的载荷及哈希复核。

## 运行环境

- **R**：187 `systemctl show fs-business-range -p User -p MainPID` 返回 root、PID 5493。unit 启动 `/opt/python39/bin/python3`。该解释器以 `-B -c 'import lxml.etree; print(lxml.etree.LXML_VERSION)'` 返回 6.1.3，系统 `/usr/bin/python3` 同一探针报缺包。
- **M**：`fs-boss-management.timer` 每日上海 00:35。service 配置 root:root，`/opt/python39/bin/python3 /opt/fs-boss-workspaces/backend/management_v2_runner.py`。当次查询处于运行窗口之间。
- **S**：`sales-dashboard-sync.timer` active，unit 说明每 30 分钟，启动 `/opt/python39/bin/python3.9 /opt/sales-dashboard/run.py`。`sales-refresh-api` active，启动同一解释器的 `/opt/sales-dashboard/api.py`。两者 systemd 未配置 User/Group，系统服务默认 root。销售解释器别名与 python3 是否解析为同一文件未单独核验。
- **O**：187 `stat` 返回 `/run/fs-order-session` 0755 root:root，`session.sock` 0666 UID 0、GID 11027。broker active，无显式 User。POSIX 权限允许下列已见宿主 UID 访问 socket，容器另需挂载，RPC 成功未实测。客户端候选路径见 `order_global_session_20261021/client.py:7–18`。销售 auth 在 `shared_backend_session/sales_auth.py:7–15,139–140,175` 搜索 `/opt/fs-order-session` 等路径并调用 `fill_jar`。

## 消费者

| 消费者 | 维护源、187 目标及入口 | 解释器、会话及路径 |
| --- | --- | --- |
| 全局发货统计 | 历史维护源记录在 `docs/planning/business-shipping-profit-20261024/ACTIVE-SOURCE-MAP.json:7–13`。后续管理台发布明确覆盖同一 `/opt/fs-exact-range-20261001/business_shipping.py`（`releases/fs-dashboard/management-november-20261103/SOURCE-MAP.json:13–19`）。187 `range_api.py:38,247` 实际导入，供经营范围 HTTP 查询。 | R + O。187 `business_shipping.py:59–63` 通过 `/opt/sales-dashboard/collector/p2pah_auth.py` 填 jar，HTTP HTML 解析使用 lxml 依赖。 |
| RS 发货统计 | 维护映射 `ACTIVE-SOURCE-MAP.json:122–126`，对应发布候选 `releases/fs-dashboard/shipping-profit-20261024/source/rs_shipping.py` → `/opt/fs-exact-range-20261001/rs_shipping.py`。187 `range_api.py:46,236` 实际导入，供 RS 范围 HTTP 查询。 | R + O。187 `rs_shipping.py:44–48` 通过 collector 的 auth 填 jar。范围环境已具 lxml。 |
| 经营管理台 | `releases/fs-dashboard/management-november-20261103/SOURCE-MAP.json:13–19` 分别映射管理台 facts 到 `/opt/fs-boss-workspaces/backend/management_facts.py`，shipping 到范围服务目录。187 runner 第 7 行导入 facts，范围 API 第 27、38 行加载管理台配置及发货函数。 | M 与 R 均为 Python 3.9/root、具 lxml。共享 shipping 的 Order 路径沿 R + O。管理台日更中实际触发哪项 Order 查询未做实时调用。 |
| 渠道成本 | `releases/fs-dashboard/dashboard-refresh-20261025/source/channel_cost_source.py:59,103`，组合发布目标 `/opt/fs-hermes-fc/channel_cost_source.py`（同 release 的 `deploy/es_data_release.py:35`、`deploy/prepare_es_data.py:204`）。已核目标存在。范围 HTTP `/channels` 调用证据见 `source/range_api.py:371–372,405–411`。 | R + O。经 `/opt/sales-dashboard/collector/p2pah_auth.py` 建会话，用 lxml 解析发货 HTML。187 的 Hermes service active，具体是否独立运行此消费者及其解释器未核。 |
| 销售采集 | `shared_backend_session/sales_collection.py:34,364–397` 为仓库接入源。187 现场对应 collector `/opt/sales-dashboard/collector/fetch_all.py`（32–34 行导入 auth/lxml），定时及刷新入口见 S。按仓库文件名查找 `sales_collection.py` 无此目标，原发布器的字节映射待核。 | S + O。通过同目录 `p2pah_auth.py` 取得 Order 会话。 |
| 实际利润 | `releases/fs-dashboard/dashboard-refresh-20261025/source/actual_profit.py:125` 委托渠道成本，`deploy/cache_scope_release.py:5` 映射至 `/opt/fs-exact-range-20261001/actual_profit.py`，后续维护来源见 `docs/planning/admin-recovery-review-20261028/P1-DIRECT-API-TARGETS.json:19`。按需 HTTP `/channels?mode=actual-profit` 分派见范围 API 409 行。 | R + O。lxml 与 Order 会话由渠道成本路径继承，利润计算自身无需向 broker 再取一次 cookie。 |
| FC 成本采集 | `releases/fc-coins/fc-pricing-v3-20261026/source/collect_p2pah_cost.py` → `/opt/fc27-cloud-browser/collect_p2pah_cost.py`（同 release 的 `deploy/target_map.py:297,360`）。187 `fc-pricing-v3` active，root:fc27cloud。包装 `releases/fc-coins/cost-timeout-20261025/source/collect_p2pah_cost.sh:11–18` 启动 180 秒超时的一次性容器。 | `fc27-cloud-cost:1` 的 image 配置用户为 fc27chrome，实际数字 UID、容器 Python 版本和 lxml 未核。包装挂载 O 的代码和 socket，`PYTHONPATH=/opt:/opt/fs-order-session`，走 broker 客户端与 Playwright/CDP。 |

## 发布关系与待核项

`business_shipping_profit_20261024/source/` 是活动映射中的维护来源标识，该前缀在本次基线未作为 Git 目录存在。`releases/fs-dashboard/shipping-profit-20261024/source/` 保留对应发布载荷副本。11 月管理台 release 对同一全局 shipping 目标有独立后续发布映射，RS 不在该清单。对照 `docs/collaboration/SOURCE-MAP.json:2383–2388`，范围读取器另有基础映射，不能由其推定当前 shipping 文件版本。

187 `sha256sum` 返回全局 `a005fff1…`、RS `2e3a1ace…`、实际利润 `83daebfd…`、FC 成本 `9a61aa4c…`。管理台 SOURCE-MAP 第 41 行的全局载荷为 `ca120282…`。全局现态的导入结构与 11 月管理台版本一致，但哈希证明需继续沿后续发布记录定位。阶段 3B 应基于确切活动载荷确认修改点，保留历史副本。

## 阶段 3C 现役读取器

核对时间为 2026-11-25 上海时间。现场证据来自 systemd 单元、源码调用点和 SHA-256。发布载荷及复核前置见 [阶段 3C 清单](consumer-release-3c-manifest.json)。

| 消费者 | 187 入口和调用方 | 维护源与候选运行方式 |
| --- | --- | --- |
| 事务定时采集与范围类目 | fs-transaction-collect.timer 每 120 分钟触发 /opt/python39/bin/python3 -B /opt/fs-transaction-snapshot/collector.py。现役 collector.py:35–61 对 primary_reader.py、fc_category_reader.py 和 profit_daily_reader.py 启动 order_reader_runner，runner 借用 fs-order-browser 网络。fs-business-range 的 fc27-categories 分支也调用同一个 collector。 | 活动 collector 在 releases/fs-dashboard/dashboard-refresh-20261025/source，事务主源和类目在 fs_transaction_snapshot_20260930，日利润在 candidates/business-snapshot/order-endpoint-padding-20261007/source。候选保留锁与超时，通过宿主解释器运行读取器，复用 /opt/fs-order-session。 |
| 原生范围 | fs-business-range 以 root 运行 /opt/python39/bin/python3 -B /opt/fs-exact-range-20261001/range_api.py。现役 range_api.py:48–53 将范围读取器发给 fc27-cloud-browser，读取 /stats/admin_order/index.html。范围 HTTP 和 FS MCP 的 business.native_range 共用这条读取路径。 | 读取器维护源在 releases/fs-dashboard/shipping-profit-20261024/source。候选范围 API 通过宿主解释器调用同目录读取器。读取器从 /opt/fs-transaction-snapshot 加载 primary_fields，从 /opt/fs-order-session 加载 order_http。范围 API 现网与仓库源存在后续路由差异，发布时只对已核哈希的现场文件替换 Order 派发。 |
| AI Advisor 与 Hermes 问题单诊断 | fs-business-range 的 DeepService 在缓存失效时经 fc_order_diagnostics.py:88–91 运行 /opt/fs-exact-range-20261001/fc_order_reader.py。Hermes 能力的 fs_reader 引用同一读取器。 | Advisor 诊断维护源在 releases/fs-dashboard/ai-advisor-20261013/deep/source，与 Hermes 能力引用的诊断副本同步。带 Hermes 投影的读取器及调用方在 releases/fs-dashboard/hermes-fc-pilot-20261013/admin_order_capabilities_20261014。候选保留缓存、锁、列表页数和详情样本上限，复用 /opt/fs-order-session。 |
