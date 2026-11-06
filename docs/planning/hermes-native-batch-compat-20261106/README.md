# Hermes 原生批量取数兼容修复

2026-11-06。目标是让 FS 日报沿官方 Hermes 自主取数、计算和表达；不以固定调用顺序或停用批处理解决接入故障。

## 原因与处理

官方 Hermes 71d34bad 的 `agent/tool_call_batches.py::expand_local_tool_batches` 会把本地 `tool_call` 批次展开为单项调用，然后持久化和执行。模型回执中的 2 个调用，在原失败任务中展开为 4 个；用线上官方原函数复算，ID、名称、JSON 参数全部相同。FS 原来的回放检查只接受未展开的列表，在下一次模型请求时报 `provider_tool_history_changed`。

本次仅使 native 回放接受**可从原付费回执确定性还原**的展开列表。连接器专属批次不展开；仍核对完整对话前缀、工具 ID、名称、参数、顺序与 index。原付费回执不重写，调用预留和用量记账不变；执行仍走原身份、工具权限和业务 writer。

活动源：`releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py`。回归：`releases/fs-dashboard/hermes-v2-core-20261020/test_native_chat.py`。未来升级 SDK 时应核官方展开函数及直接消费者，不按过时的逐条线性假设限制 Agent，也不接受任意新增调用。

## 已完成的验证与发布

