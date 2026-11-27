# FS-Workbench 项目规则

## 硬约束

- **FS 核心原则。** 吴律拥有最终管理权，可调整目标、授权和规则，监督、暂停或接管任务。Hermes 是 FS 的智能中枢，在吴律明确授予的权限、业务目标和规则内行使最高执行及决策权，成员沿用各自的会话与数据访问边界。
- **开工与交付。** 改仓库前使用 [`fs-task`](.agents/skills/fs-task/SKILL.md)，核对任务、唯一负责人、工作树、origin、分支和未提交改动；旧任务沿用原工作树，新任务从最新 `origin/main` 建独立分支与工作树并记录基线。执行、验证和提交 PR 遵循 [HOTFIX 全仓唯一执行规则](docs/ops/HOTFIX.md)，Git 与共享发布串行，分别报告 CI、合并、部署和真实入口结果。
- **FC 自动改价 P0 可用性。** 维持每 60 分钟自然轮及调度、API、worker、采集、Order 会话、Admin 通道和原操作对账常驻，豁免节省资源导致的回收、休眠、停用、降频或节流。改变现有自动化能力前须通过完整链路、真实入口与自然周期验收，保留原防错价和对账保护。
- **Order 后台单会话。** 187 仅 `fs-order-session` 可以登录 Order，使用 `wulv`；Order 仅对 `wulv`、`chenchao` 免谷歌验证器。其他程序、脚本与 Agent 一律通过 `fs_order_client` / `order_http` 取共享会话，不得登录或提交 Order 凭据，`pr-fast` 的 `order-single-session` 强制执行。
- **最小充分实现与写入核验。** 修到根因及必要调用链，在外部输入、权限、持久化和真实写入边界校验，内部复用已验证契约。真实写入保留原身份、回执、CAS 和幂等，超时或结果未知沿原 ID 核验；FC 改价按对应协议核成功回执和价表或单位价读回。
- **凭据与平台安全。** 凭据、生产数据库、日志和缓存不得入库，权限和安全设置按当前用户授权及相关合同处理。工具、平台安全限制与审核独立生效，明确拒绝时报告原动作、来源与理由。

## 协作约定

- **审查分级。** 审查中，只有会算错钱、丢数据、越权、发错消息或导致故障的问题阻断合并或上线。其余记为建议，可后续处理。同一 PR 最多审两轮，仍未通过交用户决定。
- **规则写法。** AGENTS.md 与规则文件只写做什么、不做什么。历史事故、原因和证据放到文档或记忆。
- **用户确认。** 删除数据、停服、花钱、对外发消息、修改业务方向或规则、变更密钥、凭据或权限须经用户确认。清单之外且已授权的事项连续推进，无需逐次请示。
- **改全。** 同一事实在代码、文案、文档和测试中同步更新，并按旧说法搜索全仓确认覆盖。
- **纠错固化。** 用户纠正或审查退回的问题，能机械判断就优先加测试或 CI 守卫，无法机械判断再写成文字规则。

<!-- core-rules-end -->

## 场景索引

Codex、Antigravity 和 Claude Code 共用本入口。项目技能只编辑 `.agents/skills/`，运行 `python tools/sync_agent_skills.py --apply` 生成 Claude 镜像。

