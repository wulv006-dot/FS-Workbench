# FS revision3：有限最终只读增量复审

日期：2026-10-05。审查工作区：`D:\codex\2026-10-05\task-6`；主工程唯一写负责人仍为01a0f1c0。

**结论：R2-F1～F3在本次静态源码和已生成合成测试记录层可关闭。311项冻结库存匹配，原301冻结候选未变，经营/FC核心保留。未发现本次有限增量范围内新增可确认的P0/P1运行缺陷。仍不能发布：FC共享资源别名范围、NBA逐计划确认与无人值守取舍，以及实际运行验收继续阻断。**

本报告供后续Astra架构任务接手，不进行结构重构、业务选择或生产操作。初轮和revision2报告保留原件；本报告仅更新本轮有限delta。

## 1. 范围与核验

- C3：`E:\WorkBuddy\大超服务器\fs_platform_integration_20261005\candidate_revision3`，来自revision3 README实际入口。
- C2：同层`candidate_revision2`。
- P3：`E:\WorkBuddy\大超服务器\docs\planning\fs-platform-integration-20261005\revision3`。
- 下述源码行号以C3为根。

已读当前AGENTS要求的README、SOURCE-MAP、OPEN-DECISIONS、.gitignore及本轮修复/决定/路径映射；静态阅读迁移工具、相关测试、FC只读桥、NBA计划绑定和共享发布策略及关键消费者。没有执行、import或安装任何候选／新包／测试代码，没有访问生产、浏览器、真实账号、订单、凭据、日志、数据库或私有PROFIT。仅在本审查工作区写报告与证据。

独立哈希与枚举证据：`fs-revision3-independent-evidence.json`。

| 项目 | 独立结果 |
| --- | --- |
| 准确库存 | 311文件、12,111,256字节，逐项长度/SHA全部匹配；无额外文件 |
| 原冻结C2 | 301/301当前SHA仍等于revision2准确库存；原件未变 |
| C3相对C2 | 282文件不变、19修改、10新增、0删除，符合delta记录 |
| 已记录测试源码 | targeted-evidence列的10项源码SHA均匹配当前候选 |
| 集合摘要 | 清单声明`f1d7ce1d3cb2c73ccaae58744ef2ff2a34cef69070d098193b2cac86b7ae532c`；本审查逐项核完整集合，未独立重建集合摘要的序列化算法 |

“原301不变”指原C2目录保持冻结，不是C3内301份旧路径全都不变；C3确有19项有限修改。证据明确区分这两个事实。

## 2. R2-F1～F3关闭依据

### R2-F1：六后台实际身份——已补齐

`tools/fc_migration_contract.py:7–13`与现有coin_all_sync_job.PRODUCTS一致：PS ALL163329309/source163329311/aid21587，XBOX ALL163329275/source163329277/aid21585，PC ALL163329343/source163329345/aid21589；mid41217957/gid1327/cid9623、site0/266、unit K/title coins/status1。

`:49–57`不仅检六个外层键，还逐行核九个实际身份字段并拒绝非dict，关闭“别的商品行放在正确外层键也通过”的缺口。`tests/integration/test_fc_migration_contract.py:10`正例现在包含身份；`:34–42`六行×九字段的空/错值负矩阵及跨平台行替换均应拒绝。测试helper直载路径`:3–4`仍为当前候选tools源。

这是只读迁移前置验证，不代表已经取得当前六后台行；身份常量未来可抽为经审查共享合同，但本轮无需为去重复重构现有运行读回逻辑。

### R2-F2：有限正Decimal及数值唯一——已补齐

工具`:15–27`先约束15项列表，再Decimal转换，拒bool／非有限／非正值；用数值集合判唯一，明确拒20/30/40K。`:53,59–64`分别验证批准向量与两行gold，保持顺序、原gold表示及源/ALL的gold/discount/give一致，不用排序掩盖变化。

测试`:43–54`包括True/False/0/负数/NaN/Infinity/错误字符串，以及`60`与`"60.0"`等值异表示重复、实际行错误、顺序反转。带日期仅数量参考和“不生成旧18档、不每轮删档”的合同继续保留。

工具没有把真实price当迁移参数计算或替用户生成策略；真实价格、当前revision与三公开页仍须未来受控读回，不能由合成检查替代。

### R2-F3：真实Python／JS报价及write gate四档矩阵——已补齐

