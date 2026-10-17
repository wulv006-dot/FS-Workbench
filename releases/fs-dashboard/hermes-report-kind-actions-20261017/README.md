# 报告类型与行动区隔离修复候选

状态：本地候选，未发布。活动三源于2026-10-17只读核对，精确source→runtime及before/after SHA见SOURCE-MAP.json；旧e947源码和历史报告不改。

- report_tracks：周/月词不再绕过日期约束。自然周仍须周一至周日；明确月报意图仅月初至同月合法窗口适用，保留既有月中月报。
- boss_projection：冻结类型与日期冲突时，仅阅读投影降为investigation；状态和缺口明确历史分类不一致，原result、证据、metadata及HTML保持原字节。周报完整周renderer校验不变。
- brain.js：行动读取异常在行动区提示并提供只读重试，不冒泡为主连接故障；主接口失败、无发起权限、UNKNOWN和提交中限制保持。

验证入口：

```text
python -B -X utf8 -m unittest discover -s releases/fs-dashboard/hermes-report-kind-actions-20261017/tests -p test_*.py -v
node releases/fs-dashboard/hermes-report-kind-actions-20261017/tests/check_actions.cjs
```

Python3项覆盖单日问题提周报、合法周报/月报/月中、跨月调查、历史冲突不改输入、原renderer完整周拒绝；JS实际refresh/actionRecords覆盖局部503、健康提交、无权限、UNKNOWN、提交中、切换竞态及主接口失败。

私有本地真实原74bb纯函数投影/渲染也通过，原四文件hash不变；验证结果只在任务私有目录，不包含进Git的真实业务数字。该结果不代表生产页面修复或真实新日报/周报通过，后续与continuation/学习方法/模板统一受控发布和验收。
