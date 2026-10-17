# Hermes 试点取消sk文本拦截

用户明确指令：“直接让他不要拦截sk”；同时要求尽快落实试点，真实卡点及时请求人工干预。此指令替代此前逐普通词豁免方案。先前候选/独立P1/P2/失败证据保留，未部署未修候选。

第八任务9fd91485a91fc7aa86f16748422fefed终态FAILED/context_rejected：10个模型调用全succeeded，422920 tokens，公开峰值估算1006598microCNY（非账单实扣），无新增unknown。最后60消息435570B在新预留前误拦task-scoped简写，非1M容量满；39保留证据包括pending/partial。旧8FAILED、模型费用和两个已批准unknown保留，不重放/不记零。

删除Hermes Agent文本里的sk规则及复杂普通词豁免：模型请求、最终报告、提交问题、已审背景、旧兼容报告、分组标签6处消费路径一致。提交问题使用Hermes独立验证，保留原长度、URL/邮箱/长数字与其他凭据检测；旧共享短顾问源码/合同保持原字节。Bearer/Cookie/password、报告中文密码/邮箱、字段工具白名单、角色同源保护、数字证据引用/schema、预算账本与unknown保护均保留；不新增密钥、角色、服务、网络或业务写。

原publisher新增专用6目标scope `hermes-fc-sk-text-guard-20261014`，proxy_gateway/report_validation/controller/background/pilot/research；历史5/8及其它scope映射保持。其余Hermes/现有Admin会话和Order接线、全部静态前端/其他模型在347现场清单保护，6目标341保护。既有锁、admission fence、模型账本锁、静止检查、CAS、备份/回滚沿用，只原FS重载，无Hermes/Admin重启。

验证：本机211项207pass/4POSIXskip；新直接110项106pass/4skip。官方high/max smoke加入完整公开说明、普通简写和引号包装。旧顾问不可替代Hermes真实提交测试。正式精确Linux CI待新head。部署后对原第七/第八失败dump作活动代码纯预检（不预留、不调模型），再wulv真实入口创建新完整周调查，数字/证据/行动/报告质量独立验收。不能凭CI/merge/部署/HTTP或模型往返宣布经营试点成功。

来源：SK-GUARD-LOCAL-FREEZE-20261014.json、SK-GUARD-WINDOWS-TESTS-20261014.txt、EIGHTH-REAL-TERMINAL-20261014.json、EIGHTH-FAILURE-PATTERN-SHAPE-20261014.json、PROSE-BOUNDARY-LIVE-BASELINE-20261014.json。当前base2971a9e867f4ced279b954ecb54e9801d8bd509c/tree4e8b1973937c51bc942df486fbe20f9a970aa80d，04:36UTC347/347匹配、active0。私有推理、raw订单、凭据均未归档或进入PR。
