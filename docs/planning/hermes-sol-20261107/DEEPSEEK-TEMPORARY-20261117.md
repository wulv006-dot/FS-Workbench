# Hermes 临时使用既有 DeepSeek 通道

用户要求：OpenAI额度用完时临时使用已配置的DeepSeek继续处理。负责人Codex；独立分支codex/hermes-deepseek-temporary-20261117，基线25ea08c6097a9720d6a250d6d6596032532087b0。保留另一条OpenAI适配器及凭据，不购买或充值。

## 当前事实与最小切换

187同时安装deepseek-flash与gpt-6.1-sol两条适配器；DeepSeek原凭据文件存在，原客户端/models真实返回verified。官方/user/balance只读回执为is_available=true、CNY75.64（本次检查时点，不是长期余额保证）。没有输出密钥，未据此声称已完成业务报告。

普通聊天原本使用DeepSeek；报告和pricing_review_v3在NativeConversation.dispatch中硬选Sol，因此不会因额度不足自动替换。临时只改两份活动源的三个接点：新准入模型使用已有deepseek-flash，gateway使用原DeepSeek默认路径，新报告预算policy_id沿direct_provider。保持工具、用户身份、来源、知识、权限、用量账本、原ID、UNKNOWN及共享锁。OpenAI适配器和显式Sol路径保留；营销控制台独立的Sol建议接口不在这次报告/FC复盘切换范围。

仅影响新请求；旧failed/unknown任务不换ID、不盲重发，不宣称失败任务已自动恢复。FC每小时算价、writer和market-anchor计划保持。

## 验证与发布

报告派发失败先行测试确认原模型gpt-6.1-sol与期望deepseek-flash不符；改动后报告32项、FC复盘13项通过，新断言核准入模型、账本模型/policy一致；原ID去重、lost202恢复、只读权限与独立provider锁保持。Windows附件测试缺openpyxl，按模块锁文件准备隔离依赖，不把缺失当业务通过。

原发布器为hermes-conversation-20261018/deploy/runtime_prepare.py的software增量及runtime_release.py。两目标按当前Git基线证明、完整现场保护和原准入栅栏，在无活动模型任务时发布。Linux/CI/发布和真实入口回执待完成，不以源码存在认定已切。平台拒绝新建独立审查子代理（agent thread limit reached），不伪报独审通过。

回切仅恢复本次三处原Sol选择及openai_provider.POLICY_ID；先核当前字节与任务状态，沿原publisher精确增量。保留账本、任务、配置和后来无关更新，不整包覆盖。没有新增自动重试、自动跨供应商回退或新调度器。