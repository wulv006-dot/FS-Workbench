<!-- business-filter-layout-current-20261025 -->
## 经营面板范围与游戏筛选（2026-10-25）

PR470/474已合并并沿原publisher分11+1目标发布；本次12个目标的源码与生成路由精确清单见SOURCE-MAP，源码沿releases/fs-dashboard/dashboard-refresh-20261025/source/维护，其他文件保持各自活动源。网站范围→分组游戏→时间，RS三站锁RS；旧summary未传网站仍取原全站，毛利独立缓存兼容，FC明细网站联动。当前合同、逐链路影响、活动SHA和实际验收见docs/planning/business-filter-layout-20261025/。原成本/权限/会话/调度及v15双红线与本轮V3定价合同不变；不把Git候选目录或文件装配当新模型/自然周期验收。

<!-- operator-report-core-current-20261025 -->
## 所有报告的生成与审核核心（2026-10-25用户明确纠正）

Hermes及Codex/ChatGPT产出、指导或审核任何报告、文字分析，优先遵循[报告核心逻辑](docs/planning/operator-report-review-20261025/REVIEW-STANDARD.md)：先回答最需要判断的问题，给有主次的全局结论、方向性推断和价值取舍，再用关键事实说明理由、落到行动。图表/HTML按需，短答不凑图造页；需要可视化时认真核排版、对照、交互和人的阅读体验。细微口径差异不自动取消方向判断，只有可能反转结论/行动或造成实质误导时深查；内部精核不扩成前台审计。用户明确审计/论文时按专项目的执行，真实数据、财务公式、实际执行权限及UNKNOWN保护不变。23号指定报告为阅读参照，24号旧补报已被否定；实际落实与后续验收见同目录PLAN/ACCEPTANCE。

<!-- dashboard-refresh-current-20261025 -->
## 经营看板八主卡与刷新（2026-10-25）

用户已确认同范围旧值先展示、顶部提示刷新并替换；默认销售额、订单数、毛利、毛利率、新客人数、复购率、新客占比、客单价八卡，其他收起。来源、历史更正核验、当前积压与未支付来源缺口，见 `docs/planning/business-dashboard-refresh-20261025/CONTRACT.md`；活动源码与正式发布/验收见同目录SOURCE-MAP和ACCEPTANCE。不改变逐单毛利公式、权限、会话、调度、v15双红线与本轮V3定价合同；Git候选知识不冒充生产目录或真实模型应用。

<!-- dashboard-actual-profit-current-20261024 -->
## 经营看板利润主展示（2026-10-24）

用户已授权用逐单实际成本毛利、毛利率和覆盖情况替换发货利润卡与每日曲线。有效合同见`docs/planning/business-actual-profit-20261024/CONTRACT.md`；新活动源及上线状态见同目录SOURCE-MAP与ACCEPTANCE。Admin同批付款完成订单整单CNY收入减同网站同订单Order实际历史成本，覆盖单不外推全体；未完成、缺收入/成本和失败明确展示。每日按同批付款日期分组；发货统计主展示及自动读取退役，原Hermes按需查询保留。RS筛选保持，FC未核细分不显示整游戏利润。不改FC v15双红线与本轮V3定价合同、调度、权限与UNKNOWN。本段覆盖旧看板shipping主展示规则，旧证据保留。服务器业务基准仅追加本规则，并仅更新原wulv/FS/fs完整基准兼容SHA；不把Git候选目录声称为已发布知识目录或真实模型验收。

<!-- business-shipping-profit-current-20261024 -->
## 经营看板利润计算规则（2026-10-24）

全局/分游戏主利润与每日曲线按Order“统计管理→发货统计”同网站、游戏、原生类目、交易时间取人民币销售减采购；分游戏原生率、全局总利润÷总销售，不再用Admin付款USD乘参考率。零分母率不适用，未知不补零，负利润保留，非净利润；同订单Admin整单人民币收入减Order实际成本及覆盖证明独立展示。规则见[业务基准专项补充](docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md#看板发货利润2026-10-24用户确认并上线)及[计算合同](docs/planning/business-shipping-profit-20261024/CONTRACT.md)。PR435/436已上线，活动源见[交付与版本](docs/planning/business-shipping-profit-20261024/DELIVERY.md)。仅看板Shipping字段迁移；旧primary兼容、Hermes其他报告、定价v15、权限/会话/调度和原UNKNOWN保持。Git文档/候选知识与生产装入、模型实际使用分别验收。

<!-- fc27-report-method-current-20261024 -->
## FC27经营报告字段与呈现

FC27经营报告先按[字段使用与呈现规则](docs/planning/fc27-daily-teaching-20261024/REPORT-RULES.md)定位相关教材：逐字段核来源、范围、单位、分母、计算、允许结论及主动补查；日期和数字是历史实例，新任务重取证。可比数据优先图表，多维指标按需切换；Ads/流量提高分析权重并置于发货履约之前，本次日报默认04获客、05利润目标、06履约。详细界面设计仍由Hermes自主，不扩为FS全站UI要求，不改预算或业务执行权。Git追溯、项目入口、正式技能、任务实际加载和长期应用分别验收；只入Git不等于服务器自动生效。Admin优先/Order补缺、现行业务基准、v15及原调度/权限保持。

<!-- fc-v3-current-20261026 -->
## FC27 V3统一定价与长期影子

本轮用户授权P0–P4开发、PR/CI、受控发布、真实试验及旧机制退役。当前业务合同为docs/planning/fc-pricing-v3-20261026/HERMES-OPERATING-CONTRACT.md，活动源与真实上线状态须核同目录SOURCE-MAP和DELIVERY。五策略采用真实经营输入，Hermes负责候选选择和审核；v15双10%红线、Console共同基价/成本、PC独立、原操作ID/UNKNOWN与公开读回保持。沙特地区及三平台系数使用真实Admin规则，兼容英国0.9100。积压仅Admin11/21/31与Order1/2正常订单交集，暂停/问题单及其余状态排除。

旧加权、临时ItemD2R钉价、旧baseline/hold/parity、尾价回摆及被替代调度不得保留生产控制。PR425/426等旧证据移作历史和隔离只读回放，不用于恢复旧控制权。切换与退役只有实际回执才算完成，不由本条推定已部署。原共享服务、其他游戏和未替代采集能力保持。详细参数基数、真实预测与长期学习方法按V3合同，Git知识候选、生产实际加载和Hermes独立运用分别验证。

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



<!-- management-all-sites-current-20261025 -->
## 经营管理台全站范围（2026-10-25）

用户明确要求经营管理台所有项目按全部网站实际比较原目标，不限定MMOEXP主站。活动源为`management_rs_recovery_20261025/source/`清单内文件；Git、发布、真实入口及逐日完整性分别见`docs/planning/management-all-sites-20261025/{CONTRACT,SOURCE-MAP,ACCEPTANCE}`。Admin全站原生USD销售/订单及客户字段共用范围；管理台既有USD利润仍为全站销售额×Order同期间全站参考率，RS仅接受已核发货统计百分比，明确预估非实结。经营分析看板逐单实际成本毛利独立保持。保留原目标/负责人、两线程/日更/模型计划、权限会话及原回执；旧主站缓存隔离，同期间旧值有据保留，拒绝/未知不补零。自然日更和模型应用不据手动发布认定。
