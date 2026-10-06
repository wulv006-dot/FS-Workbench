## 2026-10-07 治理文档合并准备：当前状态优先于下文历史快照

用户本轮明确指示“那你检查完就合并吧”，授权检查完成后合并PR #6治理文档；不包含其它PR、服务器部署或业务变更。草稿原head ac2866c40b883d3084e28fbf02818a71fe46bcbf/tree e6ac6f494509070b60e33b4e0c3380fb37c2a2b3 已入库；下文“远端尚未更新/写入或合并批准待补”仅为冻结时点。当前候选补充这次状态及准确清单，最终head/tree和merge结果以GitHub PR #6与merge读回为准，不在文件内自引用最终commit。

本次只有治理文档/JSON及两活动清单，308份其它文件原字节、size、Git mode保持；业务源码未变。吴律当前直接授权文档合并，不替代陈超的ARPG业务批准。PR #2的NBA候选与PR #3的检查器都仍独立draft，不顺带合并：先集成本治理文档，后续PR需基于新main协调其7治理路径/2活动清单重叠，重生成活动清单并检查新的组合树。原分支/历史证据不改，不声称未来组合树已经验收。

最新协调交接记录注册PR #5 d9dd533008fe298946eadd9e4bfea3a294aec111/tree d30ccde1e6551cd8ef6228a55d6629b7d603b84f 的Linux43=43pass/0skip、14.164秒，B-CL-01已关闭；原证据Library id libfile_c091fb7f82648191886848703a72e0ed、SHA256 34b8d9c0b7eac08ea5acce513a54b81ef47ab4ba0bb89a4f730c045dcea1398c。本治理轮只读交接，未独立获取原始证据或复跑。Python3.9目标环境、真实角色/Nginx与另4项多进程验收仍待，不能把43项通过当注册合并/生产批准。旧Windows错误、取消上传和原冻结对象保留。

利润补采首新版自然主体成功、补采12项失败；两既存cache已定位严格右端次日00双零占位兼容缺陷，独立最小修复尚待审查，不声称12项全因一致或已修复。120分钟/60秒、业务口径/价格/账号不变。本治理合并不发布业务模块，所有模块releaseReady=false、未接管映射继续legacy-unreconciled。

来源：已读取的本机CURRENT-QA-HANDOFF.md脱敏摘要，仅作协作记录；该原工程全平台文件不复制进本仓，也不建立新部署绝对路径依赖。空GitHub checks不代表CI通过；本PR按实际最终树作文档/清单/原字节检查及隔离合成检查，合并后读回实际集成树。生产、自然验收和各业务PR未决门槛保持独立。

# FS-Workbench 协作入口

当前修订候选：governance-20261007-v1，日期2026-10-07。首批已入私库 main `bc3b29531cec2fab3fc090385f3d7d126eb9ada7`，323文件；不是全平台已接管或可部署证明。本地候选未提交、未上传、未合并。

人类读[操作手册](docs/collaboration/OPERATION-GUIDE.md)；AI先读[AGENTS](AGENTS.md)、[当前状态](docs/collaboration/CURRENT-STATUS.md)、[负责人](docs/collaboration/OWNERS.json)、[来源与活动映射](docs/collaboration/SOURCE-MAP.json)、[就绪状态](docs/collaboration/READINESS.json)及模块合同。

核实来源/owner→独立候选→合并前QA/消费者回归→确切SHA确认与合并→合并后产物校验→独立上线批准/受控发布/读回。代码、协作、责任映射、运行证据分开；上线及自然验收分开。

[首次入库计划](docs/collaboration/FIRST-UPLOAD-PLAN.md)是历史初始化材料。[HANDOFF](HANDOFF.md)只记录本私库源码协作；原工程未迁移全平台记录保留。每模块接管需来源/构建/依赖核验，不依赖个人电脑绝对路径作为新部署合同。

## 历史介绍和PR2候选约定

# FS-Workbench 干净协作源码

> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。


当前文档/NBA候选批次：[准备读我](docs/planning/fs-docs-nba-batch-20261006/README.md)、[测试复现](docs/planning/fs-docs-nba-batch-20261006/TEST-REPRODUCTION.md)、[AI操作手册](docs/collaboration/OPERATION-GUIDE.md)、[状态](docs/collaboration/CURRENT-STATUS.md)。首批已入库，本批尚未提交。无需等D4/UI生产验收才审阅此增量；它们不纳本批，不被放行。所有releaseReady=false；无workflow/自动部署、凭据/运行数据/旧Git历史。
