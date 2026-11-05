# 用户分析日更与身份字段接入

## 本轮结果与边界

用户于2026-11-05明确要求恢复日更。本候选使原用户分析流水线每天补齐已完成日，再原子发布最新完整结果；未完成时保留上次发布。它不更改客户生命周期、付款/退款口径或客户主键，不宣称buyer_id身份迁移已经完成。

## 已核实际状态

- 生产 `user_jobs tick → user_weekly.wake/run` 当前是周更，不是采集故障。原15分钟唤醒保留，实际工作窗口04:18至05:00；完整周成功后其余自然轮source_calls=0。
- 订单事实已在 `/var/lib/fs-user-analytics` 按订单ID去重存储并保留修订；不是每次查询全量重新下载。旧订单退款、状态仍可能变化。
- 原每周90日修订、最旧日轮巡、历史缺口回补、定向旧订单复核已有实现。本候选保留这些能力：平日补新/缺日，周一保留90日修订。
- 自动整库备份已按此前授权退出，现为on_demand_only。本候选不恢复每日整库复制，也不删除旧恢复点。
- 普通Order/index实返uid，尚未见buyer_id；历史ES导出实返buyer_id和uid。2025-09-28文件1835行，两列已确认。新字段原值为不透明文本，不假定数字。
- 一次 `downloadsMake` 仅时间加buyer_id、未加游戏条件的试验仍返回全日1835行。这只能说明该请求组合未筛中，不能推断带游戏条件也无效。完整组合由客户价值线继续核实。

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

2026-11-05生产只读核对：9目标中8个与本候选main基底一致。`user_query.py`生产尚未部署main已有的member_keyset/streaming-export候选；本次生产文件须在精确当前版本仅应用3处cadence接线，不整文件携带未部署分页能力。实际before/after哈希在私有`target-manifest-candidate.json`，releaseReady=false。

发布、真实页面/工具读取、自然日周期由主控统一验收。不能用构造时钟或人工补采冒充自然日验收。

## 验证

183现有Python3.9.18隔离容器，无网络、只读根、0.25CPU/256MB：用户分析293项全部通过。包括失败日与完整日交错、跨日续旧周任务、周一90日修订、ES前6日复用和只补末日、标签未齐不发布、同日幂等、旧snapshot回放及既有权限/存储测试。UI日期4项、JavaScript语法及git diff检查通过。

首次整套运行因打包遗漏原宿主源码/服务文件出现5项FileNotFoundError，补齐原仓依赖后重跑通过；未修改测试断言或伪造平台。正式CI、合并、生产应用和自然周期尚待后续回执。

## 身份补充后续最小路径

复用ES已存文件，按确切订单键与站点关联现有订单，提供buyer/uid覆盖及冲突证据；保留原customer_id、订单修订和旧snapshot。UID只作辅助，不以共享UID连接多个buyer。身份补充可独立于buyer精确历史查询推进；全量canonical迁移须有完整订单映射和冲突核实，不能把字段存在当作所有历史已迁移。