- FS 授权、Hermes 职责与成员边界 → [FS 核心原则](docs/agents/agent-workflow.md#fs-principles)。
- 新任务、续做、Worktree、CI 与交付 → [任务归属、Worktree 与交付](docs/agents/agent-workflow.md#start-work)。
- 按场景选择项目技能 → [开工技能与技能选择](docs/agents/agent-workflow.md#skill-selection)。
- 制订大方案、独立起草、合成与处理分歧 → [大方案流程](docs/agents/large-proposals.md)。
- 定位代码、查询调用关系、初始化或修复索引 → [CodeGraph 与源码核对](docs/agents/agent-workflow.md#codegraph)。
- 执行任务、查负责人或来源映射、对账历史 UNKNOWN、写 FC27 或绿茵计划文档 → [AI 执行入口](docs/agents/agent-workflow.md#execution)。
- 判断全局偏好、项目执行规则和模块合同的适用范围 → [全局偏好与项目规则分层](docs/agents/agent-workflow.md#rule-layers)。
- 查环境事实、历史原因和已知坑 → 先读[共享开发记忆](docs/memory/MEMORY.md)。私有客户端记忆只放个人偏好，收尾时把项目事实归入 `docs/memory/`、AGENTS.md 或测试。
- FC27 Coins 改价或追溯原操作 → [定价合同入口（V6.1 与旧标量）](docs/agents/fc-pricing.md#pricing-contracts)。
- 核对三平台两段价、市场定位锚、分时段目标、分段数量加权成本与活动让利保护 → [FC27 Coins 当前定价](docs/agents/fc-pricing.md#current-pricing)。
- 调整改价依赖、资源和调度，或验收自动化 → [FC 自动改价 P0 可用性](docs/agents/fc-pricing.md#pricing-p0)。
- 回溯早期定价规则或旧标量版本 → [历史规则](docs/agents/fc-pricing.md#historical-pricing)及[旧标量版本](docs/agents/fc-pricing.md#legacy-pricing)。
- 修改 FC 看板分类、趋势、导出或订单组利润 → [FC 看板分类](docs/agents/dashboards.md#fc-categories)。
- 核经营看板人民币毛利、日粒度与退款覆盖 → [现行发货统计口径](docs/agents/dashboards.md#shipping-profit-current)及[历史计算规则](docs/agents/dashboards.md#shipping-profit-history)。
- 修改经营看板网站、游戏与时间联动 → [经营面板范围与游戏筛选](docs/agents/dashboards.md#business-filters)。
- 修改经营看板八张主卡、缓存展示或刷新 → [经营看板八主卡与刷新](docs/agents/dashboards.md#dashboard-refresh)。
- 核经营管理台全站目标、日更与预估利润 → [经营管理台全站范围](docs/agents/dashboards.md#management-scope)。
- FC 项目经理经营复盘与 SEO、广告、其他事项分工 → [FC 项目经理经营复盘](docs/agents/reporting.md#project-review)。
- 生成或审核报告和文字分析 → [报告核心逻辑](docs/agents/reporting.md#report-review)。
- 出 FC 日报、周报、月报和专项分析 → [FC27 经营报告字段与呈现](docs/agents/reporting.md#fc-reporting)。
- 查用户复购、客户阶段和维护名单 → [用户分析与客户维护](docs/agents/backend-access.md#customer-lifecycle)。
- 实时查用户订单、分页、精确邮箱或 Hermes 身份 → [用户订单按需查询](docs/agents/backend-access.md#live-order-query)。
- 核 Admin 直接 API、备用桥、旧标量或 V6.1 writer → [本轮接管与直接 API](docs/agents/backend-access.md#admin-direct)。
- 维护后台登录、共享会话、OCR 或二次验证 → [Admin / Order OCR 登录自动化](docs/agents/backend-access.md#ocr-login)。
- 定实现边界、数据分段、改价写后读回 → [最小充分实现与写入核验](docs/agents/business-knowledge.md#implementation-and-verification)。
- 读取现行业务知识、核取数口径、收尾知识或方法变更 → [当前业务基准](docs/agents/business-knowledge.md#business-baseline)。
- 183／187 分工、Linux 隔离测试或复用 RPG 通道 → [183／187 协作与 Linux 测试](docs/agents/server-coordination.md#server-coordination)。
- 新建、修改或验收 FS 界面、主题与手机宽度 → [FS 界面规范](docs/agents/fs-ui.md#fs-ui)。
- 查 GitHub Issues、分诊标签、术语和 ADR → [Agent skills](docs/agents/agent-workflow.md#agent-skills)、[Issue tracker](docs/agents/issue-tracker.md)、[Triage labels](docs/agents/triage-labels.md)、[Domain docs](docs/agents/domain.md)。
