# Dot 专用只读身份

最新r4（13:16）：改密页面静态修复已上线并读回；角色变更待用户核定，新身份使用/接管暂停。页面真实私密改密尚未验，原Work观察及服务器周期保持。详见[当前交付](DOT-ACCESS.md)。

状态（12:27）：代码已受控上线，专用身份已创建，服务器真实HTTPS允许/拒绝及同会话权限撤销通过；Dot私密登录交付和云端接管未完成。以下r3实际回执覆盖r2旧提案中的“未创建/待授权”。

授权依据：老D原任务转交2026-10-22 03:44UTC用户“允许”，消息Sentinel_367f8b7d98348191b686d6b54b2f3033，目标dot_fc_observer及精确FC状态/监控/报价和已审查的任务状态；本Work唯一实施。对端主对话在本工具未返回历史正文，保留转交的原问题、答复及消息标识，不冒称独立读到用户原页面。

沿现有HTTPS、IAM/RBAC、普通会话与原publisher；不新增端口、认证协议、全局TTL或长期自动续期。原本机观察继续，服务器仍为唯一业务执行方。

## 权限与数据

专用身份只接受精确GET /api/fc27/cloud/automation、/monitor、/pricing/state及/jobs/合法UUID。任何查询参数、其他路径、非GET和deploy通道拒绝。登录/登出走原门户私密流程，登录后直接返回上述JSON入口，无需开放全站首页、IAM控制台或全站静态资源。

新增FCObserver角色只授现有coins:view，先对该主体限制精确GET白名单再映射coins资源，不能据此读取其他Coins页面/接口；主体显式拒绝edit/execute/deploy/manage。不授Viewer、Auditor或unmapped-wide；删除该主体绑定会拒绝，不能回落Viewer。IAM故障回退也对该身份拒绝，其他用户和现有资源目录保持原行为。

API针对该专用身份投影白名单：配置状态、源时点与报价成本/FX/平台数值、原任务/模型回执ID及终态、原写入/公开读回身份与时点。排除原始request、客户/订单明细、模型正文/建议全文、凭据、原始配置、无关Players状态。jobs仅接受Coins原auto_cycle/collect/execute/restore/recalculate/preview/hermes_review种类；不公开其它任务或任意账本。后续字段默认不转发。POST在读body或调用任何业务函数之前拒绝。

这份投影不是全量经营或利润核验工具；平台/售K、营销归因和完整退款缺口不能据状态接口补齐。failed不等于未写，Dot只报原ID，由当前负责人核原audit/reconciliation，不向该身份开放写入或重放。

## 凭据与撤销

只在现有认证源存储密码哈希；生成/验证过程不把密码、token、session写入消息、Git、Notion、TXT或本地交接。不复制已有凭据。实际登录通过原门户及产品私密表单，不能把账号创建或一份token样本称云端全天候已接管。

本Work尚未取得可安全跨给Dot的vault入库工具。若没有已验证的私密交付通道，保留交付阻塞并报告，不能改用明文文件。可由用户在现有IAM成员管理的私密密码框为该主体自行设定密码，再直接输入Dot的产品安全登录框；须实际确认该入口及登录结果。

撤销保留主体绑定，追加coins:view显式deny并在实际认证源禁用；不能删除绑定作为唯一撤销。验收须旧会话访问目标GET返回401/403，恢复授权也保留审计及同主体原ID，不轮换全局密钥。普通会话配置12小时不等于无人值守续期能力。

## 验收分层

候选代码、本地检查、正式CI、merge、原publisher上线、主体创建、真实允许/拒绝与旧会话撤销、安全登录交付、云端持续调度和唯一责任切换分别登记。未做的保持未执行，不把测试、merge或HTTP200冒作正式接管。

## r3 实际回执

