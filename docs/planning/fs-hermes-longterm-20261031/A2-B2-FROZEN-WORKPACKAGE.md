# A2/B2冻结调查与显式追踪工作包

沿唯一主方案阶段2，不新增路线。用户现阶段保留DeepSeek，候选模型仅验证；本包没有模型/业务API、生产认证或部署动作，也不宣称完整用户运营闭环已上线。

## 终点、基线与唯一维护者

一个host授权scope内，用原冻结群体摘要、候选分页与最小单客时间线，对两个事实版本和明确检查点给出可追溯付款观察、缺项与下一步，再交B1最小引用。没有新客户库、采集器、目标持久化或调度器，不恢复legacy due_reports。一个最终集成PR，包内修复留同PR，最新完整head由Business Sol High独立worktree审查、必要CI通过后按授权普通合并。

主控开工fetch/ff main=71cb788e8fdffab3068b278045911c910a12f093，干净；该基线PR709的reviewed head cbc2799b41d0f44b70d44dba415f3ca32897688e已独审通过，CI41214989116/41215336533成功，默认DeepSeek/候选验证包代码已合并、未运行时装配。随后正常merge A候选7ee41c0a506b75f04d933e8a4aa101c148a81a78，仅三文件，不读取A未提交目录。

| 路径（releases/fs-dashboard/下，除另标） | 本包唯一维护者 |
|---|---|
| user-analytics-20261022/source/a2_query_context.py、tests/test_a2_query_context.py、A2-QUERY-CONTEXT.md | Business A，固定候选7ee41c0a；B不并改 |
| hermes-v2-core-20261020/source/b2_frozen_investigation.py、新test_b2_frozen_investigation.py及test_core.py加载 | Personal B |
| tools/pr_fast.py | Personal唯一维护：仅原user-analytics units列表追加test_a2_query_context，A已明确不并改 |
| 本工作包、唯一主文件 | Personal主控 |

controller、公共schema、迁移、插件、IAM、原查询/DB、采集/调度、原DeepSeek和发布清单保持各自原归属，本包未修改。

## A接口与真实边界

完整合同沿A2-QUERY-CONTEXT.md及固定源。context_factory(service,identity,allowed_scope,validate,observation)创建同Store/clock的Service受控实例，authorizer为原授权与host当前scope严格True交集，不能从页面/admin宽授权继承global；每次源查询仍经原permit。无有效scope返回unavailable且不读源，撤权及旧global-dependent快照拒绝。身份/scope/观察计划由host注入，不是模型参数。

catalog/aggregate/candidates/timeline/changes_due复用原us_/ua_、事实版本、覆盖及周截止。候选按opaque ID稳定排序，不是净价值排名；时间线仅投影必要字段。first_paid只在源证明可信历史Day0时verified；期间首笔/观察首见不冒充历史首购。候选与时间线complete只表示单次请求从头覆盖，末页next_cursor=null本身不是全量证据。

changes_due只读两个冻结版本，检查显式host时点，不注册追踪或自动回源。scope/identity/实际lifecycle policy等不兼容返回incomparable；cutoff不足、partial或退款更正不补0。具体源码可复用不代表真实生产scope、更新游标或活动装配已验。

## B实际消费者

