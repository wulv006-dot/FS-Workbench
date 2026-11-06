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