- PR335 head a453794c89e3ad2eb897e9bbc861a6d7cbc0cbd1、merge3552cd2b4f36c25b49cd146ec0e3ce56c12fdac4；正式PR fast39720127576/job119631428801成功。本地FC68，双Linux各IAM22/控制台30/FC68通过。
- 原发布检查因access_policy属于旧Hermes“不变消费者”而拒绝，未切生产；PR336以精确四目标/唯一新增模块为前提，将获准目标转入原beforeSha256/CAS，其他保护与冻结publisher不变。head81730879e4d0a5d134c0f976c9457accd7ced8cc、merge3a240f86efae5ff167a2c075e0076f642e598aa3，正式PR fast39720689560成功，新增8项本地/双Linux通过。首次QA资源冻结失败及deploy依赖缺失保留，未放宽断言。
- 原publisher nav-20261022T041407Z，manifest a2eadf3b76501b30c2f1e018f8d72e24424c756aa65613f24c10902eb1486673；4目标/134保护，共138个SHA吻合。只重载auth-portal和FC API，价格/模型/周期写入0。原备份/var/backups/fs-navigation-20261006/nav-20261022T041407Z；没有改全局TTL、端口、认证协议或服务器数据库格式。
- dot_fc_observer已在原native命名空间互斥下创建，权威密码沿原管理器保存为PBKDF2覆盖值；主体enabled，account version3；IAM generation13，角色FCObserver/coins:view及四写动作显式deny。比对变更前策略，其他角色/绑定及内容保持。
- 12:22真实HTTPS四GET均200且返回fc-observer-v1投影；全站首页、D4、IAM管理页、查询控制、完整quote账本及三个POST共8项均403；未触发业务写入。保留原a5914831自然job，无新模型调用。
- 对同一实际登录会话添加coins:view显式deny后真实403（热加载观察到200、200、403），随后恢复原获准范围同会话200；不删除绑定。权限撤销实测通过，不承诺瞬时零延迟。
- 密码版本从2更新到3后会话表为0。验收脚本原断言要求公共401，但网关把未登录转为302登录跳转而中断；同秒原自测网关记录为恢复时200、重置后302。保留失败及原意图；没有单独捕获原verify的401，不能写成401验证已通过，也没有重新创建或盲重放。
- 最早创建准备因旧SQLite3.7.17不识别现存索引语法失败，核无意图/身份/角色写入后，改用门户既有LD_LIBRARY_PATH中的SQLite3.53.4继续；未迁移或修复数据库。另一次TLS验收错误来自脚本以fullchain替代系统信任根，修正为系统根后主机名/完整校验通过；未改证书或关闭验证。
- 私有原证据/tmp/fc-dot-observer-20261022/{identity-intent.json,validate-identity-intent.json,identity-progress.jsonl,identity-result-reconciled.json,release-result.json}。密码/会话只在服务器进程内用于验收，进程结束后未保存或交付，不进本文、聊天、Notion、Git或TXT。

## 当前真实阻塞与安全登录

老D转交：12:10云端刷新返回protected_command_failed，人工接管请求也失败且要求停止；该浏览器操作已停止，不绕过。账号与服务器验证完成不等于Dot已使用新身份。

