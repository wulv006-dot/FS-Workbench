# 第五包：持久检查点、artifact与兼容边界

新增query_checkpoint.py、query_artifacts.py、test_query_checkpoint.py；修改range_jobs.py的显式checkpoint/recover钩子。复用原Archive/catalog，小表保存job元数据、订阅与追加结果行；不会每页向DB重写以前的结果行。检查点元数据最多64KiB、job32个、订阅1000个、每job结果8MiB；校验预算时仍需序列化有界结果，CPU成本不是O(1)。容量满明确失败，生产宿主需沿现有保留规则回收，当前无自动删库/缩库。

每个源页调用前原子持久化请求预算 reservation；保存失败不调用来源，标checkpoint_unavailable，不能成功返回缓存。源页通过字段/水位/预算检查后，结果追加与cursor/状态/订阅同事务保存。重启load保留generation/固定scope/policy/watermark/source_contract和已消费预算；recover要求原secret派生key一致、现行grant仍有效且host确认同水位来源可恢复，否则停止。中断只读页可在原cursor/水位复读，不扩窗，不恢复Agent/MaterialRun/改价行为。

此版本使用同进程原宿主锁+SQLite事务；未实现多宿主CAS/发布锁接线，不可启动两个独立runner消费同一个job。真实source支持的稳定水位仍未验证。没有新线程/timer/服务或生产注册。

artifact是现有Archive root内query-artifacts生成的有界JSONL，按完成结果页流式写，最多8MiB；不是user_query.members的数据库keyset改造。写入前/每页/发布前复验权限，下载每chunk再核授权/取消/epoch/水位generation/到期；manifest记录hash/bytes，结束校验。下载lease持有pins，关闭生成器后才释放。过期仅列候选，未删除。进程死亡可能留下保护性pin，当前没有已验证的dead-reader lease回收；不能简单清零后删除。正式报告/recipe引用pin接线也未完成。

## 第四包窄审缺口关闭

- planner携带可信field_contracts；默认全部请求字段required且不可null。明确optional/nullable/type才放宽；缺必填不能complete或完整cache。source_contract升级必须伴随字段语义变化，不能复用旧缓存合同。
- page严格只接受null或非空签名字符串；0、false、空字符串、list/dict均invalid_cursor，不再作为首页。
- 新增2项反例通过；新增持久化/artifact6项通过（包括失败checkpoint不触来源）。第五包完整独立测试38项通过；均本地合成，无真实源/客户/模型/生产写。日志在任务目录fifth-pack-tests.log。

## Python3.9 / SQLite3.7实际兼容证据

11份候选source用ast.parse(feature_version=(3,9))通过；源码常量SQL未发现UPSERT DO、RETURNING、window或STRICT依赖，未使用partial index。使用基本CREATE/复合索引/INSERT OR REPLACE/BEGIN/参数化SELECT；这不是对运行期全部API的形式证明。
2026-11-01沿原187脚本运行仅sqlite3.connect(':memory:')的小探针，Python3.9.18、SQLite3.7.17，15组候选源码DDL成功；未打开任何生产库/文件/服务，未安装升级。前两次生成探针分别误用execute执行多语句、误纳入测试fixture重复建表而失败；纠正为仅source+executescript后本地预跑及现场通过。最终任务目录server187-compat-result.json。该探针不覆盖URI/WAL并发、artifact文件权限或完整查询/恢复行为，不能据此发布。
固定c079b3b云Linux265+14回执不覆盖本包；新包仍需独立审查与相同提交Linux/目标SQLite行为验收。

## 接线与删除边界

默认仍无生产调用。现有宿主应显式initialize候选schema、注入同一原锁/可信grant/固定adapter/Checkpoints.save，reload后调用recover(resume_allowed)。每个真实source必须先证明稳定水位与失败分类；不支持恢复的来源明确终止，不盲继续。
artifact只在授权结果内生成，不能给任意文件路径或上传/编辑T3材料。cache/过期候选未自动删除；保留recipe/L0/主库/key/Excel与两旧备份原保护。187两不可读fd、30日回执未复演/验签、0释放的现状保持。