- 原代码隔离复现失败；补丁后 74 项 native chat / transport 检查通过，含篡改参数、ID、顺序、多余和缺失调用拒绝。
- 补丁纯函数对原失败输入的结果，与现役官方 SDK 完全一致。验证过程未导出私人正文。
- [PR #867](https://github.com/wulv006-dot/FS-Workbench/pull/867)；[正式 CI](https://github.com/wulv006-dot/FS-Workbench/actions/runs/42188240423) 通过；合并 `c8a50c08bb27c04102b368d01130927260199c58`。
- 沿原软件发布器发布 `nav-20261106T083430Z`，只替换 `/opt/fs-hermes-fc/proxy_gateway.py`。48 项保护文件完整元数据不变，worker、Desktop、Nginx 未重启，业务排程不变。
- 实际源 SHA256：`26f0b4ea186f633bc2d8c267face01414f5e5b4ccd913d564d0a60fc1312f26e`。
- Manifest：`45b08fd107fa2aa0dcc45d232565368baea2d9492742b9b3bc449df49b25a8d3`。
- 原备份：`/var/backups/fs-navigation-20261006/nav-20261106T083430Z`。恢复沿原发布器及 journal 对账，不覆盖任务、账本或历史报告。

## 真实入口验收

正常 FS 报告页面提交的 2026-11-05 只读日报已成稿，报告 ID `21ab2b349f64ea689efae3bf586e4cfd`。页面显示 27 份证据、44 次模型调用；已从「打开汇报」进入独立阅读页并核实正文可见。旧失败任务未重放。

这证明取数、计算、成稿及实际阅读链路已完成一次真实验收，不代表报告所有经营结论均已独立核定。正文仍有 FC27 专属流量、广告归属等缺口；「让利增加但单量下降」不足以单独证明降价无效，客单价也不能代替同套餐实付价。

连续追问已操作一次，但页面未出现新版本或明确回执；保留未确认状态，不重复提交。下一自然日报尚未发生。两项均不计为通过。截图与业务正文仅留私有运行目录，不进 Git。

原施工目录中的三份未提交文档草稿保持原样；本修复没有代替或覆盖其他线程的收尾。

## 七天最小迭代接续 · 2026-11-06 20:47（UTC+8）

继续使用原施工目录、同一检出及本交付记录。当前候选 PR 为 [#881](https://github.com/wulv006-dot/FS-Workbench/pull/881)，分支 `codex/hermes-knowledge-scope-20261106`。已合入当前 main `8a5fda56`；方案中的旧 commit/PR 仅作定位，没有回退或重复安装。

- #867 批量展开保护兼容已生效，线上 proxy 与 main 的 Git 字节一致；native_chat、native_reports、conversation_knowledge 也已逐一核对。后续 #873–#876、#879 的定价复查与知识修复已有记录，直接复用，不重复施工。
- 现役 native_reports 已传入来源、统计区间、币种、覆盖、缺日、过期与错误信息，沿用原实现。冻结证据追问不等于刷新数据；需要新证据时走现有新调查入口。
- 真实新日报复现：知识索引顶层只允许 FS/FC27，技能条目另有 FS/FC/RPG 适用标签；模型把后者作为工具 modules，连续三次被真实范围检查拒绝。候选仅澄清宿主 overlay、worker helper 的工具说明及固定知识提示，保留原范围拒绝，不做别名映射或扩大权限。
- 直接回归 15 项在 183 的 Python 3.9.18 隔离容器通过；网络关闭、1 CPU、512 MiB、无端口。独立代码复核无阻断项。知识收尾检查 104 项中 97 通过、7 项原条件跳过，无受影响业务知识 ID。Windows 的既有路径兼容失败另存原日志，不作为 Linux 通过或放宽断言。

### 真实任务与阶段结论

本次手动从正常 FS 入口提交一次日报，未人工提示工具参数，未重发旧请求。报告 `4440c1c80ea6284f96179a4533b96c18`，task `67fc843cb176d9ce52317f2e5f759fab`，run `run_8c6c6db8d9b04b368a88ae0f1d994f28` 已完成，31 份证据，独立阅读页可见。

独立复核判定本次**内容质量失败**：无券均折扣增幅计算错误；第一页已有更多自动价格事件且 has_more=true，却称全天仅 8 次；把并行变化写成确定因果。保留原报告和全部失败轨迹，不以人工修订替代本次成绩。目前完成 1/12 次，0 次质量通过，其余 11 次未执行；两个保留题由独立复核者持有，不参与调优。

本次模型配置 deepseek-flash，41 次调用、92 次工具调用，SDK 累计输入 5,433,058 / 输出 32,992 tokens（输入包含重复上下文）；实际美元费用未回传，不能写零。原生成与诊断耗时以私有原任务时间戳为准。

| 阶段 | 目前证据 |
|---|---|
| 代码完成 | 两个运行文件的说明修复与直接回归完成；PR #881 正式 CI 以关联最新 head 为准 |
| 部署生效 | 本轮候选尚未发布；需要本次两文件发布及原发布器必要重载授权 |
| 真实模型通过 | 旧现役链路本次能自主成稿；新候选真实模型未验 |
| 自然周期通过 | 0/2；11/6 night_daily 原任务失败，后续自然周期尚未发生；定价复盘不冒充经营日报 |
| 内容质量通过 | 本次 0/1；上述错误使日报不能直接验收 |

20:47 只读核对：FC API/worker 原 PID 与启动时间未变，最近 18:35、19:38 原操作 COMPLETED，20:42 原操作 NO_CHANGE，回执保留。没有由本轮触发改价、改策略或重启 FC 核心服务；这是发布前基线，不替代候选上线后的无退化验收。共享 range 服务已由其他现役变更于 20:41 重载，发布前必须再次核基线与空闲状态。

候选沿原 runtime_prepare.pack_software / runtime_release，仅目标 conversation_knowledge.py 与 fs_native_knowledge.py；原发布器将等待空闲并重载原 Hermes worker 和 range，保留 admission fence 与 readiness。回退沿本次 release ID 的原 journal/备份，仅恢复这两个文件并按同一发布器重载；保留数据库、费用、UNKNOWN、业务回执及他人后续修改，不回退旧整包。

私有证据均留原 `.agent_runtime/hermes-report-repair-20261106/`：`iteration-live-state.json`、`iteration-core-state.json`、`iteration-r1-daily.json`、`iteration-knowledge-index.json`、`iteration-knowledge-trace.json`、`iteration-linux-tests.txt`、`iteration-red-tests.txt`、`iteration-r1-ui.png`。下一步是候选正式 CI/发布授权与真实模型回归，再观察连续两个原定时日报；内容计算和证据覆盖仍待剩余任务验证，不能宣称七天目标已完成。

### 22:22 后接续：#881 已发布，忙碌错误单点修复

用户明确批准后，#881 合并为 `dffb33cf`（正式 CI `42220517615` success），沿原发布器完成 `nav-20261106T124849Z`。两文件哈希匹配，49 项保护文件完整元数据一致；worker PID 27726、range PID 27918，Desktop/Nginx 未重启，businessWorkerTimerActions=0。Manifest `3615374ed55aa80446895a912b01a1bc57b6c05513f0985ff31b02ec4ab6b00a`；备份 `/var/backups/fs-navigation-20261006/nav-20261106T124849Z`。此状态证明发布及服务重载，实际新模型使用与内容质量继续分别验收。

追问原日报的新任务 `bf7b0a121a29579863d2b002357d1306` 已自主成稿（31 次模型调用），保留原稿并更正部分错误，独立评分中。并行提交的第二次昨日复盘 task `e281d964a91c03ac74cb83845e2cd832` / run `run_17289534ded544caac46a4689e862b8e` 在零模型调用、零证据时失败：`HTTP 400: FC model request blocked: model_busy`。该次失败保留，不换请求编号重放；不能因零付费而删除失败成绩。

根因是共享 provider_slot 临时未取得，尚未进行费用预留或供应商请求，却被 transport 映射成参数错误400，原生SDK因此终止。用户进一步授权“最小修复”：仅模型路由确切 ValueError(model_busy) 返回503，复用原SDK的有限退避；没有放大并发锁、改预算或新建队列。原SDK实际纯函数证明503为overloaded/retryable且分类阶段不要求压缩、凭据轮换或fallback；持续忙碌仍可能耗尽原重试，不能承诺无限等待或必成。UNKNOWN及其他参数/权限拒绝保持原样。

直接回归在183/Python3.9.18隔离容器67项通过，另4项原发布器基线/CAS/回退范围检查通过；新测试在原代码400失败、补丁后503通过，验证忙碌零预留、释放后同一逻辑turn只付费一次、再次同请求复用回执。沿原发布器仅补登记 transport.py 的现役源码/目标对应，不新增发布机制。SDK纯函数与候选独立审查证据留 `iteration-busy-sdk-proof.json`，测试原日志留 `iteration-busy-red.txt`、`iteration-busy-linux.txt`、`iteration-busy-publisher-linux.txt`。

### 22:49 后接续：忙碌修复已生效，质量验收未达标

- [PR #882](https://github.com/wulv006-dot/FS-Workbench/pull/882) 最终 head `a7fd4ca5`，正式 CI `42235869300` success，合并 `1c9b1422`。首次 CI `42235327652` 失败被保留：历史发布测试读取了当前 transport 却断言旧哈希；已将同一历史提交 befa7cd8 的 transport Git blob 固定到既有夹具，原哈希/长度断言保留并增加 blob 校验，未放宽检查。
- 沿原发布器发布 `nav-20261106T143601Z`，仅 transport.py；载荷源 `2fedc691` 与最终 head 的运行文件逐字节相同（后续只修历史测试夹具）。实际 SHA `6ddf6de1abfdd323d46d3026bd8f8dd7b1bae61dd0d90341b2fa2f009e1d6fff`，48 项保护文件完整元数据一致。range 重载为 PID 9723，worker27726、Desktop1118、Nginx31780不变；businessWorkerTimerActions=0。
- 一次安装连接超时后，先核同 release ID：stage/backup/journal 均不存在、文件仍旧值、进程不变，证明未进入安装；沿同一ID接续成功，没有未知写入盲重放。manifest `d8406b2cb9e9d54b45945aa1128e9b6797b076424958e794dfe6d0508c64f6ad`；备份 `/var/backups/fs-navigation-20261006/nav-20261106T143601Z`。回退继续用本发布器、本ID和该manifest，仅恢复本次transport，保留#881两文件及全部业务状态。
- 上线后 FC 原自然周期：22:46:04到期、22:49:05完成；live_collector同轮来源覆盖ready，算价财务检查pass_all，原自动操作三步CONFIRMED、总状态COMPLETED，原执行编号读回verified。API/worker PID24218/24224与启动时间不变。详私有`iteration-core-postrelease.json`；只证明一轮FC核心链路，不计经营日报自然周期。

截至前5次终态，完整质量验收0通过/5失败：昨日复盘1计算/归因错误，昨日复盘2model_busy零调用失败，追问1误将原已注明“折扣额/净销售”改称分母错误；保留题1混淆Coins子集与全类目数据、错误解释为数据修订；保留题2报价范围和群体筛选链错误，并把指定套餐双20扩用于整日毛利。有效分析与缺口说明仍保留，未因单个工具错误直接否定整题；没有以修订稿或重跑替换成绩。两个保留题完整原请求、终态及独立评分保存在iteration-holdout-1/2-{receipt,final,grade}.json。

PR881新工具说明已由两道真实保留题的tool_describe确认到达模型；模型仍选错技能modules，未发现合法参数被误拒绝的代码证据。知识自主调用能力尚未恢复可靠，不能因部署成功声称修好。第6次异常调查已在#882上线后正常FS入口提交，原任务运行中；余下任务按原批次顺序验证。一次并行提交被自动审批以共享模型通道争用风险拒绝，已改为等待原任务完成后顺序提交，不绕拒绝。当前批次已无法达到10/12门槛，后续结果仍完整记录，不重新包装为达标批次。

阶段结论：代码与两次授权部署已完成；新说明已被真实模型读取，但内容质量未通过；经营日报连续自然周期仍0/2。未变更模型、并发锁、预算、业务权限、FC策略或调度。实际美元费用仍未回传，不能写零。停止扩项，不将上述技术修复表述为经营自主性成熟或收益已证实。

### 23:30 接续：先处理上下文，暂停剩余验收

用户要求先验证上下文处理，再推进原验收。原批次目前8次终态、0次质量通过：新增异常调查1（报告`3e78cb45`）、定价复核1（`a4884715`）、来源区分2（`a68d91ab`）分别存在无数量依据的成本归因/新报价建议、成本趋势及跨时点比较错误、FC名称筛选广告与全账户混用。所有原稿、请求、成功/失败轨迹和独立评分留存，详私有`iteration-open-case-1/2/3-{receipt,final,grade}.json`。剩余异常调查2、定价复核2、缺失数据2、追问2均未提交；不把后续对比覆盖到原成绩。

实际请求验证：现役配置上下文1,048,576 tokens；193份包含模型验证字段的回执确认向`deepseek-flash`转发thinking开启和high推理，供应商未回显effort，不能证明内部实际档位。最大单次输入188,245 tokens；现役原生自动压缩推算触发点327,680，所查样本没有压缩或截断记录。最长样本工具正文434,604字节，其中知识137,441字节（31.6%），完全重复工具正文约1.86%。以上不能证明长度是质量错误的根因。

本次候选只改两个现役运行文件：`conversation_knowledge.py`区分索引与原文工具说明，说明显式`entry_ids`按需读取和同固定版本复用，保留全模块读取能力；`fs_native_readonly.py`及知识handler仅去除JSON格式空格，解析后结果与原回执等同。现有`compact-v1`证据投影、计算JSON路径、工具关联、来源/时期/单位/缺失/null/0/分页及权限检查均保留；复用原生摘要与知识pin关联，不另造表格协议或调报告流水线，不改摘要阈值、1M窗口、模型和全局预算。

183/Python3.9.18无网络、1CPU/512MiB隔离回归48/48通过（含原生compaction fence）；独立审查无阻断问题。知识收尾104项中97通过、7项原条件跳过，无受影响业务知识ID；首次本机缺tzdata失败保留，补用原测试依赖后通过，未安装新依赖。冻结18篇知识原返回136,655字节；全部仅紧凑编码为135,301字节（约1%减少）。按条目主题前缀选择完整条目的离线比较：报告/数据7篇63,247字节、定价3篇31,685字节；每篇内容、hash和来源元数据等同。这是工具结果字节实验，不是token或模型质量提升，也不证明这些集合足以回答具体任务。证据`iteration-context-selection-proof.json`、`iteration-context-linux.txt`、`iteration-context-closeout-with-testdeps.txt`。

候选上线后只追加最多2次可比模型任务，独立记录上下文输入、知识读取范围、证据保真及质量；有明显改善再追加最多2次，否则停止付费试验并请用户确认方向。总追加上限4次，不无限重试、不刷题择优。原12次余项待上下文方向确认后接续。当前候选尚未发布、真实模型未验，不称问题已解决。

23:21只读核原定时：没有RUNNING/QUEUED请求；原日报仍enabled，下次自然时点11/07 01:40，来源未就绪沿原02:00 fallback及07:49截止；最近11/06原日报失败，候选上线后自然经营日报仍0/2。未触发补跑、不改排程。现阶段：两项先前修复代码/部署已完成；本次上下文候选仅代码与直接检查完成；真实模型、内容质量和自然周期均未通过。
