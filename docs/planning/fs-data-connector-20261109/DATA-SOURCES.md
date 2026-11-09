# FS 读取面与连接器映射

2026-11-09，当前业务数据目录快照；本轮目录收窄及方法新增尚待单独发布。已有发布与真实结果见 [LIVE-ACCEPTANCE.md](LIVE-ACCEPTANCE.md)，不以操作数量视为全量接通。

机器清单`fs_mcp_connector/catalog.json`保留30项业务导航范围及6项非导航范围，共113个命名读取操作，登记站点目录/Google数据的共享入口及未完成项；精确数量以该清单为准。数量只表示候选适配，不表示模块全部数据或真实用户验收通过。调用只接受对应schema，未知字段、任意URL/SQL/文件路径和身份覆盖都不是查询入口。

2026-11-09用户明确撤销模型不能读取客户身份的旧限制：在原FS管理员、private、owner/session及对象权限内，邮箱、UID、原订单号和业务明细可以返回，用于客户与订单查询；只过滤凭据，不再将这些业务标识当作secret或强制匿名。匿名聚合仍可按需使用。旧不可变reviewed快照保留哈希历史，不能恢复为本轮有效规则；生产知识索引及实际加载另按版本发布验收。

本轮按用户最新范围退出5项`conversations.*`及6项`reports.*`：前者属于Hermes会话，后者是历史生成/导入报告池，不是Admin订单或原始经营数据。weekly/brain报告导航不再作为连接器缺口；原FS能力不删除。`campaigns.report`是活动统计，`customer_tracking.*`是客户业务数据，`knowledge.*`只读获准发布文本，均保留。固定业务传输参数或源码路径含Hermes不表示接入代理。

当前AI可从`fs_list_data_sources.data_methods`取得按权限过滤的可选方法/口径；详见 [DATA-METHODS.md](DATA-METHODS.md)。

## 来源与现场证据

- 基线 `0a1ef1e1cda8dfa1815f95720c684bfd8a1e35ca`；主代理只读导出的当日 nginx 路由用于交叉核实。只匹配 FS `iggm-web.conf` 与其共享 include，排除其他虚拟主机、预览和历史不可变资源URL。现场文件位于本地 `.agent_runtime/connector/host_routes_current.json`，不入库，也不回传模型。
- 每个操作记录当前仓库源码、固定路径、权限检查入口、参数及请求/响应预算。`route_observed_date` 证明当日网关有相应路由；**不证明后端文件SHA、数据正确或角色权限已实测**。源码存在测试不取代运行验收。
- 用户确认 FS 真实入口为 `https://47.85.224.112/dashboard/#overview`。`events-origin.p2pah.cn` 的404不用于判断 FS 故障。
- 历史 `docs/collaboration/SOURCE-MAP.json` 明示为快照，未拿它直接认定上线。具体活动模块优先采用现役源码、模块发布映射和当日路由的交叉证据。

## 已有候选操作

