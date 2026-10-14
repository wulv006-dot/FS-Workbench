# Hermes FC 最大规格修复（候选）

用户已明确输入、输出采用百炼最大值，费用不是缩小分析能力的理由。原十个 FAILED 和已知/未知费用保持；新验收使用新任务，失败调用不重放。旧顾问退役安排在试点报告交付之后。

准确规格来源：[百炼 deepseek-v4.1-flash 官方详情](https://help.aliyun.com/en/model-studio/deepseek-v4-1-flash)，2026-10-14 本轮实读 Context Limits：输入/思考输入/上下文 **1,000,000 Token**；输出/思考输出/思维链 **393,216 Token**。这是 Alibaba Cloud Model Studio 路由；不借用 Vanchin 或 DeepSeek 直连规格。上下文是供应商实际 Token 限制，不保证同时容纳 1M 输入和 393,216 输出。

| 链路 | PR130 活动值 | 本候选 | 性质与验证 |
| --- | --- | --- | --- |
| AIAgent / FS proxy / 百炼请求输出 | 65,536 | 393,216 | 所有 Hermes 档位；reasoning 包含在 completion，不重复收费 |
| 原生上下文配置 | 1,000,000 | 保持 1,000,000 | 保留固定版本 ContextCompressor，不替换为本地剪裁器 |
| 输入准入 | JSON 字节估计＋输出当 Token 相加 | 删除此硬拒绝 | 字节余量仅用于预留估计；供应商真实 usage 结算 |
| 模型请求/响应 | 1MB | 10MB UTF-8 传输边界 | 与固定官方 Runs 的 MAX_REQUEST_BYTES 一致；不称 10MB＝1M Token |
| 工具参数 | 4096 字符 | 同传输字节边界 | 完整 JSON 解析及每个 FC 工具 schema/范围继续验证 |
| 工具/最终 Runs 读回 | 128KB | 10MB | 无局部截断；超过真实传输边界明确失败 |
| 历史证据 | 累计 24KB，重复也扣配额 | 无累计字节配额 | 保留页/章节/原字节分片与 source watermark，不当成现时事实 |
| Admin/Order 投影 | 12KB 删除行/事件 | 保留授权投影全部行/事件 | 上游真实不完整仍 partial；不伪造完整性 |
| FS 百炼等待 / SDK read-stale-outer | 600 / 660 秒 | 1800 / 1860 秒 | 单调用时间边界；无新费用或总运行配额 |
| 原生 compression | 缺 max_tokens / 探测 stream 被拒 | 任务绑定摘要适配 | 默认无 tools、无 max_tokens 的官方摘要 plain 请求继承该任务档位与最大输出；不新增密钥或路由 |
| compression 流式探测 | 未验证完整原生恢复 | 预留前 HTTP400 | 固定官方 auxiliary_client 原生转 plain 一次；只 plain 有一笔实际调用/结算，不把 JSON 冒充 SSE |
| 最终报告 SQLite / UI | 无额外文本/条数截断 | 保持 | 新增大报告验证、完整保存及读回测试 |
| 迭代 / 总任务期限 | 官方 sys.maxsize / None | 保持 | FS 续租至终态；用户可取消 |

任务问题字段的 600 字符用于简短调查指令，审核背景 32KB 与章节分片用于固定方法资料，容器 2GiB 为运行资源约束；它们不代表模型输入 Token 上限。经营证据通过已授权只读工具进入分析，固定方法文件没有冒充动态经营输入。没有更改 Nginx、账号、授权、业务数据库写、价格、订单状态、采集频率或其他服务身份。

固定官方源仍为 `71d34bad1045610252eda02ee79549436896e784` / v0.21.7，原镜像不重建。摘要依据：官方 `agent/context_compressor.py` 的 `_call_summary_llm` 不传 max_tokens；`agent/auxiliary_client.py` 的 `_create_with_progress_once` 对非鉴权/付款/瞬断错误先尝试 stream，再退 plain。主工具请求仍须匹配 FS 颁发档位和 19 工具名单。摘要无工具权限，结算/取消/短期任务 token 与主请求同链。

独立候选 `.agent_runtime/hermes-max-capacity-qa-20261014/`；冻结 `MAX-CAPACITY-LOCAL-FREEZE-20261014.json`。原 publisher 新增精确十目标范围（原八目标＋research＋capability provider）；347 文件现场栅栏中另337保护。只重启原 FS 与 Hermes，Admin 保持。正式 CI、固定官方摘要往返、最终发布/独立读回、真实新任务报告分别验收。本文件为候选设计，不声明部署或业务通过。
