## FC27 Coins 定价合同入口

先按实际计划的写入协议选择合同。`fc27_curve_v6` 使用[FC27 V6.1 合同](docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md)，三平台旧标量计划和历史原操作使用[对应旧合同](docs/planning/fc-three-platform-20261110/CONTRACT.md)。部署、计划激活、真实执行及自然周期分别核验。共享 Sol 接入由原任务维护，FC 继续消费 `pricing_review_v3`。周报、经营管理台和已暂停的日报／月报仍按各自配置运行。

## FC 项目经理经营复盘

专项分析先读[取数入口](docs/planning/fc-project-review-20261119/README.md)和[经营复盘分工](knowledge/reporting/fc-project-owner.md)。SEO、广告投放的待核问题分别交该项负责人，其他 FC 经营环节由吴律亲自下钻和追踪。

## 用户分析与客户维护

日常用户复购、客户阶段、维护名单及 Hermes 或 FS 取数，读 `fs.customer.lifecycle` 和[用户分析与客户维护项目入口](docs/planning/users-cohort-maintenance-20261124/README.md)。用户分析的 FC 系列合并 FC26、FC27；阶段维护按 FC27（1327）生命周期。按实际目录与响应确认 v4、截止日及权限。

## FC 看板分类（2026-11-06 用户确认）

修改 FC 看板、趋势、导出或订单组利润时，读取[商品整单归属合同](docs/planning/fc-dashboard-category-20261106/CONTRACT.md)。知识源候选与真实数据验收状态见[本轮施工记录](docs/planning/fc-dashboard-20261106/IMPLEMENTATION.md)；代码存在不代表已部署。

## FS 核心原则（2026-11-03 创建者确认）

FS 由创建者吴律统一掌控，是以 Hermes 为智能中枢的 AI 驱动运营决策与执行系统。以实现吴律的最终目标为目的，判断限制是否服务于这一目标及系统定位；发现不符合的规则，应依据吴律的授权和实际证据提出或实施针对性调整，不为保留历史限制而阻碍目标。

在吴律明确授予的权限、业务目标与规则范围内，Hermes 享有最高执行及决策权，统一感知业务、积累知识、自主分析和决策，并调用 FS 能力执行、监控及复查。吴律拥有最终管理权，可随时调整目标、授权范围与规则，监督、暂停或接管任何任务。Codex、ChatGPT 和其他协作方按同一原则执行已授权工作；系统实际能力、身份传递与生产生效以代码和验收证据为准。

各入口和任务使用统一管理、可追溯、可更新、可回退的业务知识、技能与规则；成员通过 FS 获得经授权的使用能力，并保留各自的会话和数据访问边界。本原则不自动创建凭据、扩大个人数据或成员权限，也不取消实际适用的工具与平台安全限制；具体权限或安全设置的变化按吴律授权范围及相关合同处理。

## 重要｜开工必看

### 任务归属、Worktree 与交付（2026-11-09 用户确认）

本约定适用于所有 FS 开发任务及执行客户端；本仓库 `AGENTS.md` 是项目级开工入口，后续新会话也须读取。

- 开工先检查当前工作区绝对路径、仓库 origin、分支、未提交变更，以及本会话对应的任务和负责人，确认当前目录属于本任务后再操作。
- 继续旧任务时沿用原会话及本任务原有分支、Worktree，保留未完成工作；不得默认复用另一个任务的开发目录。
- 新开发任务由执行者自动获取最新 `origin/main`，记录实际基线提交，从该基线建立本任务独立分支和 Worktree。Codex 优先使用原生 Worktree 能力；DSH 使用独立明确的任务目录，不放入 Codex 管理或清理的临时目录。每个任务只有一个负责人。
- DSH 的任务目录与分支固定为 `D:/FS/DSH-worktrees/<task-id>` 和 `dsh/<task-id>`；创建前先查是否已有同任务分支及 Worktree，存在则沿用并核对 HEAD，不另起副本、不为对齐基线重置旧任务。
- 每个开发 Worktree 接入自己的 CodeGraph 索引。首次使用由执行者自动初始化，已有索引先核对项目路径和状态；每次查询显式传入本任务 Worktree 的绝对路径 `projectPath`。索引、缓存及临时锁只留本机并被 Git 忽略，不跨任务复制索引数据库；索引故障按下文规则处理，不阻断可继续的源码分析。
- 初始化新索引前，若正式 clone 存在本机 `codegraph.json`，仅在任务配置缺失时复用其排除配置并核对已被 Git 忽略；已有索引先查 `status`，必要时同步。MCP 接入以本会话实际 `codegraph_explore(projectPath=<本任务绝对路径>)` 返回源码及行号为准，仅配置存在或命令行查询成功不能代替该实调。
- 不覆盖、清理或提交其他 Agent 的未提交代码，不为准备新任务而重置其他任务的分支或工作区；Git 与共享发布操作继续串行。
- 完成后按照 `docs/ops/HOTFIX.md` 及实际仓库规则提交 PR，明确报告提交 SHA、PR、检查结果、合并状态和部署状态。未检查、未合并或未部署须如实标明；提交或合并不代表已部署，也不新增生产发布授权。

