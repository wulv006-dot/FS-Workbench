# 第八真实任务的普通词误拦修复

第八任务 `9fd91485a91fc7aa86f16748422fefed` 已终态 FAILED/context_rejected。10 个已记录模型调用均 succeeded；最终请求未进入新预留。39 份保留证据包括待取得时的 pending 记录，不等于39份完整可用数据。原失败、费用与证据保留，不重放。

现场请求 messages UTF-8 435570字节、60条消息，小于试点传输上限。安全诊断仅输出字段位置/长度/摘要：唯一原值误拦来自消息54的模型 reasoning_content 中完整普通词 task-scoped（官方运行dump同时保留相同reasoning字段）。私有推理没有进入归档或PR。真实工具的公开 HMAC 说明此前已通过，模型使用简写后旧豁免不足。

候选只在扫描副本豁免 Unicode 边界完整普通词 task-scoped；句尾点号允许，连接的字母、数字、下划线、连字符及点号凭据串继续拒绝。原值、模型思考和工具字节传输不改。最终报告校验复用同一扫描，另保留中文密码与邮箱检测，数字证据绑定、引用和schema规则不改。

既有publisher新增专用两目标 scope `hermes-fc-secret-prose-boundary-20261014`，仅 proxy_gateway.py/report_validation.py；旧5/8/历史发布scope不变。其余Hermes、Admin session/Order接线、模型和所有347文件基线保护；原发布锁、任务静止检查、模型锁、admission fence、CAS、备份及回滚保留。仅原FS进程重载；Hermes/Admin不重启。无新密钥、模型、身份、网络权限、业务写或调度改变。

本机207测试203pass/4POSIXskip，正式Linux CI和独立审查尚待；不把本机skip或合成结果当真实报告验收。正式通过后发布并在活动进程里对原失败dump作无预留/无模型纯预检，再从wulv真实入口创建新的调查。旧8个FAILED不更改，两个已批准unknown原记录保留，其他unknown/在途仍阻拦。

来源：EIGHTH-REAL-TERMINAL-20261014.json、EIGHTH-FAILURE-PATTERN-SHAPE-20261014.json、PROSE-BOUNDARY-LIVE-BASELINE-20261014.json、PROSE-BOUNDARY-LOCAL-FREEZE-20261014.json。当前基线 main2971a9e867f4ced279b954ecb54e9801d8bd509c/tree4e8b1973937c51bc942df486fbe20f9a970aa80d；04:36UTC独立347/347一致、active0、三服务active。
