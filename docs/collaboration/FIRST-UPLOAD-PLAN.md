> 首次目录状态补充：本文件原始时间点保留，后续条件入库/今晚自主推进与最终准备状态见CURRENT-STATUS.md及READINESS.json；源码基线可入库不等于可部署。

# 首次私库上传准备计划

日期标签：20261006。执行状态：**本轮未commit/push，未创建新Git仓/凭据，未改冻结候选或生产。** 用户已条件批准符合首批标准的白名单源码/测试/文档入库；根协调审核手册与准确入库材料后才执行已授权push，不重复把历史“未批准”当最新状态。

最新授权：今晚由根协调自主推进普通实现、优化、迭代；本目录交付后，门槛满足即可执行首批已授权commit/push，不再把普通步骤送回用户确认。重大事项及新持久凭据/OAuth/SSHkey、生产权限扩展、定价策略、不可恢复删除仍不能据广授权执行；本分工只出准备证据，不并发推送。必要的入库/发布安全检查仍执行，未验模块隔离。

## 1. 已核实与未核实

| 项目 | 本轮只读结果 | 执行影响 |
| --- | --- | --- |
| GitHub连接 | wulv006-dot；仓库id1405023980；private，size=0，默认main；分支查询为空 | 现有连接可读私库；没有可用baseline commit SHA，不虚构main SHA |
| 现有权限 | 吴律连接admin/push；dachao1997=write | 不需要再邀请/扩权；不能推导目录隔离 |
| 本机Git | 已安装；原工程HEAD `1dd843ef0b991215fe66bd26b006f8ce37923a41`，83项已跟踪dirty，无remote | dirty统计未包含untracked总数；本地HEAD只是取证，不是首批可推历史 |
| 本机现有HTTPS认证 | Git Credential Manager 2.7.3已在；非交互 `ls-remote` 认证不可用，未发起交互 | connector授权不等于本机Git登录；未读取credential/token值 |
| 网络与测试 | 普通沙箱网络连接失败；经批准只读联网后返回“不能读取用户名，交互关闭” | 不能据前一次网络错认无凭据；后一次仅证实当前非交互身份未完成Git认证 |
| 强制门禁 | 套餐、有效branch规则、bypass、CI未核实 | 人工/AI规则先执行；不说已有技术强制保护 |

只读Git因目录所有权提示失败后，仅对三次只读命令用 `-c safe.directory=<这一个已指定工程>`；未写全局配置、未使用通配信任。没有查询或输出credential内容。

## 2. 首批来源和准确选择

原候选：`E:\WorkBuddy\大超服务器\fs_platform_integration_20261005\candidate_revision3`。外部完整库存311文件、12,111,256字节，集合SHA `f1d7ce1d3cb2c73ccaae58744ef2ff2a34cef69070d098193b2cac86b7ae532c`；完整清单SHA `196e4789ba19364d047adb3f9a5ee915cd354b2022cacf2de964a721bc25a41c`。本轮逐文件复核结果见本目录SOURCE-MAP.json，未执行候选代码。

**推荐采用独立首次入库目录，保留现有相对源码路径。** 不把候选重命名为modules全站架构，不改311冻结文件。新目录不能在原E工程内初始化后接其历史；由根协调选可写独立目录。只有新目录可设置这个私库remote，原E工程继续无remote。

根协调准备精确 `first-upload-manifest.json`，每条写 `sourcePath/sourceSha256/targetPath/targetSha256/moduleId/owner/category/releaseReady/变更原因`。输入是本目录SOURCE-MAP.json中311条完整准确来源，不是“复制目录”。支持三类：

1. **源码、测试、非秘密模板**：逐条复核来源SHA/秘密后复制；测试baseline/before_engine只标回归对照，永不当活动部署真源。归档运行声明不补为有效nginx/systemd配置。
2. **候选历史治理文档**：保留冻结原件不动，首次目录中更新到真实时间顺序或保留清楚标“历史”；不得把原工程AGENTS/HANDOFF整份未经筛查拖进去。不允许旧指令恢复publisher/旧身份/第四admin。
3. **最新补充文档**：逐文件扫描和白名单后加入最终状态、两份最终review及必要脱敏证据、架构/业务决策、本操作手册/计划/精确source-map、入库清单和验收记录。测试摘要写范围，不替代原始输出。新目录的文档必须能离开本机绝对路径读懂。