| 模块/数据 | 命名操作/固定读取面 | 依据与保留的合同 |
|---|---|---|
| 数据看板 | `business.catalog/archives/summary/profit_history/native_range` | `dashboard-refresh-20261025/source/range_api.py`、`live_summary.py`；`business-filter-layout-20261025/SOURCE-MAP.json`；原网站/RS/游戏/时间筛选、pending、毛利来源和原共享池保持 |
| 用户分析/订单 | `users.catalog/summary/members/detail/search`、`orders.live/customer` | `user-analytics-20261022/source/user_http.py`、`user_query.py`、`user_contract.py`，原private授权；实时订单合同20条/页、28天、365天、256KiB/10秒、partial及原游标，精确邮箱只POST；原权限下邮箱、UID、原订单号可回模型用于继续查询 |
| 数据分析工具 | `analytics.user_section` | 原 `user_tools.invoke` 的 `action=tool` 读取；冻结快照、证据ID、section、覆盖与生命周期规则不重算；H仅7/30 |
| 渠道效果 | `channels.code/coupon/profit` | 当前 `dashboard-refresh-20261025/source/channel_effects.py`，50条分页、原归因及金额合同；不暴露任意查询表达式 |
| 营销/Ads/GA4/GSC/流量 | `marketing.range/business_links` | `daily-archive-20261021/source/marketing_range_api.py`，原 `/dashboard/marketing/` 网关到8935；保留来源时区、Ads账户、失败/旧值/部分状态。8MiB来自原缓存上限，原366日区间由服务核验；不套实时订单28天限制 |
| 活动转化 | `campaigns.statistics_snapshot/report/discount_revenue/origin_traffic/ads/ga4/gsc` | `campaign-analytics-20261023/app/analytics/production-server.mjs`及对应reader；计划结果读不触发refresh；自选31天、原PostHog有界查询、Google单通道/缓存及来源合同保持 |
| 活动商品 | `campaigns.catalog` | 原商品catalog/registry/layout；编辑器center、connection、config等含csrf的接口未作为数据导出；待独立业务投影，未降低原编辑功能 |
| SEO/日历 | `seo.current/manifest/summary/history/sources/rankings/markets/calendar/pages/orders/rules` | `mmoexp_google_data/seo/{web,api,snapshot}.py`，已发布快照、原4游戏范围、每页1–100及原cursor；不提交新采集 |
| 任务 | `tasks.board/members/detail/events` | `opt/mmoexp-taskboard/taskboard_server.py`，当前 `/dashboard/tasks/api/` 到8932 `/api/`；原成员与对象权限；不导出含会话令牌的session辅助接口 |
| 游戏情报 | `game_monitor.intelligence/intelligence_status/seo_news/seo_news_status` | `ui-system/modules/game-monitor/{README.md,web/app.js,prepare_ui.py}`；当日四条JSON路由，内容与状态独立；未恢复退役工作区或采集计划 |
| 经营管理 | `management.targets/daily_v2/daily_status` | `management-november-20261103/SOURCE-MAP.json`、原runner和当日路由；全站目标、发布事实和状态仅读；按期配置bundle、历史期仍待适配 |
| FC金币 | `coins.monitor/automation/player_sync/jobs/snapshots/quotes/previews/audits/restore_previews` | `fc27_cloud_browser/fc27_cloud_api.py` 与当日 `/api/fc27/cloud/` 网关；UUID白名单，仅读原状态/结果，不重放原操作；新版smart扩展读取面仍须继续核查 |
| MLB | `mlb.stats/coins_rate/tasks/task` | `opt/mlb-online/mlb_server.py` 与当前 `/mlb/`；最多300条，任务ID12位hex；不注册执行器配置或写回 |
| NBA | `nba.read/current/competitors` | `opt/nba-reprice/backend/server.js` 与当前 `/nba2k27/api/`；沿原服务鉴权，不提交apply；已接线真实角色、当前proxy认证模式仍待验 |
| FC捆绑包 | `bundles.state/search` | `fc27_pack_bundles_20261013/src/pack_bundles_server.py` 与当前8904网关；原已保存产品绑定、价格与最多12条player搜索，不刷新或写价 |
| Madden | `madden.monitor/automation/activity/jobs/quotes/previews/restore_previews/audits` | `madden-browser-isolation-20261023/source/dashboard/server.py` 与当前8792网关；活动最多500条；只读路径无采集、写价或恢复 |
| RPG | `rpg.cost_status/iggm_source/shelf_drift/history` | `opt/d4follow/app.py` 与当前8900网关；保存成本/状态、60点历史，IGGM来源判断dry读取；不注册local/pull等领取任务面 |
| SBC | `sbc.status/rows/automation` | `fc-sbc/security-20261015/source/webapp.py` 与当前8793网关；rows保留原admin限制；未导出任意下载文件或后台登录材料 |
| 机器人 | `bots.fc_status/fc_news_items/fc_logs/service_status` | `opt/bot-console/server.py` 与当前8936网关；FC日志采用原已过滤安全日志，服务名固定guard/shugo；通用日志和凭据配置未注册 |
| 部署/站点目录 | `deployment.sites/log` | `opt/deploy-hub/deploy_server.py` 与当前8898网关；最多500条原审计，保留网关真实owner；不注册上传/删除/执行文件 |
| 客单追踪 | `customer_tracking.config/tracked/request/candidates/detail` | 当前`hermes-customer-lifecycle-20261019/source/`；新增stored_only分支沿原AdminService复用Store，以独立SQLite mode=ro+query_only查询，不_poll_scan/_poll_history/observe/queue。`tracking.py`五view固定业务投影保留邮箱/UID/原单号/订单明细、覆盖、stored_only/refreshed，不重算金额 |
| FC运营状态 | `ops.health/job` | 当日SSH核对现役`/opt/fc27-ops/ops_api.py`的GET源码与SHA，见`REMOTE-SOURCES.md`；原网关真实主体，job固定32位小写hex，不提交collect；原worker/job结果保留敏感字段检查 |
| 进化商品 | `evolutions.state` | 当日8914现役源码已核；`evolutions.py`已扩展config/overrides、snapshot模型/商品/汇率、rows、job/history、blocked及调度状态业务投影；raw上游错误正文明确withheld，source/SHA见`REMOTE-SOURCES.md` |
| 销售系统 | `sales.status/snapshot` | 现役8905和受保护`/sales/data/dashboard.json`已核；status固定业务字段，snapshot按meta/promoters/owners/codes/orders分页，每页最多100条、续页核同文件SHA；获准邮箱/UID/原单号保留；不注册refresh |
| 球员维护 | `players.status/candidates/models/tags/jobs/job/plan` | 当前8901与`fc27_players_cloud/player_web/main.py`；`PlayersService`复用原bootstrap，服务端保管SID/CSRF，模型不获得凭据；沿原owner、后台会话和分页 |
| 收藏馆 | `gallery.state` | 当日现役`/opt/fc27-gallery/api.py`与storage已核；`gallery.py`固定业务投影config、latest报价/目标/计划、最近30jobs和schedule，不启动采集/writer；部署源SHA见`REMOTE-SOURCES.md` |
| 部门手册/历史库存参考 | `docs.handbook`、`odds.reference` | 两处现役目录分别只有受保护的静态index.html；固定读取`/docs/`及`/s/wulv/fc-odds/`，HTMLParser转中文标题/正文/表格并剔脚本。odds为FC26历史参考，不冒充当前FC27库存 |
| 知识 | `knowledge.index/read` | 固定服务配置`FS_CONNECTOR_KNOWLEDGE_ROOT`，真实subject复用原FS/data selector、门户brain权限、published索引/hash及modules/entry_ids/history允许集；无匹配route明确unavailable，不借Git候选或管理员替代 |
| G2G | `g2g.state/job` | 原state/job已接业务行、计划、汇总、最近30条执行回执及任务阶段；只返回凭据可用状态，raw错误正文/未核日志明确withheld并保留log_coverage，不以空结果冒充完整 |
| 账号与权限 | `accounts.overview/audit` | 原受保护`/__auth/access/api/overview`及audit、原管理员manage权限；固定投影成员、角色、资源目录及审计，过滤会话/CSRF/token，不新增成员或权限 |

