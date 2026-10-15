# 已接通的现有行情只读工具

FS研究工具：`fc.query_market_snapshot({"profile":"FC27"})`。先读目录，再调用该工具；同任务保留首个可用回执及来源run/SHA。当前行情不能当作研究历史期间的订单成本。

原生Hermes桌面可直接用终端执行：

```sh
python3 -B /fs-source/market_snapshot_client.py
```

这是实际只读取数入口，返回现有采集结果，不启动采集、报价或改价。客户端在进程内使用已有Desktop身份认证；不要读取、打印或让用户重新提供token/Order会话。调用失败报告`market_bridge_unavailable`，不能改为读取凭据或开放网络重试。

范围固定FC27 Game Coins，PS/XBOX/PC，100K购买档；Lootbar、IGGM、U4GM、U7Buy；Order对应平台订单发货成交成本（CNY/K）；MMOEXP主站公开商品；中国银行CNY/USD折算价。赠送单列，不把100K线性折为1M的真实可买报价。

每次保留`collection_run_id`、`run_sha256`、来源采集/成交时间和`freshness`。`captured_at`是本次读取时间，不是各来源发生时间。`status=available`只表示现有四类来源可读取；`offer_completeness=partial`、`complete_comparable_offer=false`表示交付、优惠码资格、额外费用和有效期仍有缺项，不自动推荐新售价。

Lootbar的`auth_state`和`coupon_excluded`原样披露；不能把登录态报价称匿名价，也不单凭false断言用了券。中行`published_at`可能只有日期，`publication_time_status=not_provided`不能被读取时间填补。缺值不是0，0赠送有效。分析费率5%仅为已给定情景口径，不改生产自动改价规则。没有新增定时任务或监控。
