# 活动统计有限重试合同（候选）

范围：既有187活动统计的只读来源。北京时间00/08/16、UTC统计日、固定快照槽、原scheduler flock、身份隔离、lastSuccess回退与退出0/2/1/124语义不变；不修改其它业务调度，不加入失败定时器或重试平台。

每个槽/来源一次正常读取，最多额外2次，总计不超过3次。只有识别出的临时原因重试：TimeoutError、明确backend只读子进程超时、指定网络错误、HTTP408/429/5xx、日志读取超时/读取中轮转。一般SOURCE_READ_FAILED、BACKEND_UNAVAILABLE、未知原因、鉴权/权限、参数、身份改变、日志历史缺口/容量限制和非法结果不循环重试。

首次重试至少等2秒，第二次至少5秒；有效Retry-After秒数或HTTP日期要求更长时取更长值。等待加原来源完整单次超时和1秒收尾余量若超过整轮360秒预算，就保留最后原因并记录run_budget，不截短服务端等待后提前发请求。仍保留来源原超时（请求日志10秒、PostHog15秒、收入桥120秒）、Python390秒进程组保护与systemd420秒上限。预算不足的来源明确缺测；“最多3次”不代表每次都必须耗尽次数。

重试在单来源内部串行，上一读取已结束才再试。成功的同槽来源结果复用，不再次读、重复累加或制造事件。原Python flock覆盖整个worker生命周期（包含退避），其他定时/人工包装调用仍不能并发启动第二个worker。每次开始及返回后核public release/config/start和UTC日是否仍一致；变化则SOURCE_CONTEXT_CHANGED，不发布该次旧结果，也不继续重试。已有消费端日期/身份校验和旧成功隔离继续生效。

脱敏记录存每来源lastAttempt.retry：attemptCount、retryCount、elapsedMs、stopReason以及最多3个attempt的状态、分类原因、耗时和等待毫秒数。记录不含token、URL、原始事件、订单、堆栈或任意异常文本。最终失败保留同身份原成功值和原区间，partial仍可见。成功后仅替换该来源当前区间汇总，不把三次读数相加。

生产载荷预计为analytics/statistics-retry.mjs新依赖以及statistics-refresh.mjs、server.mjs、discount-revenue.mjs、backend-client.mjs；复用原publisher，并强制消费者载荷包含新依赖，防止缺文件启动失败。无需修改timer/service或前端、无需提高现有超时。backend-client的超时分类仅discount_revenue读取动作受影响，其它读写动作处理保持原行为。

隔离验证覆盖临时失败恢复、严格次数/总预算、Retry-After、确定性错误只一次、成功来源不重采、顺序调用、跨日/配置改变、旧成功隔离、backend真实子进程超时与输出超限区别；复用既有Linux真实锁/进程组超时用例。所有生产失败注入均未实施，真实“遇到临时失败自动恢复”需上线后自然周期证据，不能用隔离测试替代。
