# FC 项目复盘的 FS 数据入口

`business.fc_project_review` 从 `unified-business` 目录发现。传 `profile`、`start`、`end`，游戏取 FC26 或 FC27，日期采用包含结束日的北京时间自然日。目录声明固定将原调用者的登录态带到 `/dashboard/fs-home/range.json`，查询条件为 `mode=fc-project-review`。FS 后端复用原管理员权限。完整复盘返回 202 时沿相同参数继续。

## 按版本展开与复查完整报告

完整归档的 `revision` 在响应顶层。MCP 小结果可从 `data.revision` 读取；大结果的索引和展示分页将 `revision`、`archivedAt` 保留在 `data_context[""]`。下一次调用在 `arguments` 内沿用 `profile`、`start`、`end` 并加上该 `revision`，在工具参数外层传 `data_path`（如 `/packets/0/kpi`、`/packets/0/ordersData`）并将数组响应的 `response_view.next_offset` 传给下一次的 `offset`。

HTTP 查询也可携带 `revision`，取 64 个小写十六进制字符，匹配同一游戏和期间下的已保存完整报告。版本缺失时返回 404，版本请求与 `view` 或 `refresh` 同传时返回 422。

普通读取可复用的完整报告时，若期间为最多三个已结束的自然日，会检查本地同单证据。证据可用且结果发生变化时，只更新 `sameOrder` 及对应覆盖说明并保存为新版本。指定 `revision` 直接读取当时已存内容。HTTP `refresh=true` 仍沿原流程重取整份复盘。

## 三个完整付款日的同单采购毛利

在原操作追加 `"view":"same-order"`，例如 `{"profile":"FC27","start":"2026-11-16","end":"2026-11-18","view":"same-order"}`。看板在「经营概览」展示同一响应，筛选中可选择「全站近三个完整日」。沿用原管理员权限。只读现有发布和发货归档，不启动经营复盘或上游采集。未传 `view` 时沿原完整报告模式。

- `totals.salesUsd` 与 `totals.orders` 使用固定共享发布中的全站 Admin 付款订单，剔除已确认测试单、验证未通过和退款订单。原生汇总的读取时点独立，缺日时标记已知小计。查询最多三个已结束的北京自然日，当日付款汇总走 `business.summary` 并注明截止时间。
- `totals.actualCostCny`、`totals.grossCny`、`totals.grossMarginPct` 只使用可核对的已完成、未退款订单。分母为同一批覆盖订单的原 Admin 人民币收入。完成状态用现有主站客户库逐日采集回执和同一原生订单复核。成本仅含同网站和原订单号可关联的普通订单发货，发货归档覆盖付款至已完成状态的观察时点。无法关联的销售补发、最终结算、缺成本和未完成订单不参与毛利。待核成本订单同时报告可核实付金额。
- `breakdown` 按站点和可证的平台分组，同单只进一组。平台使用固定发布中具有单行单件证明的原生 Coins 投影；多行、混合及未能证明的平台归入未知。查询返回来源、覆盖及复合修订号，发货日看板毛利仍使用原口径。

| 源码 | 现有发布目标 |
|---|---|
| `releases/fs-dashboard/fc-project-review/{api.py,same_order.py}` | `/opt/fs-exact-range-20261001/fc_project_review/`。复用原 `/range` 项目复盘分支和 `fs-business-range.service`。 |
| `releases/fs-dashboard/fc-project-review/{index.html,review.js}` | FC 项目经营看板当前正式静态发布路径。使用原静态发布器生成，现役哈希在发布前核对。 |
| `releases/fs-dashboard/user-analytics-20261022/source/shared_es_facts.py` | `/opt/fs-hermes-fc/shared_es_facts.py`。只读原共享 ES 归档及主站逐日采集回执。 |
| `fs_mcp_connector/{catalog.json,response_view.py}` | 连接器运行镜像 `/app/fs_mcp_connector/` 中原 `business.fc_project_review` 目录与版本续查展示。 |

回执缺失或需要更新时，使用原客户任务的精确日期同步。在已有授权的运行环境，用 `python3 /opt/fs-hermes-fc/user_jobs.py sync --site 266 --start 2026-11-16 --end 2026-11-19` 补主站付款自然日；该命令的 `--end` 不含当日。已有回执默认复用。需要重读已覆盖日时沿用 `--recheck`，待原 Order 发货归档覆盖新的观察时点后再次读回。

## 归档续查版本的发布

从运行中连接器的原镜像导出 `/app/fs_mcp_connector/catalog.json` 和 `/app/fs_mcp_connector/response_view.py` 的原始字节，记录镜像 ID 及当前服务定义文件的 SHA-256。在已审核源码工作树生成候选。

```text
python3 -B connector_release.py prepare <候选目录> --operation fc-project-review-revision --active-catalog <原目录> --active-response-view <原展示代码> --base-image <原镜像ID> --unit-sha <原服务定义SHA256> --source-commit <源码SHA> --merged-commit <合并SHA>
```

候选保留活动目录中的其余操作，仅为现有 FC 操作加入可选 `revision` 和续查说明，并更新展示代码的 FC 版本上下文。沿用原 `build`、`check`、`apply` 和 `rollback`，构建和检查会读回基础与候选镜像的两个文件哈希。

## 首次接入的发布输入

本节历史输入对应专项首次接入。11 月 19 日晚本次提速实核的活动镜像为 sha256:d5961d59734ada4ae3214063b4595aa5d17c5ac45166028ace6af92c004001ad，目录 SHA256 为 872caef8b5129c20937ed0769051d12601cc3b7056847357e68fbafd5565915d。本次候选须使用该现场基线或重新核对后的版本。

- 2026-11-19 已读回运行中镜像 `sha256:18a4c07741382bef8a99e0c3967d7b31a0c9a4d21e0a6d080018f706dd379088`，本机标签 `fs-data-connector:stage5-methods-27fe096`。
- 现行目录哈希 `07c81c4615d5c30aeee969f145a3c4c09971030f445682eb3330f2a70394a598`。新目录只增加这一入口及统一经营模块的操作计数。核对脚本逐项比较原 116 个操作、其余覆盖和数据方法。
- 运行服务定义哈希 `e353ddb0c4ac846086675f331fc3e8331260ff7ff965ff2156e4598c5f7f9ffb`。只替换连接器镜像 ID，应用、读回和回滚复用原连接器发布器。OAuth 数据、访问权限、网关配置和其它服务使用现场现有配置。

## 流程

先通过原授权读取现役镜像中 `/app/fs_mcp_connector/catalog.json` 的原始字节。在包含已审核源码的工作树，使用 `connector_release.py prepare <候选目录> --active-catalog <原目录文件> --source-commit <完整源码 SHA> --merged-commit <完整合并 SHA>` 生成候选。真实发布在同一批准窗口最后执行，先确认所映射的 FS 后端已经随本专项发布且可使用。

在已批准的服务器隔离目录运行包内 `python3 -B connector_release.py build`，以现场固定镜像离线构建单目录层。运行 `python3 -B connector_release.py check <新镜像 ID>` 复核运行镜像、服务定义及候选哈希。经正式授权执行原包内 `apply` 后，从真实连接器按本目录和目标操作读回，核对原 admin 权限和返回期间。回滚沿同一候选包内 `rollback` 与备份回执。若原基线已变化，先核对现场实际版本和差异。

本地已验证固定路由、未知参数拒绝、原管理员拒绝透传、202 原样续查，以及目录逐项差分。镜像构建、运行镜像读回和认证角色验证分别记录。
