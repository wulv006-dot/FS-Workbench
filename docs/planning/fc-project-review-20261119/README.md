# FC 项目经营复盘入口

吴律负责 FC 项目。正式菜单位置为「球类工作区 → FC 项目经营看板」。同一份带期间、范围、来源、覆盖和修订号的聚合数据供页面、Claude 和 Codex 使用。先核实销售变化和可解释的来源。按[项目经理确认的分工](../../../knowledge/reporting/fc-project-owner.md)，SEO 和广告的疑问分别提交专项负责人，其余环节由吴律亲自下钻、跟踪与确认。

## AI 取数

近三个完整日的已付订单、采购成本及同单毛利率可使用原操作的 `view="same-order"`。口径、覆盖及发布路径见[快速查询](connector.md#三个完整付款日的同单采购毛利)。

1. 先调用本人已授权的 FS 工具 `fs_list_data_sources(module="unified-business")`。目录中选择 `business.fc_project_review`，传 `{"profile":"FC27","start":"2026-11-16","end":"2026-11-18"}`。按原参数续查 202，403 停止；大响应按 `data_path` 和 `next_offset` 取全。用本周至昨日完整日，对照上周同星期几；月报注明是完整月还是同日进度。FC26 与 FC27 用真实游戏标识分别查询，2026 年 9 月可同时有两代销售。早期历史受原数据源覆盖限制。
2. 请求对照窗口，用 `/packets/0/kpi`、`daily`、`ordersData`、`adminDimensions`、`traffic`、`prices` 下钻。先核游戏、全站、实际日期、时区与覆盖。若当前客户端尚未列出专项方法，已登录同权限网页使用 `/dashboard/fs-home/range.json?mode=fc-project-review&profile=FC27&start=2026-11-16&end=2026-11-18`；基础原源独立可用，见下表。API 查询会按需留存聚合版本。相同期后续修订保留旧版；HTTP 参数 `refresh=true` 可显式重取。同一期用相同修订号复盘，实时取源的时间也要保留。
3. 先算全站差额，再在同一个维度内把少了多少订单、少了多少收入排出来。对销售额按订单数与客单价做对称分解，数量贡献等于两期客单均值乘订单数变化，客单贡献等于两期订单数均值乘客单变化。地区、支付、产品和客户会描述相同订单，不跨维度累加。同一笔交易在不同系统用站点与原单关联；必要的授权明细可进一步下钻。
4. 产出项目会议用的报告，给出量级、原因强弱和待验证材料。对照期不全的渠道只比较同序已完成日。记录每项负责人、措施时间、预期指标和复查窗口；下轮用实施前后同口径数据核效果。业务动作和结果分别记录。

| 问题 | 正式来源及字段 | 计算、范围与限制 |
|---|---|---|
| 销售、订单、客户、国家、支付 | `business.summary`，`profit_site=all`，读取 `/profile/supplement` 的 Admin 已付款窗口、原生维度 | 实付 AOV = USD 销售 / 已付单；新客人数 / 窗口去重付款人数；国家、支付的金额与订单可对回整体。订单口径的新客标记另列。 |
| 采购成本和利润 | `business.profit_history`，`profit_basis=shipping`，原生全站 Order 发货统计 | 发货交易日人民币销售减采购。期间总毛利 / 总发货销售；成本率为同组采购 / 同组销售，零分母未知。 |
| 商品、用户分档、平台 | [订单与商品](orders.md)，`orders.py`，按固定共享 ES 发布版本和原生 PID 分类 | 每单唯一归属，显示未识别项；热门球员/SBC 为已核单一 PID 子集。新老客户用窗口首笔可核标记，累计消费分档按完整期间客户去重；折扣率为同单优惠美元额 / 同单优惠前美元额，给出分子分母覆盖。 |
| 订单渠道和投放 | [广告、自然搜索及归因](traffic.md)，`marketing.range`、`channels.facts` 与既有 Ads/GA4/GSC Reader | FC 专属与跨游戏系列分开，实付、广告归因价值和 GA4 购买事件独立比较，标记网站及归因成熟度。 |
| 价格策略 | `prices.py START END`；原 `actual_price_windows` 与操作实际站点 266 完整读回 | 按平台、购买 100K/1000K 统计期间实际读回观测数和范围。测效果需用下单时刻匹配实际价表、数量与同单成本，观测中位数不可用作新报价。旧标量缺少曲线时保留缺项。 |
| 交付 | [Order 事件、抽样和分母](fulfillment.md) | 金币按购买量小于 1000K / 至少 1000K；区分完成样本的全程时长、问题处理分段和包含在途的真实完成率。时长起点、末次足量交付、日期与样本覆盖独立保留。付款到首笔发货只是一项诊断。 |

## 本地复跑和归档

在仓库 `releases/fs-dashboard/fc-project-review/` 下运行。接入 FS 的 AI 可以直接使用当前连接器。需要原生统计的 CLI 使用现有已授权访问令牌环境；`requests` 仅输出同样的调用，无需新凭据。

```text
python review.py requests --game FC27 --start 2026-11-16 --end 2026-11-18
python review.py fetch --game FC27 --start 2026-11-16 --end 2026-11-18 --output <private>/core-view.json
python review.py build --core <current-core.json> <previous-core.json> --orders <orders-now.json> <orders-prior.json> --traffic <paired-traffic.json> --prices <prices-now.json> <prices-prior.json> --delivery <delivery-now.json> <delivery-prior.json> --output <private>/review.json
python package_dashboard.py --data <private>/review.json --output <private>/FC项目经营看板.html
```

服务器聚合保存在 `/var/lib/fs-fc-project-review/<游戏>/<起日>_<止日>.json`，可复查版本在同目录 `versions/`。真实客户身份、访问令牌与订单明细留在原资源边界。正式页只装载页面资源，经营数据由真实登录及原后端管理员权限验证后读取；本地内嵌数据的 HTML 按经营报告管理。源码、CI、正式菜单、线上数据读回与实际报告分别验收。

## 施工与验证

先在全站 Admin 与 Order 既有路由核对范围，再接入 ES 固定版本、投放与流量读源、定价读回及交付事件。按日期生成聚合存档后，页面和 Agent 读取同一版数据。交付检查包括核心金额和分母、日期、分类失败隔离、两代游戏边界、前端交互、真实菜单与权限、独立 AI 本周取数和会议报告。本轮参考用户提供的两份 HTML 的表达与图表，并用当期原始源重新计算。
