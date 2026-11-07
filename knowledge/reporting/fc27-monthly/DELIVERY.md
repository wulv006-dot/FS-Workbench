# FC知识库交付记录

2026-11-06定价效果数据与知识清理的最新状态见[统一交付](../../../docs/planning/pricing-review-recovery-20261106/README.md)。以下各次加载/发布按原时点保留，不代替最新验收。

## 2026-11-05：新版方法与取数知识已同步

本轮来源为[PR836](https://github.com/wulv006-dot/FS-Workbench/pull/836)合并`b55864d9ed9d69b4dbf118befd49cb92e9f8ae43`，methods为revision `20261105-2`、data为`20261105-3`。新增buyer身份字段不等于筛选生效、全年价值未重算边界，以及每日补新、周一当月与前两月复核、跨日截止和成功承接后的冗余清理。其余28条知识、原明确历史事实和其它用户路由保持。

| 层次 | 本版结果 |
|---|---|
| 共享Hermes审核应用 | 原review_queue完成candidate `skill:c2a74616`、request `dfb5b66bb07d92b06c8ffee7c7100c9906664b3190e836dbb5375f571e480ad0`；3项更新、12个其它文件保护读回通过 |
| 共享新会话实际学习 | `20261105_115204_46047f`只提交一次题；3次真实skill_view读取入口/index/data，回包SHA匹配；未输入教师答案 |
| 共享未见迁移题 | 11月三自然月与跨日处理、成功承接才清理、Store历史保留、buyer筛选缺口及全年未重算、GA4事件与收入未知和Admin/Order来源均通过 |
| FS新版发布 | 原ID `nav-20261105T114622Z`完成；21目标、72保护对象及owner/mode读回，methods2/data3与旧版loader可读；原成本PID14757仍持admission READ，0服务动作 |
| 真实FS模型应用 | 同一真实Chrome会话的纠错新turn completed；明确正确工具协议提示后，实际索引及两份正文读取、版本/SHA与三题回答通过；首轮DeepSeek无提示工具使用失败保留，不称全自主通过 |
| 未验边界 | native正式技能安装未做；日更/周复核自然窗口、自然报告与长期经营效果未验 |

共享参考index SHA `e62ea6ed9bfa408326867f0aa9d6d454ffd9a1d53171beb78de2c0d9de6ca353`、data SHA `5c63bef176c81b37c3c13c0eab9d5e8f73d014e0bf1924625582791d7d086d3a`。共享沿既有OpenAI gpt-6.1-sol medium配置，3次模型调用、76,323总token、60%缓存命中；实际美元费用未返回，记unknown。未修改默认模型、权限或业务数据。

### 本版发布与保护

知识发布原先被28日渠道成本读取的admission READ阻断。必要修复[PR850](https://github.com/wulv006-dot/FS-Workbench/pull/850)已合并为`e587dc123c7de65f2c4e0131177714cbeb4ea826`：仅knowledgeOnly复用现役reader-entry准入，保留原任务事务及完整quiescent检查，原apply/CAS/备份/自动rollback仍全程受控；代码/运行时分支与人工rollback合同未扩改。183真实原apply/rollback红→绿7/7；[正式Python3.9.18 PR fast](https://github.com/wulv006-dot/FS-Workbench/actions/runs/42027112705)的knowledge组104/104，0失败、0错误、0 skip。

沿原发布ID续发，manifest与正文载荷不变，只将stage adapter换为该合并实现；原失败回执及旧adapter保留。21目标为20个全新不可变文件和原policy一次CAS，全部正文落盘后原子切换policy。30条目录仅methods/data变更，原FS18个ID、其它路由及baseline保持；72保护对象含首版不可变目录，旧pin仍可读。没有停止成本任务、改服务/权限或新建发布器。

| 固定对象 | 值 |
|---|---|
| stage | `/opt/fs-release-stage/fc-reporting-knowledge-20261105-b55864d9` |
| manifest SHA256 | `b38db8bd994aa19aed249ff74e8813dd3b26cd9b9603daccdedeeb4d12db111e` |
| catalog SHA256 | `d1b767485b1c2cdaa75d272759184ae872d31c8c96050ea01629ee90a6e8d9b3` |
| 发布前policy SHA256 | `46fd5d8e172a77d985524b0fb71592b36b973862960872f71122764bdf768392` |
| 发布后policy SHA256 | `13cbc03d490ba752f0e3af14d7d914407ada2d844b90b3ad4cb413da40db13fe` |
| 原publisher备份/journal | `/var/backups/fs-navigation-20261006/nav-20261105T114622Z` |

回退沿原publisher及该原ID备份，先核原journal、现值与已完成pin的原合同，不换ID或用旧整包覆盖。文档收尾不再次发布教材，也不更改五主题正文SHA。

### 真实FS验收及首次失败边界

真实Chrome会话`902fae2bb7394e97849fe5f4bd03bd27`首轮turn `f6f0e5d2fa1c405eb1d507a33b4d81a6`为failed。新版pin正确，但DeepSeek使用错误参数（index传modules、read传id），3次工具HTTP400；原SDK又将一个批量tool_call归一化为三项，下一模型请求触发`provider_tool_history_changed`。该轮不是成功读取，completed工具事件不代表正文可用；原错误和ID保留，没有重放failed turn或放宽guard。

主控仅在同一会话发送一次新的协议纠错题：索引参数为`{}`，正文以`entry_ids`数组同时读methods/data，未给经营答案。新turn `d3191adb0218489cac9eb9abbf97fe86`、原run `run_181f04bb3be24bc9b7d4e815e4626223` completed；真实host pin冻结本版source/catalog，索引为index_only、两正文为available，内容SHA分别为methods `6e06c0fc201ea06a69ca2aacddc1658b3f038186dd0d5a4d016edc304d350fe8`、data `a9d24c2b66bceecb8f709ec10d3d9e0a453a9db83268ad9f3bdc7caead6a1741`。原SDK与UI均确认buyer筛选/未重算、跨日复核/成功清理、购买信号与收入未知三题正确。

纠错run实际为既有deepseek-flash/custom，118,517输入token、5,147输出token，共123,664；实际美元费用unknown。现役真实FS入口未提供单会话/单turn模型参数，本次没有切换默认模型。

证据保留私有`.agent_runtime/fc27-knowledge-refresh-20261105/`：`knowledge-refresh-readback.json`、`fs-native-acceptance-corrected.json`、`fs-protocol-corrected-sdk.json`、`fs-failed-sdk-summary.json`、`fs-failed-paid-receipt.json`、`fs-v3-acceptance.jpg`及共享`acceptance.json`/`HOLDOUT-RESULT.md`。教师标准、完整原消息、业务成品和生产回执不入Git。以下首版46034b08记录仅证明当时固定版本。

## 2026-11-05：统一入口与方法沉淀

- 新增中文入口 `FC知识库/README.md`，业务知识、取数计算、报告方法、定价策略、更新记录可直接查找；详细内容统一位于本目录，后续持续维护同一主题，不按月复制。
- 复用2026-11-02／03的六份取数/教学教材、报告审核核心及2026年10月优秀复盘的最终方法；私密HTML、业务明细和教师答案不入Git。53／42／46明确保留历史与估计身份，首单比例折算不用于行动。
- Codex项目技能 `fc27-monthly-report`提供短入口。现有知识索引登记方法、取数、报告、业务和维护五个稳定ID，以各文件内容SHA识别后续影响；服务器知识路由已按下述固定版本发布。
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
| FS知识发布与loader | 原publisher单次发布完成，21目标SHA及52保护对象通过；真实路由选择与五主题正文读取通过 |
| 正式FS新会话 | 实际Chrome UI新建并仅发送一次虚构短题；原turn completed，真实索引/单份正文工具回执与版本通过，回答广告CAC $40正确 |
| native正式技能、自然报告与长期效果 | native正式技能安装未做；自然报告与长期效果未验，不能从本题通过推定 |

初次裸桌面会话调用`fs_get_knowledge_index`返回缺会话冻结文件；原错误和停止回答保留。随后沿同一会话用现有`skill_view`成功读取并应用，未创建绑定文件或改权限。只读复核确认真实FS入口已有独立冻结链，裸桌面错误不证明真实FS故障。

共享教学验收模型为已有配置的OpenAI `gpt-6.1-sol`，共7次模型调用、178,484个总token（含缓存；续问回包显示94%缓存命中）。接口未返回实际美元费用，记unknown，不按token猜实付。共享验收未修改默认模型/API；正式FS短题验收单独记录，不把本段旧调用数当新增会话费用。标准技能校验脚本因已装环境缺PyYAML未运行完成；手工frontmatter检查与正式项目CI已通过，未为校验新增依赖。Windows原知识套件缺tzdata，正式Linux结果单列，不冒称Windows全过。

### FS知识接入已发布

真实FS新turn在POST前经`conversation_native`→`conversation_knowledge.lock_knowledge`→原`pin_fs_task`冻结授权知识，经host只读`fs_get_knowledge_index`／`fs_read_knowledge`读取。该helper复用共享方法源与已审核技能目录，读取KB不要求把技能另装到native profile。native正式技能安装未执行，不冒称安装完成。

[PR813](https://github.com/wulv006-dot/FS-Workbench/pull/813)的`knowledgeOnly`分支已合并（`473288861e16c59532d8717b25eb108d82c31768`），[正式Linux PR fast](https://github.com/wulv006-dot/FS-Workbench/actions/runs/41888012949)通过。沿原publisher保留锁、CAS、备份、journal及rollback，知识模式无代码/服务目标。范围检查本地4/4，旧分支不变。

2026-11-05 00:26:53 UTC（北京时间08:26:53）单次发布`nav-20261105T002653Z`，原始回执`applied-awaiting-actual-http-role-acceptance`；00:28:39 UTC完成精确读回。21目标为20个新不可变文件及原policy一次CAS；原25条知识、原13路由ID、其它用户路由与完整baseline保持，本route现18项。52保护对象SHA、21目标SHA及owner/mode均通过，四服务active/PID前后相同，0服务动作；真实已发布`task_selection`及五主题loader读取均为available。

| 对象 | 固定值 |
|---|---|
| stage | `/opt/fs-release-stage/fc-reporting-knowledge-20261105-46034b08` |
| 本次manifest SHA256 | `fb979b890afefcc1a90c691bcbedacef415d4fc8b9ee578263d2bd834e4bcb0a` |
| 原批准清单，已保留 | `88a1c79281071ce211586e08134650dc4c8bcdc4a6ccdeb366432ed674aad8bc` |
| 发布后policy SHA256 | `46fd5d8e172a77d985524b0fb71592b36b973862960872f71122764bdf768392` |
| catalog SHA256 | `7a8811daad69774324e988258fea58db4f46f61bece2498007e110559d54fdd9` |
| 原publisher备份/journal | `/var/backups/fs-navigation-20261006/nav-20261105T002653Z` |

重检时仅首页保护SHA与原清单不同；原journal证明它来自另一项合法独立发布`nav-20261105T001310Z`。主控核准只更新此非目标保护前值，新清单其它21目标和51保护不变；本次没有写首页。需要回退时沿该原backup、manifest SHA及同publisher rollback，不用旧整包覆盖其它业务，结果未知先核原journal。

此前阻碍不是待关闭的真实业务：原2026-11-02对象是已归档合成CSV样本，outcome/cost仍unknown；旧publisher未识别该既存归档。用户本次明确要求彻底删除单对象后，主控按固定CID/turn/session、原5行SHA和5文件SHA的脚本单次清理，私有原始备份与审计保留，未取消或重放原执行。未实施archive-aware publisher修复、native兼容修复或其它批量清理。原503及原ID证据保留，不将旧SDK账本0行解释为未执行。

正式FS新会话已由主控从Chrome持续对话UI新建并只发送一次虚构练习，题目仅要求读取索引和fc.reporting.data，以12000美元广告费、300名广告归因新客核广告CAC；原回答$40，拒绝用全渠道1000新客作广告CAC分母，并标注revision 20261105-1。主控实际UI与只读原turn回答一致，未另发、重放或伪造binding。

原cid为`638c9bae8f2b4cd58d62a9f6e6072933`，turn为`cfaed713481543b48f9118181ffb02eb`，run为`run_e0115479f68d46abb1bf07cd758d835d`，状态completed；00:47:35 UTC抽验的真实pin SHA为`dc75c8dd2ea6122324bdff8b8ea5b5a5d0215871f40fa2649d5ff5b17a145286`，绑定来源46034b08及上述catalog。真实index receipt为`d3fa54874060e1c4d8f820ccedca230fea1d40e6f6475422c1bee868a128abb1`；正文receipt为`5f4eb4190e2288163c902ebb1bb9a25508b23035d23edaacc5b6f1ef70ffd97f`，参数只有FC27模块和fc.reporting.data，正文SHA与Git原文一致。正式验收会话保留；新增会话实际美元费用未回报，保留unknown，不猜实付。native正式技能安装未做，自然周期和长期经营效果未验。受控证据目录`.agent_runtime/fc27-knowledge-20261105/`含`publisher-apply-result.json`、`knowledge-publish-readback.json`、`fs-formal-knowledge-acceptance.json`、`fs-formal-output.json`、私有UI截图、`synthetic-delete-apply-receipt.json`和`SYNTHETIC-DELETE-PLAN.md`；原始凭据与业务文件不入Git。计划见[发布计划](../../../docs/planning/fc27-knowledge-20261105/PUBLISH-PLAN.md)。


## 2026-11-07：每日定价复盘盈利摘要交接

修复原daily仅给覆盖说明、未给实际成本毛利的问题。新任务冻结实际盈利摘要，复盘日创建归属与当前计划累计分开，已核部分与未知金额并列；不重跑已完成旧日报。v3/data/maintenance采用`20261107-profit-summary`，约束条目的财务版本不变。代码和知识已沿原publisher读回，实际线上模块装配的模型payload确实含已核成本和毛利；下一自然日报及模型实际使用仍未验。完整源码、CI、发布、只读验收与边界见[项目交付记录](../../../docs/planning/pricing-review-recovery-20261106/README.md#2026-11-07每日实际成本与毛利漏交修复)。本次无新增付费模型、无改价或业务排程调整。


## 2026-11-07：同价续窗的计划与ABC归属

盈利摘要的分组改为按订单时点和相关资源，从已完成/NO_CHANGE操作及opened_at/continuations确认事件查对应计划与ABC，并核价格/规格一致，不把物理窗口ID当政策周期。实际账本的同价续窗已隔离复现并覆盖测试；当前冻结回放确认存在计划/ABC归属差异，但原始全体收入毛利不变；尚无自然日报使用该新摘要，不称已发生自然日报错报或经营损失。详[同价归属修复记录](../../../docs/planning/pricing-review-recovery-20261106/README.md#2026-11-07同价跨计划与abc归属修复)，部署与下一自然周期另按原回执核验。
