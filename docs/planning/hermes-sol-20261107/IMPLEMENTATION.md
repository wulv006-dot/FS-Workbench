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

生产 Sol 切换、管理台新结果及 FC 实际复盘消费尚待发布验收。周报自然周期为北京时间周一 02:40，下一次 2026-11-09，不用通用探针代替自然运行验收。
