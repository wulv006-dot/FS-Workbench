# 业务模型推理诊断与当前政策

2026-10-13。用户明确要求分析/决策至少 high，复杂调查/定价权衡 max；简单任务中档映射当前支持值并说明，禁止静默关闭或降到 none。施工会话 Sol xhigh 与业务 DeepSeek 模式分别配置。

## 已核实

百炼官方 [DeepSeek API](https://help.aliyun.com/zh/model-studio/deepseek-api) 推理强度章节明确：deepseek-v4.1-flash 支持 low/high/max，默认 high；HTTP 顶层 enable_thinking 控制是否思考。官方 [模型页](https://www.alibabacloud.com/help/en/model-studio/deepseek-v4-1-flash) 列北京地域 Function Calling 支持。不能用其他推理服务商的映射代替当前百炼 API，也不能认为网页支持即当前业务空间已实际验通。

本轮真实服务器只读：ai_advisor_model.py SHA `02d720bdfbc458ef2f94107bb139e077325f6e8d78fcc677718383d5f0e02a4e` 的请求字典写死 enable_thinking=False；fc_daily_model.py SHA `37310fdab22eccebd1a695f27a90016e2fdf6cf8fd6b07c62835a2a0631fb5ec` 的模型为 deepseek-v4.1-flash。range/boss SHA仍匹配已保护基线。未读密钥、未调用真实模型。

最初 Hermes none-only 为继承旧顾问非思考参数的临时兼容实现，不是用户最终政策、不是服务商能力限制。已承认此实现会阻止更深业务思考，候选正在纠正。旧质量差是否主要由此导致尚无同输入对比，不能宣称已证明原因。

## 修复方向

- FS可信任务令牌固定推理档位；模型不能改档、关闭或换provider。
- 开启时明确发送 enable_thinking=True 与百炼支持的 reasoning_effort；不发未列支持的 preserve_thinking/thinking_budget/tool_stream，不切 Responses。
- 保留工具轮次所需的 reasoning_content；仅内部跨轮回传和私有账本，不向用户展示原始推理。旧非思考消费者的请求不变。
- 思考token包含在completion_tokens中计费，单独记录reasoning_tokens时不重复加算；未知usage不记0。
- 模拟官方Hermes思考→工具→第二轮请求须通过；再真实模型/只读工具及第二用户轮分别验。拒绝、不支持或截断明确失败，不自动降档求通过。

## 最新验证（动态状态见 runtime-progress.json）

此前 CI38427644112 已验证13项受限工具的非思考完整往返和幂等，仅为合成协议证据。新的思考/技能候选85项本机测试通过；真实思考尚未验，不将测试等同经营达标。

2026-10-13T16:xxZ 后续：CI38429960931/head0729f57e 成功完成固定官方 Hermes high→原代理→假 provider→真实注册工具→下一工具轮请求；reasoning_content 完整私下回传，主技能实际加载。这是官方运行集成证据，provider 和经营数据均为合成。2026-10-13T17:xxZ 本机新版101项通过，补取消接收竞态、16K思考输出空间、finish_reason原样保留。真实百炼 high/max 尚未做，新版第二用户轮须最终 CI；未发起或重放生产模型请求。
