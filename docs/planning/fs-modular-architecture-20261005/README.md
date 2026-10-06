> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。

# 模块化架构规划交付索引

- 主文档：[当前架构评估与模块化改造方案](当前架构评估与模块化改造方案.md)
- 支持证据：`architecture-static-verification.json`，本轮本机静态盘点，含SHA、imports、表名、归档unit白名单字段，不含运行数据。
- 核验方法：`inspect_architecture.py`，仅Python标准库读文本/AST/哈希；未执行候选或原包。
- 交付校验：`delivery-validation.json`，报告SHA、冻结候选复核和两份最终复审SHA。
- Library结果：`library-delivery-status.json`，以官方调用实际结果为准；失败不绕过Windows元数据限制。

范围：只做架构评估与规划；C3冻结311文件不改，生产、Git、账号、调度、Ponytail不改。

推荐：单仓、统一现有路径入口、模块独立运行/产物/数据/发布账本；先完成运行闭包与FC范围/NBA业务决策，再逐模块实施。

未决事项和真实运行门槛见主文档第9、11、12节。本文是任务交付索引，不替代工程唯一`HANDOFF.md`或`OPEN-DECISIONS.md`事实登记。
