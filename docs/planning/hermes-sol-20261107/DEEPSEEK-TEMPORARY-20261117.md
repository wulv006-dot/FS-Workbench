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
## 发布与真实通道验收

PR #1216 https://github.com/wulv006-dot/FS-Workbench/pull/1216，代码742c057e18f12422dff69480ee2d39aeb16adb39，合并10971905888b9159961ed76c3405cc43de029fb1。正式CI44082007164/job134034687750通过（287+60+58+20+111=536项单测）。183 Python3.9报告32项、FC复盘13项通过；更宽附件套件的本机/隔离包依赖缺失不计通过，由正式CI原会话套件覆盖，未为此放宽断言。

原software增量发布nav-20261117T122500Z，manifest061c97c4f18a0b1437c019563d64ff5ac39b7c8e6d136c01a68705ede25b14c6。两目标、49保护项精确读回；conversation_native.py=d323ccded74647453a858cc984bce440d3af6e181ae183fc1c481a1673322861；native_reports.py=1389b491208f501e059edc0d8afed5af77dd8c7bf605a53910a2b5da6f7d3555。原回执applied-awaiting-actual-http-role-acceptance，业务worker/timer操作0。Hermes/range及FC三服务均active。

真实DeepSeek原网关核验使用独立合成测试上下文与独立临时账本，不含业务/客户数据、不创建FS用户会话、不注册业务写工具；一次实际调用返回DS_ROUTE_OK、模型deepseek-flash、17输入/4输出/总21tokens，账本succeeded。测试请求fb8a11ee489d4b0381a51cdf11f5d6bd，原回执保存在187暂存发布目录的provider-smoke/receipt.json。序列化回执曾因SQLite Row对象失败，随后只读原成功账本补录，没有重发或重复付费；之前导入/字段校验失败均发生于网络前。费用金额未回传，不写零费用。

本次证明部署接线、原报告/复盘派发合同与真实provider通道；尚未重新生成完整业务报告，也没有重跑旧failed/unknown请求。真实FS网页本次测试浏览器停在登录页，未冒用用户身份做报告入口验收；后续正常登录的下一新报告/复盘将消费当前接线。营销控制台独立Sol建议接口仍按原合同。

knowledge_closeout本次KL-3600022b9e51d08cb4e9869d：affected_ids=[]、steps=[]、无冲突或新业务规则发布要求。官方余额接口说明：https://api-docs.deepseek.com/api/get-user-balance/ 。检查时75.64元仅是该时点余额，真实后续用量沿原账本和供应商余额。