# 实交数量原始证据保留修复（2026-10-23）

已修复并上线现有发货采集器的字段丢失。真实FS准确日GET完成后，新档案包含原始游戏、数量、赠送、成本单价；原金额核算和价格规则不变。这是原始证据层验收，不是全历史数量回补、套餐结构或所有Hermes工具数量投影完成。

## 根因和范围

原channel_cost_source.collect已读表格19列，但落盘只保存delivery_id/source/sn/trade_at/cost_total/sale_total及genre，丢弃game/qty/gift/cost_unit。只扩展这四个原字段的保存白名单；空数量/赠送仍为空，不补零、不从成本反推；不保存供应商、收款人、经办人或备注。源记录ID/日期/站点/分页一致性/去重和完整窗口替换原校验保持，旧档案不伪造数量。

实际调用者是channel_source.enrich和channel_cache.cache_day，通过原完整发货档案及channel_cache.cost_index核成本；delivery_index仍只按原实际成本核金额，不据新增数量改变财务。原始字段是交货记录，不能冒充订单购买套餐数量、价格暴露或全部退款实结。

## 检查、合并和发布

PR375最终head8e9f465075082f459f9e32d0907559ed185fa8f9，合并bcbb4f91abcc36eec84ece5cd239dd4204ce9ce0。正式pr-fast39879190321/job120172161221成功，合并前精确head/base/clean闭合。原8a29 CI成功；main推进后合入PR376再完成新head正式CI，测试文件原CRLF保留，最终3文件38增1删，不覆盖他人工作。

实际生产range使用/opt/python39/bin/python3；该环境19项归档/缓存及39项金额消费者检查通过，包括非零赠送、空数量、归档保留及原成本索引不变。Windows默认Python和服务器备用/usr/bin/python3缺lxml，原失败保留，不称双Linux全通过。服务器默认Python还缺SSL；/opt现有Python的SSL/lxml实际核实可用，无安装依赖或替换全局Python。

原publisher release nav-20261023T004250Z，manifest7043be2ac7d06cacb510bc5cbf483a3a80473e0f58635be64240ebeea4eb4020；stage /opt/fs-release-stage/fc-delivery-fields-8a29aea06ab9，1目标/185保护共186SHA通过。目标/opt/fs-hermes-fc/channel_cost_source.py：7f3de5bc4dce1c1c048e56bb12f7fc0ac5a133e79f2f857e31686cae7b8ad015→91403f8295ddc32762fded53bea551a1660d4b258bf6c2bfc3b2429f2d45b0ec。

首次inspect在写入意图前因并行user_config源变化拒绝；没有发布意图、备份或目标写入。按原PR376/源b82d2faf、nav-20261023T003639Z及原manifest原字节f62e65be…/journal33d211c6…核正式CI与所有目标，叠加保护其10处更新及新backfill_history.py后沿同一候选继续，未回退用户分析。最初monitor-only清单缺运行时元数据，隔离准备失败亦保留；运行时image/runtime合同从原生产manifest读取，未把monitor-only当发布包或改旧SHA。原CAS、备份、原队列/发布锁和回退机制保持。

原publisher刷新FS worker/range接线，未重启FC采价/写价服务、未改变定时或开关。08:45真实监控186SHA无漂移、v15核心1c586eb4、rev40/on/auto/120/min10、queue0/incomplete0/timer active；现有公开价格回执matched，仍是原16:21写入身份。没有新采价/模型/价格写入/清缓存；下一原自然08:46:33，不提前或重放。

## 真实原入口验收

使用原FS /channels准确日GET，未带强制刷新、未建采集器或调度。08:43:48返回原缓存并正常refreshing，08:44:49原刷新结束、sourceError/costError均false、stale=false。订单收入08:43:56、成本生成08:44:20，实际成本窗口截止08:42。完整分页完成不等于所有订单身份齐：ES仍07:11，当前188个FC订单中135识别Coins、30缺ES身份，按原OPEN事项继续，不能补零或把旧身份覆盖当实时完整。

重新连接07:08已冻结的原三PID订单和原全局去重交货档案，今晨00:00–06:59的92笔纯单品已完成毛利覆盖订单，原数量字段齐：
- PS：50单/50交货行，数量48673K，后台赠送列0，game为FC 27 ▶PS。
- Xbox：25单/25行，数量16460K，后台赠送列0，game为FC 27 ▶XBOX。
- PC：17单/17行，数量14807K，后台赠送列0，game为FC 27 ▶PC。
- 合计79940K，仅这92单，不外推所有127单、未完成或混合商品订单，不以订单数代K。

单位K沿用户确认的Order交货口径。后台gift列0仅是原字段事实，不代表前台无赠送；不能再把前台5%统一加到这些实际交货记录。昨天同窗仍有缺数量及跨平台交货标签，不能宣称K同比、自动重分平台或拿未知补零。未重写昨日不可变档案、未强制重导出，未来沿原回补与准确窗口正常更新。

FS order_costs工具的package_quantity仍指未保留的订单套餐结构；本次只补原始交货字段，并未新增每个Hermes工具的数量聚合能力。历史平台/套餐身份、退款实结、Coins同范围Ads/流量仍待核；不据这次证据层修复修改毛利红线、定价公式或热度系数，不称净利润或策略因果已证明。

## 最新调度与同步边界

用户在本轮执行中要求持续监测改为每日一次；同一fc-coins-v2已改为北京时间每天07:30并读回，名称/目标Work/ACTIVE保持，不另建任务。服务器120分钟及每周Astra周一10:00不变，旧小时监控说明已从当前USAGE/观察合同清理。

Notion详细运行与经营验收追加被自动审批拒绝，原因是该具体敏感运行数据披露未获单独授权；未写入或用链接绕过。仅同步已授权的通用取数口径，不含服务器、发布或具体经营数字，task_54e6a8e740864def9201c91655bdb029 succeeded，最终读回另核。详细证据保留于原受控档案，本条不代表Notion详细验收已同步。


## 原自然周期后继验收

原08:46计划任务dfcafcc0-9aef-4da0-8f6b-228a52df8b59实际08:47:23启动、08:50:40 ready/no_price_change；预览8d9c1344-a298-4526-8bdb-ef12fcd1c0b8于08:50:36通过。三平台独立公开08:48:54–55仍9.84/9.84/8.68美元/100K+5K，无execution/清缓存，原16:21价格身份保留。原task c4078db7/run_e7ab3af6有7次实际provider high/11工具、v15核心1c586eb4和1.0.9方法实际输入、推荐规范化报价哈希闭合。

双红线仍被实际采用；但模型继续混用未优惠单均毛利及七日留存估算的保本口径，声称让利$0.47需增量18%。若指100K标价下调$0.47，同一R和成本下应增量22.83%；若指实收让利，则需另按实收下降计算，不能直接沿用18%。时区标注及把单日波动一概排除仍错，不能称稳定掌握。没有新增同题教学模型、经验发布或自动回滚规则。该原自然终态不依赖此次原字段修复自动投影到模型工具，不能宣称Hermes已读取新增实交K。

私有原回执latest-natural-005316-private.json、new-cycle-model-audits-005328-private.json及delivery-fields-readback-20261023T004723Z-private.json保留。当前日监控调度已读回，旧小时频率不再生效。
