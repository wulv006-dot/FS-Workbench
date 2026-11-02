# 第六包：原用户分析数据库keyset/流式导出候选

本包修改user-analytics source/user_query.py与user_http.py，新增user_member_index.py及tests/test_member_keyset.py。未改A/B/range_api/runner/provider。工作树开始无dirty，已知本地其它活动分支是campaign UI，未在此分支发现并行user_query修改；未尝试进入已拒绝的T3工作树。

## 最小模型增量与真实分页

原recipe只存算法/flags/input revision，不存在可直接按客户读的分类结果，因此单给原数组分页加cursor仍会全量read_at。候选在原customers.sqlite3显式创建3张派生表与3个筛选索引：内容寻址掩码record正文、snapshot/group签名manifest、group内ordinal/ref/分类索引。必要历史投影与执行事实分开，不删除orders/revisions/identity/原recipe，不复制raw响应或新建数据仓库。

在原Service.query已经为卡片算出private结果后构建索引，不在members/cache MISS隐式回放。record正文以hash复用，同snapshot重复构建不增正文；不同snapshot相同正文复用。snapshot/group引用仍会随必要冻结版本增长，当前未测生产增量空间，不能宣称此索引减少主库大小。首次卡片分析和建索引仍依赖既有全量/日期读取，尤其生命周期全历史路径尚未优化；本包只证明后续分页/导出有界。旧snapshot无索引时明确503，只有显式隔离影子构建才可补，不偷偷全量replay。

默认member_keyset_index未启用。开关属于宿主store.config，不改冻结算法config。启用前显式initialize schema，并注入真实permission_epoch及export_sink；缺任一返回未就绪。原默认路径/原recipe算法保留。没有部署或生产DDL。

Service.members启用时不调用private_snapshot/read_at，而是在DB按(snapshot,group,ordinal>last)及原repeat/type条件用索引读limit+1，按ref只取本页正文。原成员顺序保存，不改成字母排序。total来自构建时精确去重后的签名计数，不能将日distinct相加；原unknown包括conflict、None不冒充unknown的语义保留。构建拒绝重复CID、与冻结recipe/private hash不符的输入；选中正文/hash及行映射签名校验。游标签名绑定snapshot/revision/筛选/owner hash/permission epoch及已消费数，非法类型/换筛选/换owner/换epoch拒绝。最终页与导出计数必须吻合manifest，不把缺行当完整导出。

Service.export启用时必须由注入的原导出宿主消费export_iter。迭代器直接取数据库200条一页、每页重新授权，不创建完整rows数组；固定snapshot/revision/filter/epoch，预算超出/撤权/缺输入立即失败，不能返回complete receipt。sink未完整消费也拒绝成功。当前没有给A的HTTP/UI新增stream/artifact接线，未配置sink时503而非沿旧全量导出；默认关闭确保旧入口不变。member_export_max_bytes为可信服务端预算，默认8MiB、最多512MiB；超出应交原宿主异步导出策略，用户不能自行提高。

## 本地证据

test_member_keyset：10项本地通过、1项需真实POSIX的writer/recipe集成在Windows跳过（统一云包必须无skip）。覆盖原Service方法不触全private/facts、精确筛选total、顺序/旧修订隔离、cursor/撤权、真正迭代sink与不完整sink拒绝、去重正文、无索引不回放、缺成员不假complete。真实writer测试使用原replace_window、日期移出10月/退款，并对旧recipe与索引逐字段比较，不用新的fixture变更方法冒充。
固定第一页limit3，成员20→20000，SQLite VM步骤550→550，返回仅3记录，total20000。只证明合成索引分页成本，不证明首次分析/索引构建、百万行、生产RSS/WAL成本。所有输入为example.test/opaque合成数据。

## 第五包P1及pin安全补充

7661c98修复旧generation晚返回覆盖新checkpoint：Engine成功/异常回调和save先核当前job；DB用generation+revision条件UPDATE，替代必须提供明确previous_generation/previous_revision，同代旧revision也拒绝，插入/追加/元数据/订阅同事务。resume_allowed必须严格True。
测试含迟到成功/失败×新queued/complete/cancelled六种交错、直接旧代/同代stale save拒绝及恢复；同Engine同锁复现通过。原先有一旧测试在恢复后继续使用旧Engine写入，CAS现在正确拒绝，测试改为使用恢复后的Engine，不放宽CAS。

artifact增加可选machine/boot/pid/start lease。正常下载lease/pin同事务、关闭stream后删除自己的lease并减pin。abandoned_pin_candidates仅在artifact过期、lease数与pins匹配、全部精确进程实例被host证明死亡、引用扫描明确unreferenced时列dry-run证据；live/unknown/legacy无lease/正式引用一律保护。没有自动清零pin或删除，真正回收必须在原宿主锁重新校验；liveness与正式报告引用resolver尚未接线。新增检测fixture通过，不将年龄/PID不存在单独当死亡证明。

## 统一Linux验证与兼容范围

第五、六包及CAS修复将统一固定包提交父任务一次验证。原c079b3b云Linux265+14不覆盖本包。新POSIX用例必须实际运行且无skip；不重跑无关91项收尾工具测试。
新source按Python3.9 AST解析通过；现场SQLite3.7只做:memory: DDL/CAS探针，不冒充完整功能/文件权限验收。旧第五schema若曾在离线副本建过，需显式重建/迁移；CREATE IF NOT EXISTS不能给旧range_query_jobs自动增加revision列。生产从未启用这些候选表。

当前剩余：真实source/grant/维护锁接线、旧快照显式索引迁移/空间与recipe shadow、前端同policy、可再生proof/受引用清理dry-run、恢复与精确发布清单。候选没有触生产文件，旧backup释放仍0。
