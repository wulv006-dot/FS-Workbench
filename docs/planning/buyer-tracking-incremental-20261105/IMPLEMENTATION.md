# 用户分析日更与身份字段接入

## 本轮结果与边界

用户于2026-11-05确认每日补昨日新单、周一复核当月及前两个月、发布后清理冗余导出。本规则已在PR830日更基础上经PR834／835上线，真实用户分析与渠道页面均可读取；首日2026-11-06北京时间04:18—05:00、首周11月9日自然窗口未验。本次未人工触发全月采集或清理，未切换客户主键，也未完成buyer全年价值重算。当前归档与调度合同见[月复核说明](MONTHLY-RECONCILIATION.md)。

## 已核实际状态

- 生产 `user_jobs tick → user_weekly.wake/run` 已切换日更。原15分钟唤醒保留，实际工作窗口04:18至05:00；同一日发布成功后其余自然轮source_calls=0。旧周快照的日期与cadence不改写为日快照。
- 订单事实已在 `/var/lib/fs-user-analytics` 按订单ID去重存储并保留修订；不是每次查询全量重新下载。旧订单退款、状态仍可能变化。
- 新任务采用calendar-months-v1：平日补昨日与真实缺日；周一按当月及前两个月全状态复核，代替固定90日窗口。新策略取消每日重复旧日轮巡和已被月复核覆盖的重复逐单查询；历史缺口、旧在途任务原合同及原ID恢复保留，不每日重拉全历史。
- 自动整库备份已按此前授权退出，现为on_demand_only。本次不恢复每日整库复制，也不删除旧恢复点。
- 普通Order/index实返uid，尚未见buyer_id；历史ES导出实返buyer_id和uid。2025-09-28文件1835行，两列已确认。新字段原值为不透明文本，不假定数字。
- 已核完整 `downloadsMake` 日期+FC26游戏`gid=833`+`buyer_id`组合：返回187行FC26订单，只有1行为目标buyer。游戏筛选有效，但此顶层buyer参数未筛选；不能用该响应当客户全年历史。ES列表当前授权身份返回业务401，未绕过。
- 日增量无需buyer筛选：按日期取得新/缺日订单，按确切订单键幂等存档；已有ES文件中的buyer/UID可关联订单。buyer精确查询缺口影响按客户回查全年历史，不阻塞每天补昨日新单。用户已确认可接受该筛选缺口，优先历史留存与日增量。

## 最小实现

复用 `weekly-work.json`、meta `weekly_publication`、既有jobs锁和CAS，不新增状态机或定时器。旧字段名继续兼容，publication增加cadence=daily；没有cadence的旧周快照按weekly解释。

1. 每天原窗口使用当天零点为截止，逐日检查完整coverage；缺失日补采，不用最大日期冒充连续完整。
2. 已完整新增日可复用；周一自然月复核要求本周期抓取时间，不能用旧缓存冒充已复核。新月候选完整前不覆盖当前发布固定文件。
3. 平日ES标签沿原归档读取，仅补缺日；周复核按月重新核全状态。完整月可服务日/周子区间；当月只至复核开始时昨日，之后的新日另保留。
4. 原周任务若在途，先以原任务截止完成，不改ID或改成日任务；下一自然轮再推进日截止。
5. 订单coverage和标签齐全后才发布。数据页、下钻、导出、Hermes与A2继续共享同一冻结snapshot/data_version。
6. 同日成功且无待续月复核/清理时，不调用业务源。复核跨日先补新日再续原周期；失败保留游标与上次发布，永久清理错误不阻止下一日补新。完整月与最新日发布成功后才清理已证冗余件，无额外副本备份，Store历史重放保留。

## PR830日更初次发布记录（由下节月复核版本接续）

仅 `/opt/fs-hermes-fc/` 的 `user_weekly.py`、`user_runtime.py`、`user_jobs.py`、`user_query.py`、`user_customer_types.py`、`user_tools.py`、`a2_query_context.py`，以及原用户分析静态目录的 `index.html`、`users.js`。沿原publisher、CAS和备份回执，不改服务timer、权限、价格、广告、ES Cards解析或共享来源。

本次部署保持9目标精确范围。`user_query.py`以生产363f7972来源仅应用3处cadence接线，不整文件携带main尚未部署的member_keyset/streaming-export能力。实际组合178项回归通过；before/after哈希留私有清单。