311是**来源库存**，不是最终上传数量。候选内部UPLOAD-ALLOWLIST可能不含其自身，provenance清单仍是历史口径。首次清单必须与真实待提交集合一致，新增/替换治理文档后重新计算集合SHA。不要用311或旧SHA冒充新包数量/SHA。避免自引用哈希：内容清单明确排除该清单自身，再单独记录其文件SHA；提交树清单作为commit外部验收证据按完整树核对。

## 3. 这些文档必须同步到最新版（仅新首次目录；原件不改）

| 文档 | 需要解决的旧表述 |
| --- | --- |
| README.md、AGENTS.md、HANDOFF.md | 条件入库已批但尚未执行；原工程Git历史禁推、新目录可入库；新增两用户模板/owner分工；releaseReady仍false。HANDOFF说明它是私库准备/后续协作记录，不能宣称替代原工程唯一事实源；由根协调写关联与迁移边界 |
| docs/OPEN-DECISIONS.md、docs/integration/REVISION-3-DECISIONS.md | FC经营数据类别已批准，端点/身份验收仍OPEN；NBA方向认可且升级后置，具体策略/生产仍未批；两P2与未验模块保留。只在新目录记录更正，不抹历史 |
| docs/SOURCE-MAP.md、integration/MODULE-RUNTIME-MAP.json、MODULE-MATRIX.md | 17组232路径+79支撑，不是17个全验部署单元；taskboard实际4源；活动range0a03f802…；baseline非活动，缺闭包明确；替换旧“复审进行中/任务台0文件”读法 |
| docs/integration/TEST-STATUS.json、TESTING.md、README/REMEDIATION相关声明 | 主方47Python=46pass/1Windows skip、3Node组；182AST/34JS语法。独立review未重跑、没有把170+47相加；完整check_candidate登记不等于执行。NBA回执持久性/幂等保证严格收窄 |
| docs/integration/UPLOAD-ALLOWLIST.json、docs/provenance/UPLOAD-ALLOWLIST.json、source-manifest/INTEGRATION-MANIFEST | 冻结状态是历史；首次上传另有精确manifest和逐项用途/批准范围。文档改了就更新目标SHA，不能保留旧哈希叫准确 |
| DATA-CONTRACT、DEPENDENCIES-AND-OTHER-MACHINE、DEVELOPMENT、OPERATIONS-ROLLBACK | owner已明确部分；跨模块必要变更逐项审批；源/产物/现场SHA、缺依赖、一次性测试/不可部署脚本、数据/锁/回执与受控网关边界保持 |
| PIPELINE-INCIDENT、RESTORED-V7及provenance/restored-v7 | 历史“根因未知”结合最新取证和退役/恢复自然验收读取；不能据旧归档恢复publisher。v7双SHA模板+私有PROFIT资料，模板不可直接部署 |
| 最新补充资料 | 最终状态 `revision3/final-reviews/FINAL-INTEGRATION-STATUS.md`、两份最终review；架构方案及FC/NBA/owner备忘；本目录资料。旧架构“push未批/owner待定/FC类别待确认”以明确后续记录更正；不架构重写 |

主工程最新HANDOFF/未决项用于核对时间顺序；涉及无关业务/运行值/凭据不整体搬运。根协调最终确认哪些新增文档准确进入首批，不能把“相关目录”变成新增目录通配授权。

## 4. 秘密和运行数据排除

必须排除：原工程 `.git` 与历史对象；原tar及raw/新建文件夹；真实password/token/API key/private key、公钥凭据材料、OAuth JSON、Cookie、Basic/Bearer/session/captcha；真实env/config和账号组库；SQLite/WAL/SHM、运行订单/客户资料/经营实值、PROFIT私有JSON、日志/报表/receipt/locks/队列/cache/runtime、evidence真实截图和备份；server_187/bundle/live_snapshot、旧release/build/安装权限脚本与退役publisher/采集链。原包名字含desensitized也不能当安全证明。

白名单中的源码 `data/*.js/css` 不因名data一概剔除，测试路径带baseline也不一概当运行数据；依据逐文件内容/用途选择。非秘密example/schema只含占位和批准业务默认，禁止把真实配置换个.example名字。`.gitignore`、路径拒绝项、内容检查、人类复核同时执行。启发式扫描会漏报/误报；只报告位置与类别，疑似值由受控owner核查，不在报告或终端打印。不读凭据来测试有效性、不触价格、不轮换凭据。

检查待提交实际文件、暂存index、将提交的树和本次新commit历史；不扫描/搬运原E历史来“证明干净”。禁符号链接/路径穿越/绝对目标/仓外指向与未知二进制：发现即列阻断，已白名单图片仍须确认用途和元数据。拒绝项优先于白名单，不能以来源已审绕过新的秘密命中。

