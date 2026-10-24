# RECONCILE-CONTRACT-16：输入拒绝与追加式补偿证明

## 范围与授权

本轮在 `campaign-pr13`、`codex/fs-campaign-reconcile-contract-16` 修复 RELEASE15 暴露的文本输入与补偿登记合同，沿用现有 FS bridge、私有账本、服务端身份及鉴权边界。B 负责实现和统一提交；C 负责本交接及 PR/CI 协调；独立 Q 审精确候选。模型仅记录已指定 Sol6.1/high，不据此声称独立核实底层模型。

当前授权覆盖项目代码、脱敏合成测试、独立 Q、草稿 PR/CI；满足必要 CI、独立 Q、适用代码验收且没有工程阻塞后可按 main 保护合并。**不包含部署、生产业务读取/写入、对账或补偿记录迁移。** push/PR 由主控另行交付精确 commit 与串行 Git 窗口；本文件不授予生产权限。

## RELEASE15 已发生的事实

来源仅为主控本地脱敏回执 `inputs/RELEASE-VERIFY-15-RECEIPT.md`、`final-readback-15.json`、`bridge-text-diagnosis-15.json`；原始完整行、响应正文、凭据和私有数据库不随本交接上传。

- 已部署源码为 PR445 的 `983a3c3c9e9a2ecd7d9029dd8625d731e4e416d3`，发布 ID `nav-20261024T171345Z`；27 目标及 73 静态文件读回通过。运行源码版本与仍为 `campaign-preview-2` 的业务配置快照分别记录，不能互相替代。
- `fs-v3-coupon-1307-fs-bridge-15-edit` 实际编辑 POST 一次，恢复 POST 零次。持久回执为 HTTP200/整数 code1，快照/请求/审计绑定成立；title 严格匹配，brief 期望长度51、实际50，已观察结果严格等于该次期望去掉首个 ASCII 空格。非文本字段及类型保持。
- 该观察只解释该次读回差异，不证明任意 trim、Unicode/HTML/大小写规范化合同。完整严格读回失败为 `NATIVE_STATE_NOT_CONFIRMED`；按原 ID 只读核对后仍 UNKNOWN。
- 独立原生文本补偿于 UTC 17:24:55 执行一次 POST，HTTP200/整数 code1；17:25:24 的独立 GET 确认28字段整行与原备份相同、`changed_fields=[]`，领取/使用为零，时间/status保持。它证明对象已恢复，不证明 FS `benefit_restore` 或 HTTP/UI 管理员写链通过。
- 原15-edit及旧08/11 UNKNOWN、更新时间、三个原账本和 policy 不存在状态均保持。原 publisher journal 的 `applied-awaiting-actual-http-role-acceptance` 保留；G1现场验收仍未完成，购买能力保持关闭。

## 本轮应实现的严格合同

### 1. 派发前拒绝已知不稳定输入

brief 的前导 ASCII 空格必须在原生 POST 前拒绝，持久记录 `rejected`/`not_started`、零派发；不自动去空格、不改用户输入后提交。规则限定该字段与已观察字符/位置，不扩大为所有 Unicode 空白、所有字段或任意字符规范化。title/brief 及完整行读回继续按原合同严格逐字段、逐类型比较；实质差异仍不能确认成功。合成测试应包含无前导空格允许、前导 ASCII 空格拒绝、零 POST、历史原操作不变，以及其他字符/字段未被宽泛 trim。

### 2. 追加补偿证明，保留原 UNKNOWN

补偿是独立追加记录，关联原 operation_id、原请求摘要、原完整快照绑定和特定补偿证据；不 UPDATE 原 UNKNOWN、原 updated_at、请求或审计，不伪装原操作成功，也不删除原对象历史。对已补偿操作的 reconcile 继续返回原 UNKNOWN 并附独立补偿状态，不能再次把它转为 confirmed 或派发。

对象准入只忽略已有完整有效补偿终态的那一条阻塞记录；其他 pending/UNKNOWN 仍阻止新操作。证明缺失、不完整、关联不符或冲突一律不解锁。仅凭当前文本相同、原生 HTTP200、自报 code1 或一份浏览器 proof 都不足以成立。

只读 lookup 保持原 `state:'unknown'`、`result`、`updated_at`，另投影 `resolution:{status:'compensated',reference,proof_hash,recorded_at,original_state:'unknown',native_write_authorization:false}` 与 `object_lock_active:false`。operations 消费者对会话内原ID先只读 lookup；只有该完整、匹配的组合才停止该ID的 reconcile 引导，并单独保留可见历史 UNKNOWN、原结果/时间及补偿引用。无效/不完整组合继续保留待核记录；其他 pending/UNKNOWN 照常锁定。历史摘要不授写权限，新操作仍须服务端重新核准；没有补偿登记按钮或新写入口。

### 3. 信任入口、fresh 对象验证与事务幂等

B 的最小接线合同为可信 Python 方法 `BackendServices.record_manual_compensation(reference, reader_factory)`，`handle`/HTTP 无登记入口。artifact 只从固定 `state_dir/compensation-proofs/<reference>.json` 读取，服务端 `policy.compensation_proofs[reference]` 绑定精确 SHA256；目录 owner/0700、文件0600、无 symlink，并检查hash/schema。批准对象是待导入 artifact 的精确 SHA256，operator 对该证明来源及目标的逐次批准才是信任边界；文件、hash或 policy 本身不自动证明业务真实性。HTTP 请求携带的“已批准 hash/proof”不是批准来源。浏览器不得提供任意文件路径、完整行、凭据或响应正文，也不能从公共/普通 HTTP action 获得导入权限。

