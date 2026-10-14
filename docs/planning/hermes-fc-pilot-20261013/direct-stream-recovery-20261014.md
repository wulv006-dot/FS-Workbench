# 直连长响应断链修复

真实新调查982cef34eeb4a611db4feaf0bcfb1ddf在09:09 UTC前终态FAILED/provider_outcome_unknown。前15次官方deepseek-flash调用成功，2016423 tokens，99789 reasoning tokens已包含在completion中；第16次ConnectionResetError，61.409秒，配置超时1800秒，无HTTP状态或审核错误码。92条工具证据保留，没有最终报告。原记录不重放、不改成功或零费用。

DeepSeek官方当前文档确认：非流式等待可返回空行，流式返回SSE保活注释；stream响应以data:[DONE]结束，最后带finish_reason和整次usage。依据 https://api-docs.deepseek.com/quick_start/rate_limit/ 及 https://api-docs.deepseek.com/api/create-chat-completion/ 。无法仅凭ConnectionResetError归责供应商或网络路径；改用官方流式传输用于减少长响应等待中的断链风险，仍需真实验收。

隔离候选.agent_runtime/hermes-direct-stream-qa-20261014/；最小改动direct_provider按stream:true/include_usage读取SSE，跳过保活，完整合并reasoning/content、并行工具index/名称/参数。必须完整DONE/finish/usage，不把截断/aborted改stop，不自动retry。对外FS/Hermes协议仍完整JSON，无额外服务/网络域名/凭据或权限。

用户指定的模型deepseek-flash、high/max、1048576上下文/393216输出保持；10MB仍作用于原生请求/重建JSON而非累计SSE帧开销。新POLICY_ID含stream-v2，隔离旧nonstream-v1失败任务；用量未知在旧v1与新v2均不能显示为零费用。不添加累计费用或成本限额。

测试覆盖真实loopback HTTP保活、UTF8/high/max/aux、分片并行工具、两种usage终帧、缺DONE/usage/变ID、finish length/aborted、ConnectionResetError无retry、SSE帧累计大于wire但真实输出未超、重建超wire拒绝；相同输入旧非流式失败不别名。正式PR/CI/发布与下一新调查待完成。当前线上仍PR133/65761a，专用Key已按原授权安装；没有实际人工干预必需动作。