没有已验证的FS凭据vault交付工具，且云端私密登录入口受上述保护阻塞，因此凭据交付未完成。用户/身份管理员可以在[现有账号权限页](https://47.85.224.112/__auth/access/)选择dot_fc_observer，在“修改密码”私密输入框自设新密码，再待Dot产品安全登录入口恢复后直接输入；本Work不接收或转发明文。设置前验收用随机密码已丢弃，不能用本文登录。

云端调度、续期及唯一责任切换均未验；原Work观察继续，服务器唯一writer。原自然job a5914831-e264-4b34-b755-fa5bdba27c36于12:10:11创建、12:12:49 ready/no_price_change，下一计划14:12:49；这是服务器原周期，尚无本轮Dot独立读回。12:27原监控138SHA无漂移、v13/rev40/on/auto/120/min10、队列0/未确认0，公开仍521c及10:41旧观察，不称新的自然变价或长期增利。

## 12:46 当前改密页面阻塞（只读诊断，未修复）

用户实做报“成员标识无效”。活动成员数据给内置账号返回裸subject，页面将其原样发给要求native:subject的改密接口；下划线符合原规则。原两次POST400，权威账号仍native:dot_fc_observer/version3/enabled1。12:37以前“可在现有页自设”的建议暂不可执行，勿反复尝试；接口级验收未覆盖该页面合同，原服务器验收不能代替页面端到端验收。

最小候选为仅修改setPassword请求体：kind=native时使用native:加m.name，注册账号保留m.subject；不改成员角色标识、正则、管理员/CSRF/库存存在校验、长度、PBKDF2或会话撤销。当前仅诊断/本地记录，尚无修复代码、PR、上线或页面实测；由老D主对话协调精确实施范围。尚无已核验替代私密页面；不得索取密码、在控制台粘贴脚本或绕过产品保护。此补充未同步远端文档/Notion，最新本Work HANDOFF为接续依据。


## r4：13:08改密页面修复已上线；新身份使用及接管暂停（2026-10-22）

本节覆盖12:46“页面尚未修复”，保留原两次400及接口验收未覆盖页面的事实。PR339最终head `4dd30bbb4e34bf03ed228a583d1605166ca31263`、merge `f5f5355151aa1530dbc11b6cd44545683b5378c2`；保留PR337并行更新后，正式pr-fast `39725708600/job119648987201`成功。Node12场景及双Linux各控制台30/权限22通过。完整分发器自检在Ubuntu正式CI执行：服务器缺Git、Windows不能创建Linux换行文件名夹具，这些环境失败保留，未删除或放宽CI断言。

页面setPassword仅按服务端kind=native构造native:+m.name，注册账号保持m.subject；角色绑定仍用裸用户名，后端正则/管理员/CSRF/密码长度/PBKDF2/会话撤销不改。保留活动共享导航，代码差异只有该行及末尾补换行。

原publisher于13:08:13发布 `nav-20261022T050813Z`，manifest `8f56fa92b5002d5535a990bf122d69b41de2266a82983cd1ea93518d1c91688f`，stage `/opt/fs-release-stage/iam-password-contract-4dd30bbb4e34`；1目标/139保护共140SHA吻合，备份 `/var/backups/fs-navigation-20261006/nav-20261022T050813Z`，无服务重启、密码/权限/价格或周期写入。保留MapleStory原journal `workspace-native-20261006-e17a041d4294`及Nginx SHA `df08e52cde5ce98723ec0819285a27028b6d67516bb17ad877e7d1cafa8efb45`，未用旧保护清单回退他人上线。

13:08:57真实页面与app.js均200，JS SHA `da2d93c8b7ebed63526b80ade74246d0cf267383e5854115297b5cb8f7b9a75d`，no-store。全新匿名浏览器对实际脚本做仅测试用内存插桩，原生请求为native:dot_fc_observer，注册仍reg:UUID；全部POST在浏览器内截断，服务器收到0个测试POST。没有读取用户输入、代设密码或重用会话。账号仍enabled/version3；用户真实私密改密/新身份登录尚未验收，不把浏览器模拟成功称真实改密成功。

### 角色变更只读审计与当前暂停

12:38:36原 `POST /__auth/access/api/member/roles` 返回200，IAM generation13→14，revision `84e54e25015f20b9`；审计actor为已认证主体wulv，不能据此认定实际真人。角色由FCObserver变为Analyst、ArpgOps、Auditor、CollabEditor、Deployer、FCObserver、PricingOps、SportsOps。generation13原policy.json.bak与当前四项edit/execute/deploy/manage显式deny完全一致。本Work未改变或回退这些角色；老D已向用户核定，未答前新身份使用/接管暂停。

现行实际策略离线求值480组合，额外允许读取0、写入/部署允许0；专用主体硬白名单仍限定精确GET automation、monitor、pricing/state和审查后Coins jobs。此为现行策略离线求值，不是新身份真实HTTP登录验收。额外角色不能据此视作已获授权或永久保留。

13:16使用原生单FCObserver非秘密夹具，在匿名隔离浏览器执行现行openMember/saveMember：10个角色框只默认勾选FCObserver，请求只含FCObserver；所有POST截断、真实角色写入0，未复现默认全选。当前源码无成员全选动作，按m.roles逐项勾选、只提交checked；缺当时DOM及请求体，既不认定人为主动全选，也不宣称排除历史异常。

私有证据 `/tmp/iam-password-contract-20261022/{release-result.json,browser-readback.json,final-readback.json,role-audit.json}`；本机同名私有目录还有role-ui-readback.json。原400、来源前缀根因、旧接口验证及失败均保留。云端protected_command_failed及私密交付/续期/调度/唯一责任仍未完成，不重试保护操作。

13:12原监控140SHA无漂移、v13/rev40/on/auto/120/min10、queue0/incomplete0，公开仍521c/10:41旧观察，下一原周期14:12:49。Coins10:08收入/10:43成本/00:57Z ES仍partial，营销准确区间pending，不补零、不据此判断新价效果。原监控已原子更新合法stage引用并留旧引用；原Work观察继续、FS唯一writer，不新增采价/模型/监控任务。

### 13:19 staging来源复核与仓库重建缺口（仅核证据，未扩施工）

已读取PR339原评审 discussion_r4344699443。实际准备由 `/tmp/iam-password-contract-20261022/stage.py` 从head4dd30bbb4e34bf03ed228a583d1605166ca31263的 `opt/fs-access-policy/web/app.js` 读取，写入 `/opt/fs-release-stage/iam-password-contract-4dd30bbb4e34/candidate/source/app.js`。Git源、staging候选、线上文件及真实HTTPS读回均为SHA `da2d93c8b7ebed63526b80ade74246d0cf267383e5854115297b5cb8f7b9a75d`。

原意图 `/tmp/iam-password-contract-20261022/release-intent.json`，release `nav-20261022T050813Z`；原回执release-result.json及备份journal的批准SHA均与manifest `8f56fa92b5002d5535a990bf122d69b41de2266a82983cd1ea93518d1c91688f`吻合。journal仍保留原applied-awaiting-actual-http-role-acceptance，浏览器读取/隔离请求构造另有回执，不改写旧状态为真实私密改密已成功。

评审指出的仓库复建缺口成立：PR339提交了固定资产 `opt/fs-access-policy/web/app.js` 和wrapper，但没有提交从该源组装candidate/source/app.js的准备脚本；本次用了已保留的私有stage.py，不能把本次上线成功称“只靠仓库即可完整重建”。本轮按协调仅核证据，不修改发布器或补工程；后续重建任务须显式保留来源映射及原锁/CAS链，不能直接拿wrapper当完整发布包。
