# 数据治理首个本地候选包

基线 4e31c61ff39064377ce277e3c2dc55c5b7ee5b58，输入为 04 V2.1 完整779行。
本包不是11项施工全部完成，也未发布。用户接受故障后重新采集、放弃部分历史原样恢复；不增加全历史零损要求。

## 已实现的候选

- 用户分析启动默认要求现有完整schema和revision；主库丢失不创建identity、锁或空事实库。新初始化仅显式 `load_store(..., initialize=True)`，不暴露为HTTP/Hermes能力。运行中连接采用mode=rw，避免文件检查与连接之间丢库后被静默重建。HTTP将StoreUnavailable映射为503/recovery_required。
- `user_version_index.py` 在隔离一致性副本上分批展开历史修订的有效区间，checkpoint可续；旧订单按自己的日期/客户/scope索引查询，不用当前paid_at选历史键。原orders/revisions不删除。写入者在原事务推进索引；旧写入者/旧版本使索引revision落后时自动回旧读路径。开关 `revision_range_index` 默认关闭；无schema迁移、自动回填或生产DDL。
- 独立日期合同验证器：半开日期、月末clamp、日历年、源/政策双下界、archive/frozen覆盖与精确版本、未知源拒绝；授权先于capability解析。它不创造真实grant。
- 两指定旧备份的只读metadata盘点脚本，要求显式root，不触网/不读数据库/不删除。没有现场执行。

## 必须继续的工作

1. 当前范围索引实现只解决read_at/orders_at候选路径；仍须在Linux完整回归、真实SQLite版本和一致性副本上验证冻结recipe哈希、额外索引磁盘/WAL/锁峰值、原写入方法集成及schema缺失。迁移每批最多100个revision，但单个既有revision JSON仍是内存单位；不能声称迁移峰值已受行预算限制。历史body会复制到索引，真实增量体积未知，未证明节省空间。需要按测量选择必要投影/引用形式。
2. 生命周期无日期查询保留原语义，仍可能全历史读取。scope参数已在索引底层支持，但上层trusted scope接线未完成；当前不能宣称全链路范围/权限下推完成。真分页/流式导出和小历史锚点未实现。
3. 日期模块尚未接API/UI/Hermes、未发布有效source capability。range_api.py由T3 A拥有，保持未改；真实grant来源必须由现有身份系统提供，不能拿policy代grant。dayMin与365/366现役入口未改。
4. planner/source proof、轻量日事实/修订、query jobs/cache、原timer接入、受引用缓存清理、影子灰度仍未完成；不新增第二套宿主或定时。

## 与T3接口协调

未改hermes-conversation、review-channel、runs_contract、range_api、a2_query_context、hermes-v2-core。后续只协商授权capability resolver与受限工具的输入输出，不改MaterialRunLedger/runner/provider/AI checkpoint。
数据query job状态统一使用queued/running/partial/complete/cancel_requested/cancelled/failed；accepted是HTTP受理语义，不另造隐含状态。frozen按dataset发布allowed_modes；查询filters与缓存filter_hash需同一规范化入口。Hermes既有30秒/10MB外层限制保持，大结果只给job/artifact小引用。上述job/cache条款目前为待实现接口合同。

## 生产保护

PR732已在基线：不恢复全备。PR733已在基线：不改其WAL修复。PR734未在本轮确认合并/生产状态；本包明确不改变FC自动改价及必要依赖的驻留、降频、节流、休眠或资源回收策略。
未合并、推送、部署、迁移、采集、修改凭据或删除生产文件。