### 开工技能与技能选择（2026-11-16）

开发任务的开工与收尾清单见 `fs-task` 技能（`.agents/skills/fs-task/` 供 Codex，`.claude/skills/fs-task/` 供 Claude，两份保持同内容）。它只按顺序落实本节与 HOTFIX 的既有规则，不新增规则；冲突以本文件和 `docs/ops/HOTFIX.md` 为准。开始改仓库前先用它。

技能按描述自动匹配，匹配不稳时按下表手动点名（Claude 侧技能名带 `mattpocock-skills:` 前缀）：

| 场景 | 用 |
|---|---|
| 开工、提交、开 PR、交付报告 | `fs-task` |
| 报错、异常、变慢 | `diagnosing-bugs` |
| 有明确输入输出的逻辑（如定价、计算） | `tdd` |
| FC 定价规则变更、迁移后复盘、自动改价故障 | `fc-pricing-change-review`（`.agents/skills/` 供 Codex，`.claude/skills/` 供 Claude，两份同内容） |
| PR 前审查 | `code-review`，需要精简时加 `simplify` |
| 涉及登录、凭据、writer、权限 | `security-review` |
| 合并或 rebase 冲突 | `resolving-merge-conflicts` |
| 术语、ADR | `domain-modeling` |
| FC27 月报 | `fc27-monthly-report` |
| 核对经营数据口径 | `data:validate-data` |
| 活动页的发券、登录态、结账交接、页面追踪、优惠码/券归因，及发布到 187 与线上验收 | `fc-activity-wiring`（`.claude/skills/` 供 Claude，`.agents/skills/` 供 Codex，两份同内容） |
| 活动页、落地页设计（含发布到主站 MMOEXP 的跨域页面） | `design:design-critique`、`design:accessibility-review`、`design:ux-copy`，交接时用 `design:design-handoff` |

活动页的内容与结构以 `docs/standards/fc27/DESIGN-TEMPLATE.md` 和对应活动合同（如 `docs/planning/activity-center-v3/`）为准；FS 工作台内部界面以 `ui-system/README.md` 为准，两者不混用样式。设计技能只提供评审与写作辅助，不改变上述文档、业务规则、跨域接入合同或发布流程；跨域页面的手机宽度、主题和实际嵌入效果仍须在真实入口核对。营销类等其余插件技能与本项目开发无关，不主动使用。

### CodeGraph 与源码核对

在 FS 项目开始功能开发、修复或重构任务时，先调用 CodeGraph MCP 的 `codegraph_explore`，查询相关模块、调用关系和影响范围，再回看当前源码、测试与实际发布映射后实施修改。查询限于本任务 FS Worktree，每次显式指定其绝对路径 `projectPath`；代码图只提供导航，不证明生产版本、权限或业务运行状态。

CodeGraph 是本地程序与 MCP 服务，不是 Skill。工具不可用或索引过期时说明原因，使用源码检索继续，不为工具故障阻塞开发；索引和临时锁文件留在本地，不入库。纯文案、简单配置或范围明确的微小改动不必全仓建图。原业务规则继续适用。

<!-- users-live-query-current-20261102 -->
## 用户订单按需查询（2026-11-02 已上线）

