# FC知识库交付记录

## 2026-11-05：统一入口与方法沉淀

- 新增中文入口 `FC知识库/README.md`，业务知识、取数计算、报告方法、定价策略、更新记录可直接查找；详细内容统一位于本目录，后续持续维护同一主题，不按月复制。
- 复用2026-11-02／03的六份取数/教学教材、报告审核核心及2026年10月优秀复盘的最终方法；私密HTML、业务明细和教师答案不入Git。53／42／46明确保留历史与估计身份，首单比例折算不用于行动。
- Codex项目技能 `fc27-monthly-report`提供短入口。现有知识索引登记方法、取数、报告、业务和维护五个稳定ID，以各文件内容SHA识别后续影响；索引仍为候选发布输入，不宣称服务器已换版。
- 维护沿原 `knowledge_closeout.py`、原审核队列、原发布器及同change_id去重，未创建定时任务、修改价格/预算/排程或开放Hermes写权限。

本地与正式Git、共享Hermes审核应用、新会话读取与独立迁移结果分别补入本页。2026-11-05最初只读复验确认：共享 `data-storytelling`保留11月3日批准版；FS原生owner的独立profile仍无该技能，现有审核命令未提供管理员直导。共享应用不代表native生效；未绕过来源候选映射或直接写正式native技能。

