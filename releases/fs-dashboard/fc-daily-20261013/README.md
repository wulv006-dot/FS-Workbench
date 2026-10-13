# FC27 自动经营日报

复用现有 FCDetails、Admin 只读会话、日期缓存、范围服务与 FC「日报与复盘」页签。每日北京时间 09:15 生成前一完整自然日；09:00 现有营销日报错开十五分钟。FC 原接口没有独立就绪信号，生成前校验完整支付日覆盖。数据失败最多三次，间隔十分钟、三十分钟；启动时可补当天应生成的昨日日报，不补造多年历史。

自动任务运行在已有 fs-business-range 服务内；持久化到现有缓存根下 fc-daily/daily.sqlite3。源订单不进入日报库；仅保存确定性汇总、数据快照编号、读取时间、生成时间及版本。历史最多一年可生成，页面列最近九十个日期和单日最近三十个版本；旧版本仍在数据库保留。

入口复用 `/dashboard/fs-home/range.json?mode=fc-daily&date=YYYY-MM-DD`，页面在 `/dashboard/analytics/` 的 FC27 → 日报与复盘。读取要求既有登录身份；手动生成要求现行 access_policy.ADMINS，`action=run` 加单次 request_id 以及同源自定义头。未更改任何账号、代理鉴权、安全网络或业务订单。

SQLite BEGIN IMMEDIATE 在入队、取任务和模型回执建立前串行化；同日期并发合并，同 request_id 重试复用。全局仅一个待执行/执行中报告，服务进程另有文件锁。人工频率至少一分钟、每天最多十六次；模型每天最多三次、相同投影仅一次，调用前写入回执，不确定结果不自动重试。重启中断任务记录失败，原日报不覆盖。只读任务可在原记录上核查后重生成。

一期维持 W0–W5：MMOEXP 主站细分，已配置卫星子站合计；独立分销组缺可靠归属字段，报告明确不声称完整排除。新老客、利润、成本、备注原因及没有同口径前一日报的环比不推算。缺金额显示暂缺；支付日未完整则拒绝发布新报告，保留旧版；履约池失败可降级。

DeepSeek 沿用百炼北京 fs-green-pilot / deepseek-v4.1-flash 接口与脱敏白名单。只传报告日期、主站订单数/USD/问题数量、受限平台/产品前五汇总及已验证可比差值；不传原订单、客户、账号、支付资料、客服原文或密钥。模型输出限制为证据引用、定性解释和核查建议；所有数字由既有程序计算。

服务端仅使用**已有配置** `FS_DAILY_MODEL_KEY_FILE` 指定的同服务身份私有文件。当前服务器尚无此配置，因此只会明确返回 configuration_missing，不会从本机复制密钥或尝试其它模型/代理。这是待批准的具体上线缺口，事实报告可用不代表 AI 日报完整验收。

直接测试：`cd source && python -B -m unittest -v test_fc_daily test_fc_release`。复用现有 pr-fast 添加本模块映射；没有新增 workflow。模拟测试覆盖真实数据合同、权限/同源、并发、幂等、失败保持、未知模型回执、日期边界、历史和调度；真实角色、自然触发及模型调用须另外读回。

发布：deploy/release_navigation.py 是既有受控 publisher 的精确三文件扩展；前端沿用 release_workspace.py、十五静态资产和三个版本引用。已有发布锁、哈希 CAS、备份、失败回退和退休发布器检查保留。只重启范围服务；前端配置只更新不可变版本地址，鉴权不变。

回滚先运行 frontend/release_workspace.py rollback，指定本次前端 backup 与 approved-manifest SHA；再运行 deploy/release_navigation.py rollback，指定本次后端 backup 与相应 SHA。以实际发布回执为准；保留日报库、模型回执、旧资产和所有业务状态。来源基线 main 91437ec06b151e6a1337da424167e469aaf729e6；发布结果及自然周期另归档，不以本文冒充验收。
