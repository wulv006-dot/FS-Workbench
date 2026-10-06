## 2026-10-07 本治理合并检查记录

复用并核对PR #3精确检查器原字节，在本机隔离副本完成完整合成检查：185 Python方法，184pass/1Windows所有权skip/0fail-error；182 Python AST、34 JS语法、rev25矩阵及7组Node通过。Windows Python3.14首次Google时区用例因缺tzdata失败，原失败保留；使用现有Codex bundled tzdata/zoneinfo设置仅当前测试进程PYTHONTZPATH后完整复核通过，没有安装依赖、改源码、伪造时区或删除用例。该结果只覆盖本治理所沿用的main业务源码，不能替代PR #2 NBA增量或PR #5注册、真实Linux/身份/生产验收。

最终文档/两清单经精确树、308未变文件原字节及17模块归属检查；完整合成检查输入的业务源码与最终候选字节相同。本次15条路径均为治理文档/JSON，merge条件仅限该范围。PR #2/#3保持draft，未来业务组合树重新核验；空GitHub checks不是正式CI绿色。最终head/tree和实际merge以PR #6读回为准，生产仍未授权。

## 2026-10-07 治理文档合并准备：当前状态优先于下文历史快照

用户本轮明确指示“那你检查完就合并吧”，授权检查完成后合并PR #6治理文档；不包含其它PR、服务器部署或业务变更。草稿原head ac2866c40b883d3084e28fbf02818a71fe46bcbf/tree e6ac6f494509070b60e33b4e0c3380fb37c2a2b3 已入库；下文“远端尚未更新/写入或合并批准待补”仅为冻结时点。当前候选补充这次状态及准确清单，最终head/tree和merge结果以GitHub PR #6与merge读回为准，不在文件内自引用最终commit。

本次只有治理文档/JSON及两活动清单，308份其它文件原字节、size、Git mode保持；业务源码未变。吴律当前直接授权文档合并，不替代陈超的ARPG业务批准。PR #2的NBA候选与PR #3的检查器都仍独立draft，不顺带合并：先集成本治理文档，后续PR需基于新main协调其7治理路径/2活动清单重叠，重生成活动清单并检查新的组合树。原分支/历史证据不改，不声称未来组合树已经验收。

最新协调交接记录注册PR #5 d9dd533008fe298946eadd9e4bfea3a294aec111/tree d30ccde1e6551cd8ef6228a55d6629b7d603b84f 的Linux43=43pass/0skip、14.164秒，B-CL-01已关闭；原证据Library id libfile_c091fb7f82648191886848703a72e0ed、SHA256 34b8d9c0b7eac08ea5acce513a54b81ef47ab4ba0bb89a4f730c045dcea1398c。本治理轮只读交接，未独立获取原始证据或复跑。Python3.9目标环境、真实角色/Nginx与另4项多进程验收仍待，不能把43项通过当注册合并/生产批准。旧Windows错误、取消上传和原冻结对象保留。

利润补采首新版自然主体成功、补采12项失败；两既存cache已定位严格右端次日00双零占位兼容缺陷，独立最小修复尚待审查，不声称12项全因一致或已修复。120分钟/60秒、业务口径/价格/账号不变。本治理合并不发布业务模块，所有模块releaseReady=false、未接管映射继续legacy-unreconciled。

来源：已读取的本机CURRENT-QA-HANDOFF.md脱敏摘要，仅作协作记录；该原工程全平台文件不复制进本仓，也不建立新部署绝对路径依赖。空GitHub checks不代表CI通过；本PR按实际最终树作文档/清单/原字节检查及隔离合成检查，合并后读回实际集成树。生产、自然验收和各业务PR未决门槛保持独立。

# 当前协作状态 governance-20261007-v1

核对时间：2026-10-07T01:42:43.895157+08:00，当前入口为本段。远端main `bc3b29531cec2fab3fc090385f3d7d126eb9ada7` / tree `a4140280619771e9240e15340b0c452ab8ba9ef8`，完整树323 blobs未截断，逐blob/size和本地清理快照一致。远端5个开放PR均draft、未合并；本次没有远端写入。

| PR | 当前head | 范围 | 当前层级 |
| --- | --- | --- | --- |
| #5 | `d9dd533008fe298946eadd9e4bfea3a294aec111` | 登录权限 runtime v3：冻结候选与本轮验收失败记录（草稿） | 草稿；owner/合并/生产均未由本轮放行 |
| #4 | `d0a07b0ca85c05a3eaca10e788b0648d100566e0` | FS 自助注册与审批 v5：隔离候选及独立 Linux 验证（草稿） | 草稿；owner/合并/生产均未由本轮放行 |
| #3 | `8eed759b98218615d9857660b35c43a07c5184fd` | 候选检查器：失败退出码、精确清单与目录防漏检（草稿） | 草稿；owner/合并/生产均未由本轮放行 |
| #2 | `c5e641c82cba3280b3d2cf97179cd5ab260e94b8` | 协作文档与 NBA receipts r4：Linux 测试修复及候选入库（草稿） | 草稿；owner/合并/生产均未由本轮放行 |
| #1 | `1466362fc0c8fea1a09ba9610cfb0993486c048a` | D4／PoE2／Aion2：最终数值 guard 候选与隔离测试（草稿） | 草稿；owner/合并/生产均未由本轮放行 |

PR5当前tree `d30ccde1e6551cd8ef6228a55d6629b7d603b84f`，32-payload B-v4为新测试输入，来源自述Windows43=41pass/2POSIXskip/0error，B-CL-01有限审阅关闭；本轮未复跑。旧64028127/6633d00的39=36pass/2skip/1error及精确10054归因限制保留。旧原字节verifier只验旧包；新Linux43/两POSIX/另记multiprocess4及消费者、可信代理、存储撤销门槛仍未验。PR正文仍旧head，修改正文另需具体GitHub写入授权。

PR2与本轮治理7文件重叠；其四管理员/FC全局身份/NBA候选进展原文保留为候选来源，未把它当现场新验收或merge批准。NBA源码增量不捎带进本治理包。三/四管理员差异待对应授权及合法现场证据，既有账号不变。

main分支接口protected=false；rulesets返回403，本轮停止该查询，不购套餐/改公开/换身份；不能称全部规则不存在。actions接口被connector拒绝支持，main树无.github/workflows，本轮未核实其它任务分支/外部CI的实际执行。

所有17组模块已登记owner/待指派及接管状态；运行/产物/生产现场未知项保持null，不凭改JSON升级状态。治理候选未入库，具体GitHub载荷授权待补；merge/上线/回滚另批。

## 历史PR2合同（保留来源自述）

# 当前协作状态：文档＋NBA候选增量

> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。


本批已冻结，待根协调使用既有连接器提交draft PR。源7项均与独立NBA revision4审阅准确SHA相同；3个不变依赖也和远端基线相同。本任务未commit/push/merge/deploy。D4数值增量和UI/auth源独立批次，不依赖它们生产验收阻塞本批文档/候选入库；也不能因本批通过放行那些源码。

阅读 docs/planning/fs-docs-nba-batch-20261006/README.md 与 TEST-REPRODUCTION.md。unknown保留旧requestId核对，不新ID重写；NBA无人值守方向后置，具体策略/调度/生产未启用。当前普通全局账号范围依已授权global政策，不用旧FC-only规则拒绝合理任务。新注册仅介绍/申请方向，实际入口未实现。Git write是仓库能力，owner/path范围卡为协作规则，不能宣称目录ACL或保护已强制启用。
