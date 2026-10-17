# 按需看板的轻量巡检适配

旧两小时快照采集退役后，原Hook仍按current.json年龄报警。只适配活动hooks.py：复用既有fs-query-v1-20261012 query_api.snapshot()的metadata-only目录调用和原服务身份，核catalog ID/合同/币种/时区及空财务值；查询服务health沿原严格合同核验。不做周期财务查询，不用catalog.generatedAt宣称数据新鲜。实际财务值的新鲜度由具体日期查询的来源capturedAt/TTL合同负责，本探针不冒充该项验证。

新版目录不可用或契约不符时停止判健康，不退回旧健康财务快照冒充；旧完整性探针保持，将合法旧快照标historical_only。看板错误独立于FC门禁；FC保护及RPG共享can_resume规则不改。

沿原monitor publisher --upgrade增加明确scope的固定单hooks文件分支，原其它模式函数AST保持。复用原noncore_swap、collector锁、CAS、备份、元数据/目录fsync、失败回退；不改monitor数据目录权限或重启业务服务/timer。原publisher常规升级仍为固定五文件与35检查，本新范围只跑冻结7目录检查；另4项直接publisher检查覆盖范围/保护漂移/rename后失败/其它模式保留。AST比对使用跨Python版本稳定字段表示，期望只由冻结原publisher生成，字节常量保留。

Windows/Linux11项直接检查通过，Linux无skip。11:43:09已发布，真实入口返回17目录queryable/data_freshness=not_observed_no_business_query，旧合法快照为历史；九项核心SHA、六服务PID保持。精确来源/备份见SOURCE-MAP.json。是否退役旧采集timer由按需迁移任务按其真实消费者验收决定，本增量不修改timer/旧快照/业务数据/价格/权限。
