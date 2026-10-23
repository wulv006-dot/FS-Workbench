# 重启释放与零改动误报修复

2026-10-23用户明确要求两处修复上线并按原自然周期验收。活动源为 `fc_restart_release_recovery_20261023/` 与 `rpg_zero_write_recovery_20261023/`；不拿早期根目录覆盖现场。

FC恢复缺口：原生命周期重启后只检查连接，不调用最终文档替换释放器；startup仍打开商品页，Worker可长期驻留。现复用原采集器的同context准备受控idle后关闭旧商品文档，再核浏览器级Target.getTargets。仅在原队列/重试锁及Order耐久隔离证明下，对同一原恢复事件、同一容器新StartedAt做一次释放；释放未知先读回，已idle不重新关页。高内存原reload分支也复用真实释放器，原PS-only/采集器不改。新事件只带本次事实及重启冷却，不再继承14:30旧验收给17:15事件背书。探针新增失败阶段分类，不输出页面、会话或秘密。

18:46:39首版9cf之前的2f625d上线；原分钟tick发现复用helper默认9223与实际9225不符，URLError回执保留。18:48:48修为当前9cf301e2，原tick18:49完成文档替换但异步页对象使首次身份读回未确认；18:50:07同原事件只读核定idle_release，不再次重启。独立真实CDP：1context/1owned idle/全局Lootbar Worker0。两次发布均原publisher/CAS/备份，未重启业务服务、未触发采集/模型/写价；53项Linux回归通过，其中35项原边界及新增/继承场景均实际运行，不称生产故障注入。

RPG18:52:14发布：保留wanted意图，物品零写且全目标复核成功新增noop/实际cache_required=false/原因；监控必须原ID与finished阶段、严格整数零计数、非空目标、无mismatch完整证明才消除此ID的缓存误报。UNKNOWN/partial/缺证/真实缓存失败保留。原DB/outbox/原结果不改、不补缓存不重放。当前监控rpg_unresolved已空，原触发exit0；真实群恢复回执及下一原物品轮另验。现场两次并行readgold/金币改动均保留，3ade→1992由函数级生成器及全文件CAS绑定，40项Linux通过。

17:14原日志：17:13:38真实CDP健康/容器726016000字节；经营事务原timer17:14:04启动，primary_reader仍在FC容器经9226(socat→9225)共用FC Chrome。17:14:38真实CDP失败/936480768字节；17:15:38第二次失败后原自动恢复17:15:43重启，事务进程同时报container_reader_failed_137。原17:15事件unknown，17:16同ID恢复，无重放。无新增内核OOM证据，不把137倒因为起因；订单读取和失联时间重叠及恢复连带杀读已证实，具体Chrome分配/阻塞函数未取证。继续核该残留依赖并准备真正隔离，不能仅改容器名或把9226误当独立Order浏览器。

18:53新增独立Order8768健康503/order_probe_unavailable/login_attempts0；Admin8767正常，原Hermes链已报该真实异常，正在核查，不以零误报修复掩盖。价格rev40/ON/auto/120min/v15双10%及原失败/UNKNOWN保持；约19:02原FC与后续原RPG物品轮为真实验收，至少12轮昼夜内存与7天策略观察仍OPEN。未制造采集、模型、写价或故障。