v1 artifact 限定已派发的原 UNKNOWN coupon-text 编辑，绑定原 payload hash、完整 snapshot 和唯一 HTTP200/整数1成功 audit；仅接受本次已证明的单个前导 ASCII 空格移除，原title及其他字段严格不变。外部补偿 native payload 只能恢复 original title/brief，且须有成功 receipt 与独立 GET 严格匹配完整 original；不能把一般性“人工已恢复”声明当证明。

导入必须通过既有受信 reader 重新读取当前对象，严格验证站点/对象身份、当前完整指纹及补偿所证明的恢复目标；不能仅使用 artifact 中历史 `current` 快照。原操作、请求摘要、证据 hash、补偿引用唯一性和对象阻塞准入在本地同一事务中核对并追加；同一 artifact 重复导入返回原记录，内容或关联不同明确冲突。并发提交和进程重启不得造成重复记录或重复释放；原 UNKNOWN 仍可按原 ID 查询。

**外部并发限制：原生后台没有已证实的原子条件写入/CAS。** 本地事务和锁仅协调本 FS 状态，不能锁住 Admin/其他系统；fresh GET 到本地事务提交之间仍有外部变化窗口。它不能宣称消除了跨系统竞态。现场须独占对象/无并发维护，导入后再独立只读核对；检测漂移即停，不覆盖、不重新 POST、不用旧快照盖回。

以上是本轮验收合同；实现细节、精确候选及测试计数以 B 的最终提交与 Q/CI 回执为准，本文件不预先宣布代码或现场通过。

## 直接检查与 PR/严格 main 流程

本地 operations 消费者增量已通过 Node语法检查及既有 `app/tests/operations-browser.cjs` 合成浏览器用例：补偿历史跨刷新保留、只读lookup/原ID匹配、严格resolution与锁组合、无额外写入/对账、其他UNKNOWN阻塞、文本转义和损坏缓存拒绝均覆盖。该脚本mock所有HTTP，没有连接原生后台；不替代B最终候选整套检查、独立Q或实际GitHub CI。

1. B 固定最终 commit、文件清单和直接测试结果后，由 Q 对同一候选核输入零派发、旧 UNKNOWN 不变、追加记录、可信批准入口、fresh 读取、冲突/重复/并发/重启、隐私投影及其他 UNKNOWN 阻塞。只用合成数据；不连接生产或读真实私有状态。
2. `tools/pr_fast.py:725` 使用路径 NUL 文件、base SHA、head SHA三个位置参数。沿既有 affected-group 执行；`:750` 的 campaign 组覆盖相关 Node `*.test.*`、publisher/packaging units、backend suite 与5个既有浏览器脚本。Python units 的外网/子进程隔离保持，不为测试绕过或 skip。实际覆盖/数量以当前运行日志为准。
3. 复用同 head/base/输入/环境已有有效测试，变更后只补受影响项；实际 GitHub `pr-fast` 仍必需。CI 的 Python3.9.18、Ubuntu22.04 与离线网络命名空间结果分别记录，不拿本机语法/合成测试冒充生产 Python3.9/Node18、HTTP/UI 写入或部署验收。
4. 主控授予 push/PR 窗口后，核精确分支/head和脱敏 diff，只 push 当前项目分支，创建以 main 为 base 的草稿 PR并附任务 artifact。PR正文说明行为改变、合成验证与剩余现场界限；不提交 inputs 原始资料或私有快照，不改 CI/权限/保护，不直接推 main。
5. 观察本 PR 的 GitHub Actions `pr-fast`，核其 head/base 和成功结论；空检查、skip、失败、超时或缺环境不算通过。按现行保护读取 required checks、review/mergeability 和最新 main；不复用旧 head 绿灯。base变化按组合影响检查；需要变更由唯一分支负责人串行处理，再核新 head。
6. 必要 CI、独立 Q 和适用代码验收通过后，按用户已授合并条件将草稿转 ready，使用仓库允许的正常合并方式及精确 head 防漂移；无 force/delete/bypass。只对已授权该 PR 使用 auto-merge（如确有必要且仓库允许）。合并后读回 merge commit/main 归属。平台拒绝则停止该动作、报告明确理由；不绕过或盲重试。

依据：[HOTFIX](../../../ops/HOTFIX.md)、[既有桥合同](../BRIDGE-CONTRACT-14.md)、`.github/workflows/pr-fast.yml` 与当前 `tools/pr_fast.py`。没有为本轮创建新 workflow；merge 不启动 publisher、不迁移账本、不改变策略或购买能力。

## 最小现场后续建议（本轮未授权、未执行）

1. 后续逐次批准具体发布载荷与原 publisher 计划，重新核现役源、共享变更、保护与备份/CAS；不复用旧包强行覆盖。发布本身与业务读取/导入分别授权。
2. 经单独批准，只读审查原操作及既有补偿证明、原请求/快照/审计绑定、当前对象 fresh 状态、私有权限和其他阻塞操作；原始业务内容留在服务器私有范围，仅返回脱敏结构、hash及一致性结果。
3. 单独批准精确 artifact SHA 和生产补偿记录导入目标后，沿可信本地入口仅追加该原操作的补偿终态，不进行新原生 POST、不换 ID 重测、不直接改SQL清锁，不顺带策略开启或新编辑/恢复试验。
4. 独立只读验收原 UNKNOWN/时间戳/审计不变、唯一追加记录及hash匹配、当前对象仍恢复、重启幂等和其他 UNKNOWN 继续阻塞。生产重复导入或重启也需在明确批准的具体验收计划内，不自动执行。

本地补齐不依赖再次访问已403购买路径；该9条路径继续停止。商品数量/规格、退款行分摊、专属优惠绑定及真实交易归因仍按 [DEPENDENCIES-14](DEPENDENCIES-14.md) 分别处理，不能因本合同或PR合并宣称全部G1/G2签收。