## 未接通面及必要工作

以下为当前FS业务数据范围的剩余面，不以目录数量替代完成；Hermes会话与历史生成报告已按用户要求退出，不能再列为本轮取数缺口。

| 导航/非导航范围 | 已定位依据 | 缺口及需要的最小适配 |
|---|---|---|
| FC运营看板（ops）其余数据 | 当前 `/s/wulv/fc27-ops/api/` 到8899；当日现役源码/SHA见`REMOTE-SOURCES.md` | 已接health/job候选，静态页面其他数据与字段仍需核对；不把两操作视为整模块完成 |
| G2G历史/原错误详情 | `opt/g2gfollow/app.py`，当前8903网关 | 当前state/job已接；旧快照与完整历史是否存在独有内容仍待逐一核验。明确withheld的错误正文/日志需在去凭据后准确表达，不据两操作宣称全量 |
| 销售系统其余状态文字 | 当前`/sales/api/status`到8905 | snapshot业务数据已接；phase/detail/log_tail仍待去凭据后的字段合同，不注册可能触发更新的GET refresh |
| 进化商品原错误正文 | 当前`/dashboard/fc27-evolutions/`到8914 | 已接全部已核业务状态；raw后端payload及未核错误正文仍withheld，需要去凭据后保留有用错误，不能称全部执行结果已输出 |
| 账号本人辅助信息 | 原IAM本人/管理边界 | overview/audit已接；bootstrap含CSRF且创建会话，不能直接作为读取。若另有独有可读账号业务字段，须沿原本人/manage权限接入 |
| 已部分映射模块剩余独有内容 | 见上表及各原服务路由 | 活动编辑商品业务投影、经营历史bundle、新版FC扩展等仍待核对。CSV/SSE/二进制若只是已接JSON的重复格式，不另算数据缺失；未核与已证实缺项分别记录 |
| 客单追踪覆盖 | `tracking_readonly.py`与原publisher | SELECT-only候选/详情及五view投影已完成，原服务增量发布记录见真实验收；业务查询仍应检查stored_only/refreshed/history/complete及实际日期，不据已有存储宣称实时全量。 |
| FC活动记录 | `fc27_cloud_api.activity_feed` | GET会调用 `activity_log_store.capture`。需明确这是原读取必需审计缓存还是包含业务写入，并提供保留原语义的纯查询适配；未把它混入当前纯读取候选 |
| 独立machine query API | `on-demand-20261012/source/query_api.py`，当前8933 | 使用独立Bearer fsq身份，不是FS Cookie入口；不复制固定token或固定用户。可复用其底层原range读取合同，不以此绕过当前用户授权 |

