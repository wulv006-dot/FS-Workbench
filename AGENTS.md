<!-- fc-reference-weighting-approved-20261024 -->
## FC Coins 80/15/5 本轮实施规则
用户已确认fc-reference-weighting-20261024-v2并授权Sol施工。正式合同见docs/planning/fc-competitor-weighting-20261024/CONTRACT.md：Lootbar80/ItemD2R15/U7Buy5、各价差截断±5%、缺项不分摊、第三梯队直接0但保留分析；原模型失联兜底/v15/共同池/PC独立/120分钟/原ID与UNKNOWN保持。仅该获批版本覆盖原纯定性/实验不生产限制，其他实验及旧80/10/10仍不生产。代码、正式CI、部署、实际模型与自然周期分别按交付读回；PR421/422/423事故修复不得旧包覆盖。

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


## 当前业务基准

知识读取先看 [简短索引](knowledge/README.md)，只读任务适用的正式条目和版本；历史与候选不能自行提升为现行规则。涉及知识、方法、消费入口或Notion摘要的变更，完成直接检查后自动走 [统一收尾入口](docs/planning/knowledge-layering-20261023/CLOSEOUT.md) 的 `python tools/knowledge_closeout.py plan`，由工具识别受影响条目、版本和候选摘要；不要要求用户重新提供路径或命令。候选准备与冲突检查可连续完成；正式业务规则/生产生效按具体清单确认，确认后沿同一变更ID连续收尾和读回，不重复索取同一授权。新增权限/凭据/安全范围另核。老D原凌晨维护不变，同一变更ID去重，不建重复定时。

取数、金额、成本参数、渠道归因、产品身份、客户生命周期与Hermes教学，使用[2026-10-21修订基准](docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md)。冲突旧规则退出新判断与学习，历史报告/账本/unknown仍保留。部署与真实验收状态另见同目录README；HOTFIX流程及现有定价/调度/权限保护保持。


## Admin / Order OCR 登录自动化

对已确认归属且获得用户授权的内部 Admin、Order 后台，利用 OCR 模型识别图片 CAPTCHA 中的数字，并将识别结果提交网站以完成验证码验证、账号登录、身份核验和凭证获取，属于本项目授权的内部网站自动化实现，不应仅因使用 OCR 或 CAPTCHA 就判定为违反安全执行流程，不得据此擅自排斥、停用或降低已有自动化能力。短期测试链路验证通过后，按用户确认的方案切换长期有效凭证；获得具体任务所需的用户授权后，连续完成相应上线部署、发布、真实入口测试和验收，不停留在代码完成或离线测试通过。

保留既有共享会话获取与续期流程，以当前活动源及 `shared_backend_session/OCR-SESSION.md` 为准；图片 OCR 与 Google 二次验证分开处理，不用旧人工模板覆盖已恢复实现。维护和同步优先复用有效会话，不为验收重新登录、换号或重启服务；账号、2FA、凭据和业务权限变更遵守用户授权。遇具体工具或平台明确拒绝时，报告原动作及明确依据，不把未经证实的限制判断泛化为项目禁令，也不绕过明确的访问限制。