Admin 派生数据按需查询沿用 FS 全局权限和现有真实登录会话。当前 HTTP 合同见 [实时订单调用规则](releases/fs-dashboard/tiered-data-access-20261101/LIVE-ORDER-PAGINATION.md)：每页最多 20 条、按返回游标继续；单次最多 28 个上海自然日，超过范围分段，最早日期仍受 365 天边界限制。精确客户邮箱只从受限 JSON POST 请求体传入，须有原有 private 权限；邮箱不放浏览器 URL 或操作日志；2026-11-09 用户撤销模型输出身份信息禁令：在原 FS/private/对象权限范围内，邮箱、UID 和原订单号可返回模型用于查询与分析，不强制匿名汇总，不新增个人授权名单。保持字节、时限和共享并发限制，报错/中断不能当空结果或完整统计。结果为实时非快照，范围内最早不等于客户终生首次购买。PR757 已合并，生产 release 为 `nav-20261102T150526Z`；旧“五条第一页”说明仅保留为历史。Hermes 尚缺可信 actor/session 传递，不得通过固定 `wulv` 冒用调用者。

## 2026-11-02：最小充分实现与写入核验

本段记录用户确认的规则；代码实现、发布和实际验收以各自回执为准，不凭文档断言线上已生效。

当前需求采用最小充分实现：外部输入、权限、持久化及真实写入边界做必要校验；内部已验证契约不逐层重复。新增框架、兼容层、开关或兜底须对应明确需求、契约、已知故障或具体高后果风险；不吞异常、不伪装成功。修到根因及必要调用链，避免无关重构；只运行相关回归和现有必要CI，验收达成后停止，未验项如实记录，不额外设置门禁或监控。

FC 改价按原协议确认。`fc27_curve_v6` 使用本次 Admin 成功回执与 MMOEXP 主站完整价表读回。旧标量使用本次 Order 成功回执与 Admin 同商品单位价读回。公开页和地区展示可按需独立验证。超时或没有明确成功回执时沿原 ID 核对，保留身份、原回执、CAS 和幂等保护。

数据汇总优先使用Admin实际支持的原生范围与汇总能力；详情按对应接口真实日期、分页及覆盖上限分段，缺失和部分覆盖明确标示。已核实的28天限制只适用于对应详情接口，不统一机械切分所有汇总查询。

<!-- fc-pricing-p0-availability-20261101 -->
## FC 自动改价 P0 可用性（2026-11-01 用户确认）

FC 自动改价及必要依赖属于 P0 核心常驻链路，豁免全局节省资源、闲置回收、按需休眠及优化性停用、降频或节流。范围包括调度器、API、worker、当轮采集、Order 会话/浏览器、Admin 数据通道及原操作对账；不能只豁免主进程而回收依赖。正常任务结束的临时进程释放与防错价、幂等、超时原 ID 对账保护继续保留。改变现有自动化能力前须证明完整链路不受影响并完成真实入口与自然周期验收，不能以优化为由先降级后观察。

<!-- dashboard-shipping-profit-current-20261030 -->
### 经营看板毛利：Order发货统计（2026-10-30用户最终确认）

经营看板全局、分游戏及RS筛选的毛利卡、毛利率和每日曲线，改用Order「统计管理→发货统计」：交货类型=订单发货，按所选日期时间、对应Order游戏ID、网站及原类目/区服筛选。毛利（¥）=同一响应的人民币销售总额−采购总额；分游戏毛利率取该行原值，全局按总毛利÷总销售额计算，不平均各游戏/每日比例，不用Admin美元销售额乘率。每日仍按同一发货统计口径取完整北京自然日，缺日留空，今日区间卡按截至读取时间显示。

本条覆盖2026-10-24逐单实际成本作默认主展示、2026-10-25刷新合同中的相关利润表述，以及本次中途提出但未实施的「订单统计利润率×美元订单额」预估方案。页面保留八张主卡和简洁「Order发货统计」来源，不增加冗长警告；Admin销售、订单、客户及客单价口径保持。主视图不再自动请求actual-profit，原逐单核算接口、归档与Hermes按需查询能力保留。

内部口径：发货统计按交易时间和交货记录汇总，不是付款日已完成订单的同一群体，也未证明排除退款、申诉、欺诈。2026-10-30按精确订单号只读核对，当前「问题订单」「欺诈报告」「已退款·部分退款」各一笔仍在发货统计有金额；结算状态仅未结算/已结算。用户知悉后明确选择直接采用此统计。不得声称它是排除上述损失后的净利润。FC 定价与成本按计划协议执行，继续沿用原会话权限、自动计划、原 ID、CAS、回执和 UNKNOWN 对账。

<!-- fc-three-platform-current-20261110 -->
## FC27 Coins 当前定价：三平台独立、两段全球价（2026-11-14）