## 参数、响应与测试边界

每操作都保持原命名参数和原分页字段，窗口/资源有效性继续由原服务核验；连接器先验证类型、未知字段、整数上下限及路径ID。原服务的共享池、限频、权限与业务公式不在本次改动。连接器自有传输上限明确记录于catalog，超限/超时返回错误，不裁切冒充完整。

本地已验证catalog闭合schema/固定路径/原分页/partial与游标、静态正文、追踪stored_only合同；知识真实owner/门户权限/历史允许集/hash漂移/不写文件；文档中文实体/脚本剔除/异常编码；gallery与tracking嵌套业务投影、凭据过滤及获准身份保留。原追踪回归覆盖SQLite只读、admin边界、错误状态、publisher依赖、按需匿名聚合、模型身份/订单明细、报告幂等/CAS/输入边界。精确用例数及Linux/CI证据由主代理统一记入ACCEPTANCE；替身测试不冒充生产或真实成员查询。

## 知识原权限复核与生产根目录

原 `knowledge_catalog.task_selection`（`knowledge-layering-20261023/source/knowledge_catalog.py:177`）按真实owner/project/channel/task_type及原可选profile/chat/thread精确匹配policy中的已发布路由；`selected_route/select`继续限制固定catalog/hash、modules、entry_ids与候选/冲突状态。原 `NativeKnowledge._pin_task/call`（`hermes-server-unify-20261022/fs_readonly/knowledge.py:206`、`:404`）只从pin允许模块/条目及明确历史允许集读取，没有额外逐文档ACL证据表。原 `conversation_knowledge.lock_knowledge/host_call` 另核真实owned turn、session、profile、active grant与host.authorizer，是对话执行链的身份边界，不能用伪造任务调用替代；报告消费入口 `native_reports.prepare_knowledge` 同样以真实owner调用原selector。

因此连接器独立知识查询复用实际principal.subject的原FS data路由与门户brain读取权限，不新增`entry_permissions`配置或阻断表；无匹配路由明确不可用，不能借固定管理员或其他channel/profile扩大授权。初稿要求新增逐条证据表的限制已移除，相关回归改为验证原route的modules/entry_ids确实隔离。

生产知识根目录合同在 `knowledge-layering-20261023/deploy/release.py:17`、`:30`及`hermes-learning-closure-20261023/deploy/routes_release.py:11`：policy位于 `/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json`，不可变索引位于其下 `knowledge-releases/<release>/index.json`，原运行selector为 `/opt/fs-hermes-fc/knowledge_catalog.py`。`FS_CONNECTOR_KNOWLEDGE_ROOT`只由服务部署配置设置为该真实根目录；模型不收root/path/profile/module参数。启动接线仍须核当前部署源/读取权限，缺配置明确不可用，不回退本地Git候选。
