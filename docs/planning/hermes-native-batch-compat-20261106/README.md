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