代表性检索问题与学习标准见[维护协议](MAINTENANCE.md#验收问题与分层证据)。原回执、文件SHA、未见虚构题、教师答案及模型原输出保留项目受控 `.agent_runtime/fc27-knowledge-20261105/`，不随教材上传。

### 本轮实际结果

| 层次 | 结果 |
|---|---|
| 本地知识与Codex技能 | 相对链接、五个索引条目内容SHA/按范围选择、CAC/GA4与GSC/毛利来源三类检索通过；已安装项目短技能 |
| 正式Git | [PR812](https://github.com/wulv006-dot/FS-Workbench/pull/812)已合并，来源提交`46034b081c7a132f73fb684200859493dd6b6304`；[正式Linux PR fast](https://github.com/wulv006-dot/FS-Workbench/actions/runs/41884134080)通过 |
| 共享Hermes审核应用 | 原候选`skill:7b16b404`，原决策回执`de7e1fd9871c6bc86663fd04813e5878b91b950b689f23abca7a37280e16a086`为completed/success/applied；五份参考和短索引均SHA读回一致；未处理其他候选 |
| 共享新会话真实读取 | 新会话`20261104_181355_913db4`仅续问一次，实际3次`skill_view`读取入口、索引与取数分册，回包SHA逐字节匹配批准文件，来源固定上述Git提交 |
| 未见虚构题应用 | 本题通过：广告分母/重复与未知来源、GA4事件与付款/收入边界、不同游戏加权毛利、客户价值与回本期均正确；主判断和行动有主次。教师答案未输入模型，另由主控抽验 |
| 实际FS原生入口、自然报告与长期效果 | 未验；不以共享会话通过替代，不声称永久学会 |

初次裸桌面会话调用`fs_get_knowledge_index`返回缺会话冻结文件；原错误和停止回答保留。随后沿同一会话用现有`skill_view`成功读取并应用，未创建绑定文件或改权限。只读复核确认真实FS入口已有独立冻结链，裸桌面错误不证明真实FS故障。

本次模型为已有配置的OpenAI `gpt-6.1-sol`，共7次模型调用、178,484个总token（含缓存；续问回包显示94%缓存命中）。接口未返回实际美元费用，记unknown，不按token猜实付。没有追加付费测试或修改默认模型/API。标准技能校验脚本因已装环境缺PyYAML未运行完成；手工frontmatter检查与正式项目CI已通过，未为校验新增依赖。Windows原知识套件缺tzdata，正式Linux结果单列，不冒称Windows全过。

### 真实FS的KB接点与待发布范围

截至本次只读核查，真实FS原生新turn在POST前经`conversation_native`→`conversation_knowledge.lock_knowledge`→原`pin_fs_task`冻结授权知识，再经host只读`fs_get_knowledge_index`／`fs_read_knowledge`读取。该helper使用共享方法源与已审核技能目录，**通过KB读分册不要求把技能另装到native profile**。

现场FS路由仍固定10月30日的不可变知识catalog与原13个条目；本次五个`fc.reporting.*`条目尚未发布到该路由。若接续发布，复用原知识收尾与publisher，准确载荷为新不可变索引及其来源正文、原`wulv / FS / fs / conversation`路由的catalog指针和SHA，并追加本次五个稳定ID；保留原条目、基准兼容、`approved_current`及其他路由。仅该知识载荷不应改native代码、权限、定价、排程或重启业务，也不复用已冻结旧turn冒充新版本。

已审shared索引现含本次参考；native正式技能安装仍未执行，实际FS按KB读取与新turn独立应用仍待真实入口验收。本轮没有伪造冻结回执或把旧不可变发布ID直接覆盖为新版本。

### 仅知识发布候选已具备，现场保护阻断，未apply

[PR813](https://github.com/wulv006-dot/FS-Workbench/pull/813)已合并，提交`473288861e16c59532d8717b25eb108d82c31768`；[正式Linux PR fast](https://github.com/wulv006-dot/FS-Workbench/actions/runs/41888012949)通过。原知识适配器新增明确`knowledgeOnly`分支，保留原publisher的锁/CAS/备份/journal/rollback，旧分支不变；本模式仅知识载荷，无代码/服务目标，不进入代码恢复的服务动作。原2项及新增2项范围检查本地4/4。具体计划见[发布计划](../../../docs/planning/fc27-knowledge-20261105/PUBLISH-PLAN.md)。

最终候选为21目标（20个新不可变文件＋原policy一次CAS），保护52个原对象；当前已发布25条知识及原文保持，只追加五个FC主题，不迁移其它知识或用户路由。

| 对象 | 固定值 |
|---|---|
| 原服务器stage | `/opt/fs-release-stage/fc-reporting-knowledge-20261105-46034b08` |
| 批准manifest SHA256 | `88a1c79281071ce211586e08134650dc4c8bcdc4a6ccdeb366432ed674aad8bc` |
| 原policy SHA256 | `34bfb04dac8c76190d618372f170b94ba622db184656e45f416aca70976a67ab` |
| 候选policy SHA256 | `46fd5d8e172a77d985524b0fb71592b36b973862960872f71122764bdf768392` |
| 候选catalog SHA256 | `7a8811daad69774324e988258fea58db4f46f61bece2498007e110559d54fdd9` |

原publisher的`inspect`返回`active_conversation_or_tracking`，**未执行apply、未创建本次backup或发布journal、未切换FS路由**。只读查到唯一历史对象：turn `d2d00f2c13e749f186bf6e4303514a65`、request `web_c6a3cf2095854f898ed5b10c03b64a01`、conversation `1fbe5a2b7b0b4434af259bbde7c9293b`，FS状态`dispatch_unknown`，绑定`run_id=null`、`stopped=1`、无事件。原admission时间为2026-11-02 10:52:36 UTC（北京时间18:52:36）；11月5日本轮检查中，原native session的受支持GET对账返回HTTP503 `native_lookup_unavailable`。这些证据不能证明原执行不存在或已完成，不能清状态、重发POST或取消别的业务。

接续应先沿原`NativeConversation.reconcile_unknown`合同核原session；只有取得匹配run_id与真实终态，才使用其受支持reconcile接回原monitor。原session为`hc_f7dedcccea9b45a394c2f8f37f6f20dca043b58806d3474faa83a633a81453c8`。目前503不具备该条件。对账可用且原保护解除后，在同stage核manifest/原policy及保护SHA，重新只读inspect；若CAS无漂移，再依当前授权以唯一原发布操作调用同publisher apply、保存backup/journal并读回。任何原写入结果未知先查其原journal，不重放。

本轮不修复该历史未决业务、不重启Hermes、不改权限或弱化保护。FS本版KB发布、真实FS pin/host-call读取、FS模型运用及自然报告仍未验；本地/Git/shared成果保持可用。详细只读回执与恢复说明在受控证据目录的`publisher-final-plan.json`、`release-busy.jsonl`、`original-native-lookup.json`及`PUBLISH-HANDOFF.md`。
