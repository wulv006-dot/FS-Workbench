# DeepSeek 客户端追踪与 Hermes doctor：2026-10-14

当前实际主线仍未验收：第十三个 wulv 调查 FAILED，无经营报告。流式前八次成功共449257 tokens（其中32141 reasoning 已计入 completion），第九次 ConnectionResetError，35.24秒；旧任务及未知用量原样保留，不重放。

候选基于 PR134/main 1d8d0cd118a6beb80634054cee09bf3ea595f97b，仅改 direct_provider.py、proxy_gateway.py 及对应两份测试。原FS进程、Key位置、模型、high/max、1048576上下文/393216输出、业务只读工具、采集频率和原publisher均保留。无新依赖、无自动重试。

每次实际请求创建独立 local_trace_id 和UTC开始时间。收到响应头后立即保存 X-Request-ID，使用 provider_http_request_id 与响应正文/流的 provider_response_id 分开；成功的旧 provider_request_id 仍表示验证过的正文ID。发生断开时保留安全关联ID、opening/reading_stream/reading_body/http_rejected 阶段、响应头是否收到、已读字节和事件计数。收到响应头前断开则仅有本地追踪ID，不伪造上游Request ID。异常原文、Authorization、其他响应头、原始经营数据和私有推理不入诊断。

统一账本在成功、未知和无效响应三种结果中保存同一追踪投影。未知不会因存在ID被改成成功或零费用，同一未知turn仍禁止重放。

固定 Hermes v0.21.7/71d34bad 的 doctor.py SHA256为52f088fee433c991ea5e1e128568a48a9b5c005b1ea1011f91b9cbc25e4f864c。10:17:21 UTC使用当前配置、固定生产镜像、临时profile、禁网络和无密钥/业务挂载跑诊断；Python3.14.7/SQLite3.53.4/OpenSSL3.0.20与核心包通过。exit1四项为缺.env、精简配置版本v0→v50、未配置通用工具密钥、缺CLI launcher。没有执行--fix/--live或改生产profile。首次临时挂载根目录权限错误另存，不当成生产问题。

实际DeepSeek发送者为原FS Python3.9/OpenSSL1.0.2k，未安装requests/httpx/openai；Hermes doctor检查的是容器环境，不能代替该发送者网络诊断。目前没有足够证据断言旧TLS就是ConnectionResetError根因。

官方依据：[Hermes doctor](https://hermes-agent.nousresearch.com/docs/reference/cli-commands#hermes-doctor)、[DeepSeek流式协议](https://api-docs.deepseek.com/api/create-chat-completion/)。官方公开API文档未核到保证每次异常都带X-Request-ID；按实际收到的头捕获，不把缺失ID当成功/未出网证明。

放行链：冻结UTF8字节（ASCII JSON传递）→对应Linux pr-fast/官方high-max Runs回归→draft PR/确切树合并→原publisher/CAS备份→独立生产读回→新的wulv任务验收。本文为候选设计记录，不声称尚未执行的CI/发布或实际报告已成功。