- page_chain消费实际A分页回执，绑定scope/snapshot/版本/查询与cursor，检查总量、返回数、稳定候选顺序、重复/缺页和时间线offset；只有从头沿完整链读到total才声明enumeration_complete。host给每条链page_budget，预算结束返回partial及next_cursor，不丢弃已核局部观察；从末尾单独重放永不称全集。
- investigate重放两个明确冻结snapshot，读取host显式选择的必要客户（最多200，与A观察计划一致），消费changes_due并调用原b2_customer_followup.assess。不把原聚合、授权、分页源或生命周期算法另实现一套。
- source_as_of取query.as_of/state_data_through/weekly_cutoff最小，observation_at为host检查点，now为host当前评估时点，三者分开；来源不能来自未来，capture时间不能推进业务截止。两snapshot原引用和版本均保留。
- 结果保留source付款观察（未到期/需刷新/有新付款/到期未见新付款/需更正复核），同时保留B2因退款/身份/历史缺口的needs_evidence。已有局部事实可指导下一步调查，不因此称流失概率、净贡献或干预收益。选项含no_intervention和只读investigate_evidence；没有触达/发券/改价写入。
- 原request_id保留，unknown/pending/unavailable不自动重试或换快照；已读页最小引用保留。撤权抛PermissionError，不返回之前私有结果。停止目标在读catalog前返回。
- 最终结果不包含205名候选正文或时间线明细。B1 evidence使用原scope/us_/ua_/query/cursor和来源版本，首末页引用+页链摘要及明确覆盖/缺项；不建第二套证据账本，引用仍须A鉴权，源保留不足不靠hash冒充可回源。
- load记录实际context方法调用次数和本地JSON响应字节，source_rows_scanned仍unknown；不把小返回体等同后台少扫描、网络账单或模型费用。

## 本地验证与未验项

Personal已独立运行A2 18项合成测试，以及B2组合16项；原pr_fast.units Core入口124项通过、0失败/0skip，包含B1/DeepSeek、B2、材料与HTTP回归。组合使用真实合成SQLite Store/Service/A2上下文、B消费者和原B1 handoff，无真实模型/业务API。覆盖205候选、完整/中断/重复/末页链、来源版本变更、scope错配、必要时间线、旧截止、迟到退款/末购回退、不可比快照、撤权、unknown原ID与已读引用、停止零读取；也验证partial历史中晚于保守截止的付款降级缺项，不作为未来事实或让整个调查崩溃。handoff不含邮箱/订单/整客正文。pr-fast --selfcheck及diff check通过，A三文件与固定候选无差异。

Windows本地缺tzdata和POSIX mode支持：复用A测试对2026固定UTC+08导入及仅私有temp根mode位夹具，SQL/Service授权/覆盖/投影真实运行；不安装依赖、不改生产时区或权限。Linux实际时区/FS权限、原user-analytics旧套件及新CI接线效果仍待最终PR CI，不能据本地逻辑通过称Linux或生产验收。

未完成：模型工具schemas/真实worker/会话接线、真实数据与细粒度生产授权、目标持久化/真正变化或到期调度、价值/风险方法与干预比较、真实模型选择/费用负载、部署及阶段2整体验收。本包再次运行knowledge_closeout.py plan（base71cb788e），仍原91项中30项native_plugin_exact_registration_delta_required字节错误，未通过收尾；不改无关publisher、不放宽校验，不声称知识或Notion发布完成。

## PR711独审与project-only修复

Business Sol High独立worktree核阅12acaea91245e0620621b6edfb954ea89ab8a9d4/base71cb788e，实际9路径，发现1项P2：合法原project:1327单独授权可以aggregate/candidates，却因原Service.catalog要求至少site权限而拒绝目录，整条B调查失败。其余限定核心范围无可复现越权/UNKNOWN重放；Linux CI41218728471的Ubuntu22.04/Python3.9.18已实际Core124及user-analytics253通过、0skip，不再把该固定head标Linux待验。

A原施工聊天已确认，仅本次catalog小修临时将a2_query_context.py交Personal唯一修改、A不并改，长期归属不变。B先补project-only整条调查回归并复现user_scope_denied，再沿已核当前scope构造原静态目录字段投影，保留definitions/policies/weekly状态，不修改原Service/IAM、不增加site/global授权。项目目录sites为空、仅当前project；can_read_private仍为当前scope的原授权与host校验交集，返回字段深拷贝不修改原配置。修复继续原PR711，新完整head待重新独审及必要CI，不继承旧结论。

修复后本地原Core125项（组合17）及A2原18项通过、0skip。新增组合回归以严格project-only原authorizer跑目录→完整B调查，断言没有site/global授予、原对象/配置不变、撤权仍拒绝；原weekly publication缺失及scope交集用例继续通过。新head的Linux全组CI及独立复查仍待完成，旧head Linux253通过不直接覆盖此次目录修复。