主控于2026-11-05沿原stage `/opt/fs-release-stage/user-daily-7312aa31-v1` 发布，原发布ID `nav-20261105T052700Z`，备份 `/var/backups/fs-navigation-20261006/nav-20261105T052700Z`。apply退出0，9目标SHA读回全部一致，host-runtime为all_readers_loaded，Range/Hermes均active，Range健康接口通过；未单独调用Hermes健康接口。最终manifest SHA为`006f87c82fa253c4644682685cda5df2c42fbca738cddb105678c39011d6607c`。

此前等待中的只读inspect已结束；业务锁自然释放后重新capture发现仅`.curator_state`与`.usage.json`动态内容变化，9目标及其他保护项不变。旧plan/manifest保留为`*-before-dynamic-review.json`，只复核两动态hash后沿原publisher执行，没有取消锁保护或替换业务任务。

Chrome真实`/dashboard/users/`已显示“每日更新”，4917人及原快照正常可读；旧快照仍为weekly、截至11月1日、旧next为11月9日，未伪造新冻结结果。下一自然日周期单独验收，不能用构造时钟或人工补采冒充。

## 2026-11-05月复核版本已应用

- 归档PR834：合并`2b96801d9905e635687ac67ed6d945bbaf6e109d`，正式CI41979275770通过；调度PR835：合并`bd308d1a`，正式CI41980053777通过。
- 原发布器release为`nav-20261105T062800Z`，stage为`/opt/fs-release-stage/user-monthly-bd308d1a-v1`，manifest SHA256为`6147bf6dc96910d8717f55d9e134aabdc21cfb59650b40b466cb4d2fa5117d6a`。7目标SHA读回一致，host-runtime为`all_readers_loaded`，Range/Hermes均active；P0定价PID24231未变，原timer仍active/enabled。
- 7目标为`/opt/fs-hermes-fc/`中的`user_weekly.py`、`user_customer_types.py`、`user_store.py`、`user_query.py`、`es_order_structure.py`、`channel_source.py`，及`/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js`。Store仅沿live基线加入PR832按确切订单附加buyer/UID、刷新保留identity和revision记录；query仅沿live日更基线加入归档短锁与状态字段，未带main未上线的version/member索引。
- 日更核心身份附加已上线；PR832其他生命周期/追踪工具未上线，客户主键未改为buyer，未验证全部历史关联完成。字段支持不代表已跑新日，更不代表FC26全年重算完成。
- Chrome重载真实`/dashboard/users/`可读4917人及原完整快照；旧快照仍截至11月1日。由同页导航进入`/dashboard/channel-effects/`，2973单分页、金额和成本表可读；原覆盖及新老客未提供状态保留，未手动刷新源端或触发额外采集。
- 本次未人工触发全月采集/清理。首日11月6日北京时间04:18—05:00、首周11月9日自然窗口尚未验收；真实页面可读不等于生产月清理后已验收。知识Git更新与FS冻结知识发布分开，新版知识加载及新会话应用仍未验。

## PR830验证记录

183现有Python3.9.18隔离容器，无网络、只读根、0.25CPU/256MB：用户分析293项全部通过。包括失败日与完整日交错、跨日续旧周任务、周一90日修订、ES前6日复用和只补末日、标签未齐不发布、同日幂等、旧snapshot回放及既有权限/存储测试。UI日期4项、JavaScript语法及git diff检查通过。

首次整套运行因打包遗漏原宿主源码/服务文件出现5项FileNotFoundError，补齐原仓依赖后重跑通过；未修改测试断言或伪造平台。PR830正式CI41964626604通过，合并`9f8e1b588bb18d09ce2d299bc7ccc535dc730119`；生产应用和真实页面读回已完成，自然周期未验。

## 身份补充后续最小路径

复用ES已存文件，按确切订单键与站点关联现有订单，提供buyer/uid覆盖及冲突证据；保留原customer_id、订单修订和旧snapshot。UID只作辅助，不以共享UID连接多个buyer。身份补充可独立于buyer精确历史查询推进；全量canonical迁移须有完整订单映射和冲突核实，不能把字段存在当作所有历史已迁移。

PR832已合并`0be9a76887557e6aba02dd56ebd550c3de5c14d6`、正式CI41967943557通过。本轮已应用日更核心身份附加的必要差分，其余生命周期/追踪工具未上线；未切换客户主键。PR831知识已合并，后续规则文档继续维护，但服务器新知识冻结发布及新会话学习未验；全年客户价值重算未完成。
