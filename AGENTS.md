# AI 执行入口

先读 [全仓唯一执行规则](docs/ops/HOTFIX.md)，据用户当前任务连续完成已授权工作。不要从其它快照重建逐SHA审批、双人Approve或全套QA前置。

只再读本任务受影响的源码、模块合同、[负责人](docs/collaboration/OWNERS.json)及[来源映射](docs/collaboration/SOURCE-MAP.json)。它们提供范围和事实，不另设全局流程。Git窗口及发布串行。

[旧版记录](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/AGENTS.md)保留在Git历史，旧服务器故障、未上传和审批状态不代表当前事实。平台拒绝仍独立有效，不能以本文件绕过。

FC27 和绿茵计划的产品、技术、接口及交付文档使用 [统一标准与模板](docs/standards/fc27/README.md)。这是内容组织约定，按任务规模选用；不改变 HOTFIX 执行流程、模块合同、业务参数或授权，不导入额外审批。


<!-- global-ui-consistency-20261017 -->
UI 新建、修改与修复统一遵循项目全局 UI 规范，复用现有设计令牌、组件、布局、浅色/暗色主题和交互状态，不另建局部风格或复制一套共享样式。FS 工作台以 [UI 维护入口](ui-system/README.md) 及其当前规范、可编辑源为准；先核对活动版本，仅改任务涉及的界面并验证相关主题与状态，不因外观调整改变业务规则、权限、采集或调度，也不把本条扩展成全站重构或额外审批。

## 全局偏好与项目规则分层

通用偏好参考 [全局指令稿](docs/planning/codex-instructions-20261021/GLOBAL-INSTRUCTIONS.md)，适用范围、冲突情境与核验见 [说明](docs/planning/codex-instructions-20261021/README.md) 和 [核验记录](docs/planning/codex-instructions-20261021/AUDIT.md)。这是可复用文本与记录，仓库链接不自动安装用户全局配置。

全局约定协作方式，模块合同约定业务边界，具体执行仍只见 HOTFIX。按任务读取相关资料、复用有效证据；旧逐 SHA/双人审批与全套前置不能由历史快照恢复。文档任务以内容和读回验收，不触发业务采集或生产发布；UI/来源/价格等已确认业务特例保持。
