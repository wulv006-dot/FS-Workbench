# Hermes Sol 与管理台分析恢复

负责人：本任务统一修改和发布共享模型通道；FC 双向试价任务仅负责 pricing_review_v3 消费验收，不覆盖共享文件。

授权：2026-11-07 吴律要求暂停其他汇报、保留 FC 周报，并补充恢复经营管理台日更分析；使用既有 OpenAI API 余额。双方协调后加入 FC 定价复盘。小时算价、writer、采集及普通聊天不随此切换。

## 事实与范围

- PR900 已发布汇报筛选：weekly；记忆审阅日报已通过原 cron 接口暂停，其他业务巡检保持。
- 本次配置保留 weekly、management，daily、monthly、management_weekly 继续暂停。
- 管理台 11 月 7 日原任务 `night_management_20261107` 已 FAILED；模型账本原因为 `tool_arguments_json_invalid`，模型 deepseek-flash。保留原任务和付费用量，不重发原 ID。
- 现有 OpenAI 凭据 /models 返回 gpt-6.1-sol。真实 Responses 工具调用和回传两轮成功，共 156 tokens；仅证明通道，不等于业务报告验收。
- 官方模型说明：Responses 工具调用，最大输出 128000 tokens；保留 high/max 推理。https://developers.openai.com/api/docs/models/gpt-6.1-sol

## 活动源码与调用链

| 源码 | 部署目标 | 影响 |
|---|---|---|
| releases/fs-dashboard/hermes-v2-core-20261020/source/openai_provider.py | /opt/fs-hermes-fc/openai_provider.py | Responses 转换，原工具白名单，TLS，原用量格式；无重试/自动模型回退 |
| releases/fc-coins/fc-review-channel-20261026/source/fs_inprocess.py | /opt/fs-hermes-fc/fs_inprocess.py | 可信 native report/pricing 选择 Sol，原共享锁和账本 |
| releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py | /opt/fs-hermes-fc/proxy_gateway.py | 接受明确 Sol 用量策略；不虚构人民币费用 |
| releases/fc-coins/fc-review-channel-20261026/source/hermes_worker.py | /opt/fs-hermes-fc/hermes_worker.py | 受控任务模型及输出上限，普通聊天不变 |
| releases/fs-dashboard/hermes-conversation-20261018/source/conversation_native.py | /opt/fs-hermes-fc/conversation_native.py | 原报告/定价上下文选模，保持身份与工具权限 |
| releases/fs-dashboard/knowledge-layering-20261023/source/native_reports.py | /opt/fs-hermes-fc/native_reports.py | 新报告任务预算策略标识 |

Worker 通过原 /opt/pilot 挂载读取同一源码；发布后须核当前任务为空再重启原 Hermes worker，不能覆盖其他任务的 FC 发布。

## 验收记录

本地报告 32 项、native gateway 58 项通过。183 隔离目录 Sol 4 项、报告 32 项、worker 2 项、native gateway 58 项通过。初次 Linux 测试缺 RS 夹具，补齐后通过；组合进程测试夹具互相污染，按原测试独立进程执行，不放宽断言。

PR901 已合并（c5f896f99c8219a917f192de5e75858b0b531322），正式 CI 42385488401 成功。生产发布 nav-20261107T151800Z，7 个目标逐项哈希一致；备份 /var/backups/fs-navigation-20261006/nav-20261107T151800Z。原 worker 在确认没有活动任务后重启，真实报告调用通过。

管理台真实入口新请求 web_3fe7342a159d44b398294932ac0c78a9，报告 68467a43a0f799764df8aaa33e64e212，任务 63c6dd65852113ba3a285f53f11556a3：报告 COMPLETED，无错误；底层 TaskStore 保留 PARTIAL 原状态，不能用它宣称所有证据无缺口。12 次模型调用全部 succeeded，实际 response_model=gpt-6.1-sol，Responses/high，共 839341 tokens，未核供应商实际费用。页面显示事实截至 2026-11-06、生成 2026-11-07 23:20:55、当日有效，已读取实际三段经营分析；截图 .qa/hermes-sol/management-live.jpg。

日程配置读回仅 weekly、management；管理台每日 02:10，周报周一 02:40（北京时间）。下一周报 2026-11-09，管理台下一自然运行 2026-11-08，尚未到期，不以手动入口验收冒充自然周期。FC pricing_review_v3 真实业务消费由对应 FC 任务独立验收。

报告中心和调查入口的日程展示改为读取 report_kinds/starts，明确已暂停报告，既有结果标为历史记录；不删除报告与账本。活动目标：hermes-report-repair-20261019/source/brain.js → /var/www/dashboard/fs-home/brain/brain.js；hermes-data-workspace-20261018/source/hermes-index.html → /var/www/dashboard/fs-home/hermes/index.html。
