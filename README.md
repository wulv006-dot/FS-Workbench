# FS-Workbench

吴律与陈超的私有协作源码仓库。

- [唯一执行规则](docs/ops/HOTFIX.md)：定位、最小改动、相关检查、备份发布、真实使用确认；资料后补。
- [AI入口](AGENTS.md) / [协作操作入口](docs/collaboration/OPERATION-GUIDE.md)。
- [状态快照](docs/collaboration/CURRENT-STATUS.md)、[负责人](docs/collaboration/OWNERS.json)、[来源映射](docs/collaboration/SOURCE-MAP.json)。
- [注册权限源码/发布/验收索引](docs/collaboration/REGISTRATION-INDEX.md)：通过固定commit、文件SHA和本地模块ID查找；原始现场证据保留本地。
- [开发与测试](docs/DEVELOPMENT.md)、[发布与回退](docs/OPERATIONS-ROLLBACK.md)。

仓库包含历史候选、模板和记录，不是全站可直接部署的整包。main是代码集成基线，不能据merge推导生产恢复。旧manifest与releaseReady字段按其对象/时间读取，不作为所有任务的准入门槛。

## 知识与资料空间入口

- **查规则或执行任务**：先读 [AGENTS.md](AGENTS.md) 与其指向的唯一执行规则，再读 [知识读取说明](knowledge/README.md) → [条目索引](knowledge/index.json) → 任务适用的 Git 原文。按条目的模块、`layer`、`status`、`revision`、来源和替代关系选择，不凭文档日期或目录名判断现行版本。
- **浏览资料与追溯**：[Business 团队版（FS规范）](https://chatgpt.com/space/page_0685096df12881918422e94f9dbfe95d) · [个人版](https://chatgpt.com/space/page_6ae5813bdcf88191af4a69285736a9c1) · [历史资料](https://chatgpt.com/space/page_9827d03c50d08191a2b4478a253043e7)。空间负责阅读与追溯，正式规则仍以 Git 原文为准；入口和同步边界统一见 [资料空间说明](docs/planning/fs-space-knowledge-20261031/README.md)。

`current` 中同模块且有效的条目用于当前规则；`candidate` 只供审核/显式预览，`archive`、退役版本及历史快照只用于明确的历史查询，不恢复为执行指令。仓库索引的 `release_state=candidate` 是发布输入状态，条目标为有效也不证明生产已加载；部署、路由装载、真实模型使用及自然同步须分别核回执。

页面、附件和私有仓库各自遵循访问权限；页面分享不授予私库访问权，也不扩大 Hermes 原身份、模块或历史读取范围。只补入口不改变共享范围、规则版本或生产状态。

历史首次入库与旧候选证据仍可从[原版本](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/README.md)和Git历史读取；不重复初始化、旧SHA审批或全量归档。