## 5. 首次上传验收门槛（入库门槛不等于发布门槛）

- A1：手册、模板、owner表和跨模块规则由根协调审核；本任务只独立文档目录，不改主HANDOFF/AGENTS/决策册；根随后追加。
- A2：311来源逐SHA/大小/集合无漂移；首次目录明确来源、替换文档、精确目标文件清单/用途/计数/集合SHA，原候选与原E工作树不变。
- A3：真实文件集合/index/新commit树与清单一致；秘密拒绝检查及位置分类复核通过，不能用ignore或private代替扫描；无原历史、runtime或自动部署workflow。
- A4：新治理文档自洽并包含最新决定、有限测试、未验/发布阻断；必要helper保留，缺运行闭包仅记外置/未验，不“补装”。本轮不运行候选；若根后续要跑测试，先核实入口无网络/副作用、已有runtime可用且获得相应任务授权，不运行unknown脚本。
- A5：立即重新只读查GitHub仓id/private/成员/refs。仍空库时记录 `baseline=EMPTY`；如有人先上传，暂停首次根提交方案，记录真实head并clone/fetch后做差异PR，不覆写新提交。
- A6：选经核实的现有写入口。本机GitHTTPS认证未通过；连接工具已能读私库，不等于任意Git可写。根如采用现有连接支持的commit/ref操作，先核实支持完整树/二进制/准确SHA和无部署副作用，不拼多次逐文件commit成无review首包。无需新凭据时可继续已授权动作；需新增认证先停。
- A7：根审核已授权范围后，只有首次empty库的独立清理根提交可做一次 `main` bootstrap；记录这是空库初始化例外。首次分支/PR需要base，不能假设empty库已能开PR。之后常规任务走独立分支和PR，不直接push main。
- A8：push后用独立只读查询读回完整commit SHA、parent/tree、关键blob及白名单数量/文件SHA；验证private及main准确。记录 `源码已入库/未部署`，再由根协调追加主HANDOFF和决策册。读取失败标结果待核，不自动重复写。

A1–A6未齐不commit/push。本轮完成的是准备、现状读取和来源复核；没有给最终目标树准入通过证书。候选不能直接上线：FC静态/数据身份、NBA两个P2/真实Linux/自动策略、MLB下游agent、全部有效unit/nginx/container/CDP/真实角色及其它闭包仍未验。NBA以后升级不阻止独立准备其它模块，但共享变更和危险候选不放行。

## 6. 如需本人一次登录：最少步骤（当前未发起）

目前Git Credential Manager已安装，不为本手册装gh/GitHub Desktop等软件。只有根选择本机Git push且既有Git认证仍失败时才需要登录；已连接GitHub工具如能完整安全上传，可免本机Git登录，不为方便新开凭据。

1. AI解释“哪个本机、哪个GitHub账号、只为指定私库Git协作，现有连接不能完成本机Git认证”，先取得你对这次认证授权的明确同意。本轮禁止新凭据/OAuth，因此不能现在自动弹登录。
2. 如你同意，使用已安装且核实过的GCM网页登录流程；吴律登录wulv006-dot，大超登录dachao1997，只在GitHub官方页面输入密码/2FA。若出现新的OAuth权限/账号选择，本人阅读并确认；与预期不符就取消。不得把验证码、token、凭据文件发给AI，不生成PAT/SSHkey作为替代。
3. 返回后AI仅用非交互 `git ls-remote https://github.com/wulv006-dot/FS-Workbench.git` 核对访问、remote refs及当前基线。成功只证明只读鉴权；真实write仍以指定push结果和远端读回为准，不做试写测试。
4. 仍失败或提示扩权限/购买，暂停入库，交根协调报告。不自动重复登录、不改变可见性或权限、不继续上传。

本轮“非交互Git认证不可用”不是“不存在任何凭据”的断言，也没有要求你现在重新登录。

## 7. 根协调接续顺序

审核本目录 → 在唯一主记录追加手册/授权时间顺序 → 建独立首次目录与更新治理文档 → 精确清单/扫描/差异及入库验收 → 再查空库/认证 → 执行已授权首包commit/push → 远端完整读回 → 记录代码入库未部署。生产部署另做模块任务；本手册不授权任何全站发布。

本地来源与核验证据见SOURCE-MAP.json；Library保存结果只代表文档归档，不代表Git入库或根审核通过。Windows元数据失败保留本地和已返回Library ID，不修改官方helper、不伪造绑定、不改用别的上传路径重试。
