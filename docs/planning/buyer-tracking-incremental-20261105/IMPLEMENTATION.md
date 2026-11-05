# 用户分析日更与身份字段接入

## 本轮结果与边界

用户于2026-11-05明确要求恢复日更。PR830日更代码已上线，使原用户分析流水线每天补齐已完成日，再原子发布最新完整结果；未完成时保留上次发布。真实页面已读回，下一自然窗口2026-11-06北京时间04:18—05:00尚待验收。它不更改客户生命周期、付款/退款口径或客户主键，不宣称buyer_id身份迁移已经完成。

## 已核实际状态

- 生产 `user_jobs tick → user_weekly.wake/run` 已切换日更。原15分钟唤醒保留，实际工作窗口04:18至05:00；同一日发布成功后其余自然轮source_calls=0。旧周快照的日期与cadence不改写为日快照。
- 订单事实已在 `/var/lib/fs-user-analytics` 按订单ID去重存储并保留修订；不是每次查询全量重新下载。旧订单退款、状态仍可能变化。
- 原每周90日修订、最旧日轮巡、历史缺口回补、定向旧订单复核已有实现。本次保留这些能力：平日补新/缺日，周一保留90日修订；不是每天重拉全历史。每站点原最旧日轮巡/历史回补各有界推进一天，旧订单按既有ID与付款窗口定向复核；这与新日入库分别记录，不把退款与成本永久冻结。
- 自动整库备份已按此前授权退出，现为on_demand_only。本次不恢复每日整库复制，也不删除旧恢复点。
- 普通Order/index实返uid，尚未见buyer_id；历史ES导出实返buyer_id和uid。2025-09-28文件1835行，两列已确认。新字段原值为不透明文本，不假定数字。
- 已核完整 `downloadsMake` 日期+FC26游戏`gid=833`+`buyer_id`组合：返回187行FC26订单，只有1行为目标buyer。游戏筛选有效，但此顶层buyer参数未筛选；不能用该响应当客户全年历史。ES列表当前授权身份返回业务401，未绕过。
- 日增量无需buyer筛选：按日期取得新/缺日订单，按确切订单键幂等存档；已有ES文件中的buyer/UID可关联订单。buyer精确查询缺口影响按客户回查全年历史，不阻塞每天补昨日新单。用户已确认可接受该筛选缺口，优先历史留存与日增量。

## 最小实现

复用 `weekly-work.json`、meta `weekly_publication`、既有jobs锁和CAS，不新增状态机或定时器。旧字段名继续兼容，publication增加cadence=daily；没有cadence的旧周快照按weekly解释。

1. 每天原窗口使用当天零点为截止，逐日检查完整coverage；缺失日补采，不用最大日期冒充连续完整。
2. 已完整新增日可复用；每周90日修订仍要求本批抓取时间，避免把待复核旧日当新日跳过。
3. ES标签沿原归档读取，默认展示最近7个完整日；只为缺失日期生成原导出任务。跨月不重抓已覆盖月份。
4. 原周任务若在途，先以原任务截止完成，不改ID或改成日任务；下一自然轮再推进日截止。
5. 订单coverage和标签齐全后才发布。数据页、下钻、导出、Hermes与A2继续共享同一冻结snapshot/data_version。
6. 同日成功后不打开Store或调用业务源；失败续跑保留游标和上次已发布结果，不显示虚假新截止。

## 精确发布范围与保护

仅 `/opt/fs-hermes-fc/` 的 `user_weekly.py`、`user_runtime.py`、`user_jobs.py`、`user_query.py`、`user_customer_types.py`、`user_tools.py`、`a2_query_context.py`，以及原用户分析静态目录的 `index.html`、`users.js`。沿原publisher、CAS和备份回执，不改服务timer、权限、价格、广告、ES Cards解析或共享来源。

本次部署保持9目标精确范围。`user_query.py`以生产363f7972来源仅应用3处cadence接线，不整文件携带main尚未部署的member_keyset/streaming-export能力。实际组合178项回归通过；before/after哈希留私有清单。

主控于2026-11-05沿原stage `/opt/fs-release-stage/user-daily-7312aa31-v1` 发布，原发布ID `nav-20261105T052700Z`，备份 `/var/backups/fs-navigation-20261006/nav-20261105T052700Z`。apply退出0，9目标SHA读回全部一致，host-runtime为all_readers_loaded，Range/Hermes均active且健康。最终manifest SHA为`006f87c82fa253c4644682685cda5df2c42fbca738cddb105678c39011d6607c`。

此前等待中的只读inspect已结束；业务锁自然释放后重新capture发现仅`.curator_state`与`.usage.json`动态内容变化，9目标及其他保护项不变。旧plan/manifest保留为`*-before-dynamic-review.json`，只复核两动态hash后沿原publisher执行，没有取消锁保护或替换业务任务。

Chrome真实`/dashboard/users/`已显示“每日更新”，4917人及原快照正常可读；旧快照仍为weekly、截至11月1日、旧next为11月9日，未伪造新冻结结果。下一自然日周期单独验收，不能用构造时钟或人工补采冒充。

## 验证

183现有Python3.9.18隔离容器，无网络、只读根、0.25CPU/256MB：用户分析293项全部通过。包括失败日与完整日交错、跨日续旧周任务、周一90日修订、ES前6日复用和只补末日、标签未齐不发布、同日幂等、旧snapshot回放及既有权限/存储测试。UI日期4项、JavaScript语法及git diff检查通过。

首次整套运行因打包遗漏原宿主源码/服务文件出现5项FileNotFoundError，补齐原仓依赖后重跑通过；未修改测试断言或伪造平台。PR830正式CI41964626604通过，合并`9f8e1b588bb18d09ce2d299bc7ccc535dc730119`；生产应用和真实页面读回已完成，自然周期未验。

## 身份补充后续最小路径

复用ES已存文件，按确切订单键与站点关联现有订单，提供buyer/uid覆盖及冲突证据；保留原customer_id、订单修订和旧snapshot。UID只作辅助，不以共享UID连接多个buyer。身份补充可独立于buyer精确历史查询推进；全量canonical迁移须有完整订单映射和冲突核实，不能把字段存在当作所有历史已迁移。

PR832已合并`0be9a76887557e6aba02dd56ebd550c3de5c14d6`、正式CI41967943557通过，但身份补充尚未部署。PR831知识已合并，服务器知识发布及新会话学习未验；全年客户价值重算未完成。本次文档收尾不发布这些内容。