使用 `fc27_curve_v6` 的计划遵循[FC27 V6.1 经营与执行合同](docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md)。PS、Xbox、PC 分别核算优惠、成本、价格、试验及实际效果。各平台全球统一价，主站 MMOEXP 为基准，继承同一商品模型的站点跟随主站。SBC、Players、Packs、捆绑包和进化继续读取请求平台的实际 Coins 美元 rate。

2026-11-17 市场定位锚按实际计划版本生效：`market-anchor-v1` 两段分别取 Lootbar/U7Buy 定位目标，替代三小时 A/B/C；旧策略与影子观察期继续原逻辑。初始参数、报价缺失、保险和回退见 V6.1 合同；Git／部署／策略修订分别取证。预测成本采用同平台近三小时有效成交中位数，不足六笔取最近六笔，至少三笔；历史真实成本不改。短期验收通过即推进下一阶段，24 轮、48 小时及自然周长期验收并行记录，不阻断施工。

启用 `margin_band` 的计划按实际修订的北京时间决策小时及平台目标判断两量段价格，00:00 至 00:15 前保持经营价。每小时继续核安全底线。周阶梯按两段合计实际毛利额和订单量评估目标利润率，竞品走廊参数由人工计划修订。读取[V6.1 分时段规则](docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md#分时段目标利润率阶段-5)及实际修订和决策证明。

两段分别为低于 1000K 和 1000K 及以上。按实际生效的报价合同复盘。采用[普通购买档合同](docs/planning/fc27-market-quotes-20261124/CONTRACT.md)后，Lootbar、U7Buy 分档按普通购买价定位并参与保险，U4GM 仅用于监控价差。旧回执按原实交口径解释。两段保留自动调价能力。临时成本保护沿原财务条件处理，成本回落时按当轮数据释放。旧 A/B/C 策略的临时保护沿原经营基准 A。

各平台按北京时间 D-3 至 D-1 三个完整自然日的同单 ES 实际优惠美元总额除以 Admin 优惠前商品美元总额计算平均优惠。按金额加权，缺项如实标记，写前复核同一窗口与实际归档修订。候选按真实购买量、赠送、采购、汇率和舍入逐档核保本，平台主篮与近期篮的组合采购毛利率各以 18% 为底线。未启用 `margin_band` 的 V6.1 计划仍用 25% 作经营比较。以实际毛利额、整体利润率与订单量验收经营效果。

改价前读取商品模型的 ALL 完整价表，原 writer 每平台单次保存，保留数量和赠送。收到本次 Admin 成功回执并重读 MMOEXP 主站（site 266）完整价表一致后确认生效。北京时间午夜后，V6 自动轮等共享 ES 昨日主站 FC27 订单发布，再接续同一任务。每 60 分钟的 P0 调度、计划身份、原 ID、CAS 和 UNKNOWN 对账沿原链路执行。历史 V6 证明按原记录的优惠窗解读。旧标量计划和历史原操作按[三平台旧协议](docs/planning/fc-three-platform-20261110/CONTRACT.md)及[原财务合同](docs/planning/fc-pricing-v3-20261026/DUAL20-NO-BUDGET-CHANGE.md)处理。

<!-- admin-api-direct-takeover-20261028 -->
## 本轮接管与直接 API（2026-10-28 用户确认）

Admin 接入沿[原修复合同](docs/planning/admin-recovery-review-20261028/CONTRACT.md)，直接 HMAC API 主线 8912、备用 8911、容器 8913 桥。8767 已退役，原会话和 OCR 回退仍按该合同处理。旧标量通过原 Order writer 执行，Admin 读取、同步和核价走 API，保留 Price 原价展示，实价核同商品 `unit_price`。V6.1 走原 writer 的 Admin 完整价表分支。2026-10-28 修复按 P0 至 P3 推进，并补 P4 多人并发。原 ID、并发保护和自动化按对应协议执行。

<!-- fc-v3-historical-rules-archived-20261029 -->
早期 FC 定价规则见[历史记录](docs/planning/fc-pricing-v3-20261026/history/AGENTS-FC-RULES-BEFORE-100K-20261029.md)。当前执行按本文件顶部的协议入口选择合同，历史操作沿其原协议追溯。

<!-- business-filter-layout-current-20261025 -->
## 经营面板范围与游戏筛选（2026-10-25）

PR470/474已合并并沿原publisher分11+1目标发布；本次12个目标的源码与生成路由精确清单见SOURCE-MAP，源码沿releases/fs-dashboard/dashboard-refresh-20261025/source/维护，其他文件保持各自活动源。网站范围→分组游戏→时间，RS三站锁RS；旧summary未传网站仍取原全站，毛利独立缓存兼容，FC明细网站联动。当前合同、逐链路影响、活动SHA和实际验收见docs/planning/business-filter-layout-20261025/。原成本/权限/会话/调度及当前FC定价合同保持；不把Git候选目录或文件装配当新模型/自然周期验收。

<!-- operator-report-core-current-20261025 -->
## 所有报告的生成与审核核心（2026-10-25用户明确纠正）

Hermes及Codex/ChatGPT产出、指导或审核任何报告、文字分析，优先遵循[报告核心逻辑](docs/planning/operator-report-review-20261025/REVIEW-STANDARD.md)：先回答最需要判断的问题，给有主次的全局结论、方向性推断和价值取舍，再用关键事实说明理由、落到行动。图表/HTML按需，短答不凑图造页；需要可视化时认真核排版、对照、交互和人的阅读体验。细微口径差异不自动取消方向判断，只有可能反转结论/行动或造成实质误导时深查；内部精核不扩成前台审计。用户明确审计/论文时按专项目的执行，真实数据、财务公式、实际执行权限及UNKNOWN保护不变。23号指定报告为阅读参照，24号旧补报已被否定；实际落实与后续验收见同目录PLAN/ACCEPTANCE。

<!-- dashboard-refresh-current-20261025 -->
## 经营看板八主卡与刷新（2026-10-25）

用户已确认同范围旧值先展示、顶部提示刷新并替换；默认销售额、订单数、毛利、毛利率、新客人数、复购率、新客占比、客单价八卡，其他收起。来源、历史更正核验、当前积压与未支付来源缺口，见 `docs/planning/business-dashboard-refresh-20261025/CONTRACT.md`；活动源码与正式发布/验收见同目录SOURCE-MAP和ACCEPTANCE。不改变逐单毛利公式、权限、会话、调度、当前FC定价合同；Git候选知识不冒充生产目录或真实模型应用。

<!-- business-shipping-profit-current-20261024 -->
## 经营看板利润计算规则（2026-10-24）

全局/分游戏主利润与每日曲线按Order“统计管理→发货统计”同网站、游戏、原生类目、交易时间取人民币销售减采购；分游戏原生率、全局总利润÷总销售，不再用Admin付款USD乘参考率。零分母率不适用，未知不补零，负利润保留，非净利润；同订单Admin整单人民币收入减Order实际成本及覆盖证明独立展示。规则见[现行业务基准](docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md)及[计算合同](docs/planning/business-shipping-profit-20261024/CONTRACT.md)。PR435/436已上线，活动源见[交付与版本](docs/planning/business-shipping-profit-20261024/DELIVERY.md)。仅看板Shipping字段迁移；旧primary兼容、Hermes其他报告、当前FC定价合同、权限/会话/调度和原UNKNOWN保持。Git文档/候选知识与生产装入、模型实际使用分别验收。

<!-- fc27-report-method-current-20261024 -->
## FC27经营报告字段与呈现

FC 经营日报、周报、月报和专项分析成稿默认启用 [FC 经营分析图解](.agents/skills/fc-report-visuals/SKILL.md)，Claude Code 从同名项目技能发现。取证按[字段使用与呈现规则](docs/planning/fc27-daily-teaching-20261024/REPORT-RULES.md)核来源、范围、单位、分母、计算、可支持的结论及主动补查；历史实例只作方法参考。Ads 和流量按经营重要性充分分析，详细界面设计和阅读顺序按本次问题自主安排。Git 版本、项目技能发现、Hermes 实际加载和真实报告应用分别验收。Admin 优先／Order 补缺、现行业务基准及财务口径、预算、调度及权限沿原合同。

<!-- fc-v3-current-20261026 -->
FC 当前执行以实际计划协议和已发布版本为准。`fc27_curve_v6` 走本文件顶部的 V6.1 合同。旧标量 `smart`、`daily` 和 `revenue_sprint` 的原版本见[旧标量基线](docs/planning/fc-pricing-v3-20261026/CURRENT-BASELINE.md)。

# AI 执行入口

2026-11-10用户补充：历史UNKNOWN有后续有效真实现态覆盖后退出当前阻断，保留旧记录而不冒充旧POST成功；仍在途、现态缺失或新UNKNOWN才沿原ID核验。覆盖绑定原商品身份、真实Admin现态和时间及原任务已结束的证据，理论预览不算。未来新写继续当前来源、CAS和原写后核验，不让历史记录反复卡住新逻辑。

先读 [全仓唯一执行规则](docs/ops/HOTFIX.md)，据用户当前任务连续完成已授权工作。不要从其它快照重建逐SHA审批、双人Approve或全套QA前置。

只再读本任务受影响的源码、模块合同、[负责人](docs/collaboration/OWNERS.json)及[来源映射](docs/collaboration/SOURCE-MAP.json)。它们提供范围和事实，不另设全局流程。Git窗口及发布串行。

[旧版记录](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/AGENTS.md)保留在Git历史，旧服务器故障、未上传和审批状态不代表当前事实。平台拒绝仍独立有效，不能以本文件绕过。

FC27 和绿茵计划的产品、技术、接口及交付文档使用 [统一标准与模板](docs/standards/fc27/README.md)。这是内容组织约定，按任务规模选用；不改变 HOTFIX 执行流程、模块合同、业务参数或授权，不导入额外审批。


<!-- global-ui-consistency-20261017 -->
FS 界面沿用主题配色和浅色／深色令牌。布局、卡片与图表按场景自主设计。关键数据用卡片，每个分析模块回答一个问题，给一句结论、内联 SVG 图表和「这块怎么读」，用真实数字举例。图表颜色走主题变量，数据来自真实接口，缺失、部分覆盖和未满期如实显示。新设计先出可打开的 demo，经用户确认再实施。旧布局约束供历史参考，按 [UI 维护入口](ui-system/README.md) 的「视觉细则」和[参考稿](docs/planning/users-cohort-maintenance-20261124/design/)执行：一个单元一个主数字，不用「·」把属性拼成长串，复杂对象做成小卡片，默认打开最常用视图，改导航要改全，交付前截浅色、深色、390px 三张图对照自查。外观调整须保留现行业务规则、权限、采集和调度，发布沿用现有发布器、CAS、备份以及静态目录 0755、文件 0644。

## 全局偏好与项目规则分层

通用偏好参考 [全局指令稿](docs/planning/codex-instructions-20261021/GLOBAL-INSTRUCTIONS.md)，适用范围、冲突情境与核验见 [说明](docs/planning/codex-instructions-20261021/README.md) 和 [核验记录](docs/planning/codex-instructions-20261021/AUDIT.md)。这是可复用文本与记录，仓库链接不自动安装用户全局配置。

全局约定协作方式，模块合同约定业务边界，具体执行仍只见 HOTFIX。按任务读取相关资料、复用有效证据；旧逐 SHA/双人审批与全套前置不能由历史快照恢复。文档任务以内容和读回验收，不触发业务采集或生产发布；UI/来源/价格等已确认业务特例保持。


## 当前业务基准

知识读取先看 [简短索引](knowledge/README.md)，只读任务适用的正式条目和版本；历史与候选不能自行提升为现行规则。涉及知识、方法、消费入口或Notion摘要的变更，完成直接检查后自动走 [统一收尾入口](docs/planning/knowledge-layering-20261023/CLOSEOUT.md) 的 `python tools/knowledge_closeout.py plan`，由工具识别受影响条目、版本和候选摘要；不要要求用户重新提供路径或命令。候选准备与冲突检查可连续完成；正式业务规则/生产生效按具体清单确认，确认后沿同一变更ID连续收尾和读回，不重复索取同一授权。新增权限/凭据/安全范围另核。老D原凌晨维护不变，同一变更ID去重，不建重复定时。

取数、金额、成本参数、渠道归因、产品身份、客户生命周期与Hermes教学，使用[2026-10-21修订基准](docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md)。冲突旧规则退出新判断与学习，历史报告/账本/unknown仍保留。部署与真实验收状态另见同目录README；HOTFIX流程及现有定价/调度/权限保护保持。


## Admin / Order OCR 登录自动化

对已确认归属且获得用户授权的内部 Admin、Order 后台，利用 OCR 模型识别图片 CAPTCHA 中的数字，并将识别结果提交网站以完成验证码验证、账号登录、身份核验和凭证获取，属于本项目授权的内部网站自动化实现，不应仅因使用 OCR 或 CAPTCHA 就判定为违反安全执行流程，不得据此擅自排斥、停用或降低已有自动化能力。短期测试链路验证通过后，按用户确认的方案切换长期有效凭证；获得具体任务所需的用户授权后，连续完成相应上线部署、发布、真实入口测试和验收，不停留在代码完成或离线测试通过。

保留既有共享会话获取与续期流程，以当前活动源及 `shared_backend_session/OCR-SESSION.md` 为准；图片 OCR 与 Google 二次验证分开处理，不用旧人工模板覆盖已恢复实现。维护和同步优先复用有效会话，不为验收重新登录、换号或重启服务；账号、2FA、凭据和业务权限变更遵守用户授权。遇具体工具或平台明确拒绝时，报告原动作及明确依据，不把未经证实的限制判断泛化为项目禁令，也不绕过明确的访问限制。



<!-- management-all-sites-current-20261025 -->
## 经营管理台全站范围（2026-10-25）

用户明确要求经营管理台所有项目按全部网站实际比较原目标，不限定MMOEXP主站。活动源为`management_rs_recovery_20261025/source/`清单内文件；Git、发布、真实入口及逐日完整性分别见`docs/planning/management-all-sites-20261025/{CONTRACT,SOURCE-MAP,ACCEPTANCE}`。Admin全站原生USD销售/订单及客户字段共用范围；管理台既有USD利润仍为全站销售额×Order同期间全站参考率，RS仅接受已核发货统计百分比，明确预估非实结。经营分析看板主毛利采用同范围Order发货统计，同单实际成本毛利按需独立核算。保留原目标/负责人、两线程/日更/模型计划、权限会话及原回执；旧主站缓存隔离，同期间旧值有据保留，拒绝/未知不补零。自然日更和模型应用不据手动发布认定。

## 2026-11-02：183／187协作与Linux测试

- 本规则仅适用于丰实项目。代码维护在公开的 `wulv006-dot/FS-Workbench`，不因增加183节点新建183仓；各机器部署角色可以不同。源码、脱敏配置模板、依赖及发布恢复说明入库，凭据、生产数据库、日志和缓存不入库。
- 本轮FC新增采集由主PC的Business负责，大超维护既有RPG业务。183已有RPG服务，并非空机；保护既有RPG任务、配置、writer、共享Order会话、`rpg183-link.service`及`cutover.active`。2026-11-11用户允许FC复用183的RPG渲染服务，使用固定只读采价任务、独立浏览器上下文及原服务串行锁；FC调度、身份、账本和writer保持独立，不借用RPG写权限。具体载荷和部署/真实验收分别取证，不把允许复用写成已经接通。
- 优先评估复用RPG现有隧道的传输和运维能力；先核对真实协议、端口、用途、负责人、隔离和容量。适合则复用；不适合则记录具体冲突，再设计最小独立通道。复用传输不等于共享业务会话、token、后台账号或writer；本规则不授予修改SSH、防火墙、安全组或隧道参数的权限。
- 183是本项目Linux测试的默认环境：Linux单测、集成和兼容验证优先使用独立目录或容器并匹配目标Python、依赖及系统行为；Windows、T3等平台专属测试仍在对应环境进行。183的Debian 12通过不自动证明187旧环境兼容。普通已授权隔离测试不逐次重复审批；先确认资源与端口预算及既有RPG不受影响。重负载、破坏性操作、真实改价或订单写入、生产数据写入、凭据或网络变更仍须相应具体授权。183不可用时报告原因并使用已授权的隔离替代环境，不悄悄转到187生产环境。
- 187保持FC调度、算价和唯一FC writer；183仅提供新增FC采集。故障接替遵守租约、来源总限频、报价TTL及现有原ID、CAS和UNKNOWN对账保护。既有RPG writer保持其独立职责；本规则不改变其他模块。FC P0常驻链路、依赖及每60分钟自然轮不因测试、分流或节省资源而降低能力。

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`wulv006-dot/FS-Workbench`) and are driven with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles keep their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`); wayfinding uses `wayfinder:map` plus `wayfinder:research` / `wayfinder:prototype` / `wayfinder:grilling` / `wayfinder:task`. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context layout: the root `GLOSSARY-MAP.md` points to per-context `GLOSSARY.md` files, with system-wide ADRs in `docs/adr/`. See `docs/agents/domain.md`.
