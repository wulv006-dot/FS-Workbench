# proof有效期/撤销阻断修复（仅本条增量）

基线0c29890已获父独立Linux users282/tiered51通过、无skip，保留一个旧SQLite连接ResourceWarning；独审发现proof过期/撤销合同缺失，故该基线不能作为真实清理或自动重采的接线许可。本补丁不改变users源码、索引、sink或实际删除路径。

## 签发合同v2

proof必需contract=fs-regeneration-proof-v2、proof_id、正整数proof_version、issuer_id、registry_revision、source_revision，以及原dataset_id/scope_hash/source_contract/字段/可再生日期/稳定键/检查项/evidence hash。issued_at、valid_from、expires_at为有限UTC Unix秒，必须0<=issued_at<=valid_from<expires_at，使用时issued_at<=now、valid_from<=now<expires_at；expires_at边界即失效。revoked必须精确False，未知按失效处理。

这些字段本身不是授权签发凭证。host必须注入`resolver(proof_id, binding, now) -> Resolution`：绑定dataset/scope/source合同及当前来源修订、请求日期/字段/mode/phase(plan或use)。它应读取原可信registry的当前记录，验证issuer当前仍获授权、权限/scope/source能力仍有效、proof未撤销且版本仍当前，再返回完整不可变记录。不接受浏览器/模型JSON、固定True或自报fresh作为resolver。

Resolution合同fs-proof-resolution-v1需active=True、issuer_authorized=True、当前registry_revision及完整proof，且与所提交记录canonical JSON逐字一致。live要求authority_kind=trusted-registry且evidence_kind=live。fixture只能fixture-only+synthetic；它只是测试桩，不代表签发权限，切到live即拒绝。缺resolver、异常、未知/撤销issuer、旧版本或来源修订变化全部hold。真实registry/issuer校验尚未实现接线，因此生产依然关闭。

规划记录proof_id/version、registry_revision、issuer、source_revision、到期时间和完整record_sha256。更新记录不自动替换旧proposal：即使proof_id相同，刷新后的version/证据内容必须重新规划。

## 查询与使用时复验

- dry_run/evaluate在对象检查前后分别读取当前resolver和时间；检查期间到期或撤销也不输出候选。
- recheck复用caller原maintenance_lock，执行对象/引用检查及当前proof校验，再比较旧proposal绑定，返回前再次读取registry。它仍只返回dry_run；没有动作或删除回调。
- recovery.decision只提供bounded_plan_required，不是lease。真实source adapter必须在每个有界回源动作前调用recheck_regeneration，核当前registry、时间、相同scope/source修订/版本/记录hash；失败不执行来源请求。当前没有该生产adapter，不能凭一次规划长期继续。
- live默认使用服务端time.time，测试可注入clock。fixture可使用显式now；生产不可暴露clock/fixture开关给客户端。主机时间不可信/字段缺失时fail closed。

本组件不能保证“校验返回后永不撤销”，也不产生registry lease；未来实际执行仍需原宿主在动作边界与registry epoch/lease机制协调。没有新增执行路径，不把当前dry-run eligible当删除授权。

## 直接测试/复用范围

test_eviction_policy现16项：本地Windows15通过、真实symlink1项待Linux；其中新增6项覆盖过期、未来签发/生效、撤销/未知时间、registry/source/scope/issuer变化、缺resolver、fixture不得签发live、检查中失效、使用前失效和恢复复验。使用注入clock，无sleep。CLI仍synthetic-only、mutations=0。
受影响增量Linux包只跑本文件16项；0c29890的users282及未变tiered文件可按SHA复用，不重跑无关91工具测试或明知Windows fcntl失败的全套。新修复未宣称Linux/独审通过。

## owner和操作边界

T3 B已确认：真实identity/grant/epoch、私有artifact及认证下载、range_api与身份传递均原A；数据owner只做user_runtime/members/export内部逻辑、policy/planner/预算/checkpoint消费与故障测试。Hermes/UI/维护锁按原fileowner+A窗口。当前没有实际接线，不以伪epoch补通，不改safe.directory或系统权限绕过B的所有权拒绝。
用户仅条件允许最终相关测试/独审通过后push独立分支+draft PR；父任务通知条件满足之前不推送。没有merge/mark-ready/deploy/delete授权。本补丁无生产连接、无新schema或后台任务，两旧backup仍未动、释放0。