`tests/integration/test_fc_rev25_matrix.py:7–11`从当前根及cloud/tools加载真实engine、automation_policy和迁移合同；`:17–19`使用准确rev25四档6–8/5–6/0–5/0–0及既有初始策略的受控修改。`:26–32`调用实际Python calculate并将16份合成输入交给Node；`fc_rev25_preview.cjs:3–5`直接加载当前`fc27_chrome_collector/repricing_logic.js`并调用recompute，没有改用镜像算法。

六专门测试覆盖：

- `:37–43`三平台proposal、floor、target、降幅、档位、成本、赠送、Xbox来源等字段的Python/JS一致性。
- `:44–49`40/30/20三个阈值及下侧样本，明确四档预期，而非只比较两个实现。
- `:50–57`每个有降幅结果均落在准确批准边界内，另强制触发6和8两个裁剪端点。
- `:58–67`实际check_write对可写与成本/档位阻断的允许、拒绝，两类均必须有样本。
- `:68–73`Xbox跟PS报价，但自身成本不足时实际write gate拒绝。
- `:74–83`revision/hash/schema/rules/价格篡改拒绝，以及四档规则变动被迁移合同拒绝。

14份原脱敏fixture包含competitor_gift和own_gift_cost_only_same_band，新加两个裁剪输入，共16份。本专套件对赠送主要作跨实现比较，独立赠送公式依据仍来自未改算法和既有回归；不把其称所有业务输入的数学证明。其它档每个裁剪端点未都单独强制触发，但准确边界、三阈值、四档、成本及真实门禁已经覆盖本次要求的最小回归闭包。

没有调用save、writer、队列或timer，也未把用户rev25写成新环境全局默认；现有`automation_policy.py:202–270`门禁继续从策略、quote SHA和证据重验。

## 3. 新增变更兼容与阻断

### FC限定只读桥：实现边界成立，完整兼容未通过

`opt/auth-portal/fc_read_scope.py:8–32`限制GET/HEAD和FCops/Players路径，拒绝绝对URL、路径编码、穿越与未知API；可保留查询参数中的正常编码过滤。`auth_portal.py:687–710`只在ungrouped verifier及白名单路径调用回环8896 `/verify`，仅转fc27sess，校验状态/返回用户名，只发`X-Fc27-User`和readonly，不发内部Auth身份。`:714–733`有内部签名与现存登记时仍走内部policy。

`tests/integration/test_revision3_contracts.py:58–98`静态可见正例、过期/错误状态、同名wulv/DY不提升、内部路径／写方法不桥接，以及内部管理员／reader矩阵。但提取方法、HTTPConnection、签名解析、登记和policy有mock；没有真实8896／nginx／登录验收。

**保留业务阻断：** `fc27_ops_cloud/index.html:257`仍引用内部四资源business-theme.css/js、business-range.js、exact-range-client.js；当前bridge白名单不允许这些dashboard路径。`docs/integration/REVISION-3-DECISIONS.md:3`明确等待父协调确认FC专用精确别名范围，本审查不替用户选择。

**给架构任务的额外边界：** 即使未来仅四静态别名获准，`fs_range_read_state_20261001/exact-range-client.js:2`仍请求内部`/dashboard/fs-home/range.json`。当前FC-only桥仍拒绝该接口；静态别名只解除资源装载阻断，不能自动证明外部FC动态准确区间完整兼容，也不能据此放宽内部经营数据访问。应在后续架构/验收中明确外部FC允许的功能粒度和数据端点，不是本轮新增授权。

### NBA计划／回执：静态错绑修复成立，业务决策仍阻断

`opt/nba-reprice/backend/server.js:548–573`每请求创建独立wx/600计划文件，把排序价格、operator、确认序列化成planJson并SHA绑定，收到子进程结果后核requestId/hash/operator，清理自己的传输文件。`p2pah_api.py:298–308`改为解析envelope并走write_contract，不继续读共享计划别名。

`write_contract.py:15–47`同一运行根的writer/login/cookie流程串行；`:57–82`核绑定、重复JSON键、三admin与平台／有限正价格；`:95–117`先持久pending再有上游效果，同ID完成返回原回执，pending/unknown不再执行，异hash/actor冲突拒绝。`p2pah_api.py:67–75,125,197,217`生命周期接锁，curl用唯一响应临时文件。

