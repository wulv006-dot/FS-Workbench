# FS-Workbench 协作入口

当前修订候选：governance-20261007-v1，日期2026-10-07。首批已入私库 main `bc3b29531cec2fab3fc090385f3d7d126eb9ada7`，323文件；不是全平台已接管或可部署证明。本地候选未提交、未上传、未合并。

人类读[操作手册](docs/collaboration/OPERATION-GUIDE.md)；AI先读[AGENTS](AGENTS.md)、[当前状态](docs/collaboration/CURRENT-STATUS.md)、[负责人](docs/collaboration/OWNERS.json)、[来源与活动映射](docs/collaboration/SOURCE-MAP.json)、[就绪状态](docs/collaboration/READINESS.json)及模块合同。

核实来源/owner→独立候选→合并前QA/消费者回归→确切SHA确认与合并→合并后产物校验→独立上线批准/受控发布/读回。代码、协作、责任映射、运行证据分开；上线及自然验收分开。

[首次入库计划](docs/collaboration/FIRST-UPLOAD-PLAN.md)是历史初始化材料。[HANDOFF](HANDOFF.md)只记录本私库源码协作；原工程未迁移全平台记录保留。每模块接管需来源/构建/依赖核验，不依赖个人电脑绝对路径作为新部署合同。

## 历史介绍和PR2候选约定

# FS-Workbench 干净协作源码

> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。


当前文档/NBA候选批次：[准备读我](docs/planning/fs-docs-nba-batch-20261006/README.md)、[测试复现](docs/planning/fs-docs-nba-batch-20261006/TEST-REPRODUCTION.md)、[AI操作手册](docs/collaboration/OPERATION-GUIDE.md)、[状态](docs/collaboration/CURRENT-STATUS.md)。首批已入库，本批尚未提交。无需等D4/UI生产验收才审阅此增量；它们不纳本批，不被放行。所有releaseReady=false；无workflow/自动部署、凭据/运行数据/旧Git历史。
