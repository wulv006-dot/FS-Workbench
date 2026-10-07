# FS-Workbench

吴律与陈超的私有协作源码仓库。

- [唯一执行规则](docs/ops/HOTFIX.md)：定位、最小改动、相关检查、备份发布、真实使用确认；资料后补。
- [AI入口](AGENTS.md) / [协作操作入口](docs/collaboration/OPERATION-GUIDE.md)。
- [状态快照](docs/collaboration/CURRENT-STATUS.md)、[负责人](docs/collaboration/OWNERS.json)、[来源映射](docs/collaboration/SOURCE-MAP.json)。
- [注册权限源码/发布/验收索引](docs/collaboration/REGISTRATION-INDEX.md)：通过固定commit、文件SHA和本地模块ID查找；原始现场证据保留本地。
- [开发与测试](docs/DEVELOPMENT.md)、[发布与回退](docs/OPERATIONS-ROLLBACK.md)。

仓库包含历史候选、模板和记录，不是全站可直接部署的整包。main是代码集成基线，不能据merge推导生产恢复。旧manifest与releaseReady字段按其对象/时间读取，不作为所有任务的准入门槛。

历史首次入库与旧候选证据仍可从[原版本](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/README.md)和Git历史读取；不重复初始化、旧SHA审批或全量归档。