`test_nba_bound_writer.cjs:3–32`提取真实adminWrite，临时文件＋延迟fake execFile制造A/B反向完成，校验各自价格、错回执和timeout；`test_revision3_contracts.py:100–142`用实际helper的临时回执/线程、假上游、提取curl和fake_run验证不重放及独立响应文件。没有真实Python子进程写价，Unix多进程/flock/受信运行根未验。不重放证据限于同requestId，不是跨所有新ID自动去重承诺。

**保留业务阻断：** revision2前端逐轮window.confirm仍未改，不能称恢复无人值守。DECISIONS`:4`已给逐计划确认／另行批准自动策略两个方案；本审查不猜、不实施、不改变生产规则。NBA/MLB有效认证接入仍待实际路径验证。

### 静态发布内容规则与共享策略

`opt/deploy-hub/bundle_policy.py:14–47,78–89`新增解析后递归检查JSON的键／嵌套／列表／值，处理转义、大小写、Cookie/set-cookie/batoken/Authorization，拒重复键，保留明确无凭据placeholder。其余HTML/JS仍启发式，不是任意秘密检测或同源JS隔离。

相关四项BundleContracts含敏感JSON、正常placeholder、拒绝ZIP先于写入及生成策略匹配。独立静态核验：client嵌入完整policy及SHA头在Python通用换行读取语义下匹配；policy原文件LF、client为CRLF，所以不能说原始字节子串完全相同。当前源SHA `07a9d053…dee722`正确，换行差异不构成执行规则漂移。发布正常JSON的重复键／非有限数及有凭据内容现在会拒绝，是新契约范围，后续合法包需按此验收。

## 4. 保留与不扩大合并

独立C3/C2逐SHA核对282不变项包含经营v7模板、Aion2 Order826/Admin891 collector、FC原生商品reader/contract、根Python引擎、JS报价、automation_policy、coin_all_sync_job、活动range SHA0a03f802…31aea、六补源及Players当前45源。revision2经营14指标＋三图、FC原接口及Players9627/Packs9629/SBC9625、赠送只计我方成本和Xbox独立护栏结论继续成立。fs120负责数据，旧publisher继续隔离。

range的活动源加载修复测试没有改；本轮没有重跑parser或自然周期，不能把保留字节再说成新Linux运行证据。无权限恢复旧publisher／历史脚本，也不以D4竞价／商品表替代经营数据。

可等价整理边界仍是生成镜像／明确SHA和runtime映射，以及本轮已证明的client生成策略文本；不合并不同系统类别枚举、不为抽象公共身份重写运行writer。新MODULE-RUNTIME-MAP提供文件与外置依赖静态事实，REVISION-3-RUNTIME-MAPPING明确planned status；都不是实际unit、container或nginx已应用证明。

## 5. 离线记录与未验

P3/revision3-targeted-evidence.json记录五组Python：12 contracts＋8 migration＋6 rev25 matrix＋12既有wiring＋9既有pure guards，共47，46通过、1Windows symlink能力skip；三组Node nba-bound/routes/pure通过。P3/static-evidence记录182PythonAST/34JS语法。记录时间是归档／观察时间，不推定精确执行秒数。

本审查独立确认测试源码指向当前候选及其SHA、读了相关断言和mock边界，**未重跑这些测试**。P3没有独立test-evidence子目录，本轮可读证据为targeted/static摘要和对应源码；不能声称本审查观察到每次测试执行原始输出。该事实不推翻主负责人已记录通过，也不扩写为全套回归通过。

revision3没有重跑revision2完整170项；不把47与170相加当217项新版全套实跑，也不称191等其它汇总已全执行。当前check_candidate已登记新组并不证明该完整脚本被执行。

实际仍未验：当前六后台／三公开页／外置revision时下状态；有效unit/drop-in、运行模块SHA、路由与容器/CDP；FC外部门禁／内部真实角色、NBA/MLB认证；Unix所有权、多进程锁／软链接race；真实上游价格写／回执与自然timer；所有模块端到端、UI布局及Ponytail。没有可用真实readonly账号，按既定约束不新建或降级管理员补测。

**供Astra接手：保留311冻结集合和三轮独立证据；将R2-F1～F3记为上述范围闭合，将FC静态别名／动态端点边界及NBA自动确认方案列为待决，不在架构任务中擅自赋予访问或写价权。`releaseReady=false`、`uploadApproved=false`继续成立。本审查至此收尾，不扩全平台审查。**
