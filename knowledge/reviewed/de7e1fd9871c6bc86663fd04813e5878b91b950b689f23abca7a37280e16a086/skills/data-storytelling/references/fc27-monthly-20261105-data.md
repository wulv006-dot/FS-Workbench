<!-- Generated reference; source 46034b081c7a132f73fb684200859493dd6b6304 knowledge/reporting/fc27-monthly/DATA.md; utf8_lf_sha256=d8ae2400a8d46ae1bf9154b94bc11239d88968e04eaa8fa0fd0de47a5f0a43ed -->
# FC27 月报：取数路径与计算口径

核查基准：2026-11-05项目规则；工具示例源于2026-11-02／03已核教材。运行时以实际 schema 和当前权限为准。完整说明见[团队规范](https://github.com/wulv006-dot/FS-Workbench/blob/46034b081c7a132f73fb684200859493dd6b6304/docs/planning/report-methods-20261102/01-团队经营报告取数与分析规范.md)，本页给查找路线。

## 先固定范围，再取核心数

月报固定完整月与可比期间，再补月内周趋势／首尾等长窗口；新品不足整月要说明经营天数。每份核心证据留来源、游戏、网站、时间字段/时区、起止边界、状态、币种/单位、采集时间与覆盖。优先复用相同范围的完整冻结档案，不把目录中最新文件直接当目标期间。

| 目的 | 人工/维护入口 | 已有助手工具与限制 |
|---|---|---|
| 能力与已有证据 | 当前会话工具 schema、授权数据目录 | `fc.get_data_catalog`、`fc.read_skill`；`fc.read_evidence`沿原 evidence_id 展开 `content_index/next_offset` |
| 付款销售、订单、新客 | Admin原生经营汇总；`/admin/order.Order/orderStaticsDetailByEs` | `fc.query_native_statistics(profile,start,end)`；响应另核网站。此工具无 `profit_site` 参数 |
| 主采购毛利、每日曲线 | Order统计管理→发货统计；`/stats/admin_index/delivery.html` | 已认证FS `/dashboard/fs-home/transactions/range.json`；`mode=summary` 或 `profit-history`，同游戏/日期/网站/类目，`profit_basis=shipping` |
| 商品、优惠、新老客、来源 | Admin ES销售订单下载；`/admin/order.OrderExcelByEs/downloadsMake` | `fc.query_es_order_structure`；优惠用 `fc.query_discount_analysis`，分组 `new_customer/type/day/channel`，单窗最多31天 |
| 指定商品/模型 | Admin真实PID与商品目录 | `fc.query_product_orders`，PID或model二选一；当前主站266，PID查询不带platform，模型平台筛选按schema |
| Ads、GA4、GSC | 已发布营销快照/原只读Reader | `fc.query_marketing_snapshot`当前示例为FC27；完整计算集合与显示Top分开 |
| 客户后续消费 | 成熟首购群体、私有稳定客户关联 | `fc.query_cohort_observation(action=read)`；核实际截止、关联覆盖与成熟度，不新建追踪计划 |
| 履约/售后、实际动作 | Order详情/日志、已冻结同窗发货和原执行账本 | `fc.query_queue`是当前池，`fc.get_problem_clues`是样本线索；`fc.query_action_history`与历史证据区分建议/执行 |

维护工作站通过现有 `server_187/access/Invoke-Server187.ps1` 使用已授权只读适配器。Admin走HMAC主8912、备用8911、容器桥8913；本机 `127.0.0.1` 不是云会话或同事电脑的可直连地址。8767模拟登录已退役。读取不借用FC writer；报表不靠运行定价或刷新采集取得历史。

### 常用调用形状

以下日期仅演示历史完整月，真实任务替换为所需期间和本会话支持的准确profile：

```json
{"profile":"FC27","start":"2026-10-01","end":"2026-10-31"}
```

这是 `fc.query_native_statistics`／`fc.query_marketing_snapshot` 各自的参数形状，分别调用，分别核响应来源。详情接口按实际分页和上限分窗；28天限制只适用于已核对应详情接口，原生汇总不机械分段。

FS发货毛利示例查询字段为 `mode=summary&profile=FC27&start=2026-10-01&end=2026-10-31&grain=day&profit_site=all&profit_category=-1&profit_basis=shipping`。`all`与`main`明确选择；该summary结束日包含当天、内部转次日00:00。其强刷是 `refresh=true`，其他层可能是 `refresh=1`，按端点合同使用。一般复用同范围缓存，不默认强刷。

ES缺档时沿已有导出请求轮询和读回，超时先查原ID和文件，不重复提交。归档清单、实际文件、SHA、解析与覆盖均需核实。输出截断先展开证据，不能当上游缺数。

## 销售、采购毛利与优惠

- Admin主销售为已付款订单，退款付款记录保留并另列；具体ES/客户群体按其状态合同投影，不能全源统一删退款或统一保留。
- 主毛利为同一Order发货统计响应中的**人民币销售总额−采购总额**。分游戏率用该行原值；全局率=总采购毛利÷总销售额，不平均游戏/日期百分比。可能含部分退款、争议、欺诈的已发货记录，不称净利润。
- AOV=同范围付款销售额÷付款订单数；Admin `customer_price` 为付费客户均额ARPU。订单数不当人数，客单价不当Coins单位价。
- ES折扣金额已统一USD，不按原币实付再换一次。平均让利按金额加权；新客标记订单全部优惠不等于新客专属活动成本。已扣优惠不再重复扣。
- 同订单多SKU的整单金额去重；缺行金额不冒称SKU收入。缺SKU成本不按销售占比硬摊商品毛利。主毛利、同批实际贡献、估算贡献分别标识。

## 获客与客户价值

广告CAC=对应投放费用÷同范围明确广告来源的新付费客户数。先游戏/网站/付款期/有效状态/订单去重，再新客标记和真实广告来源，优先稳定客户键去重；身份字段缺失时说明近似人数与核对依据。空白来源为未知；广告费除全渠道新客不称广告CAC。

跨游戏和品牌系列的费用/平台价值单列；真实FC成交保留。系列名含FC或US不证明费用全归FC或用户在US。国家费用用实际投放地域，国家订单用原国家代码；名称相近不足以认定系列CAC。

历史复盘案例（2026-11-03最终口径）：FC专属CAC约$53；团队确认综合CAC约$42，直接标确认来源，不反推其费用/人数。成熟FC26客户赛季收入情景乘已核FC27毛利率估计采购毛利约$46。三者各自保留期间、群体和估计身份，不作为当前扩量线；首单比例折算约$32已退役，不再用于行动。

客户价值包含只买一次的人，首购群体在看后续活跃前确定。按同批30/60/90/180日/赛季累计看收入、复购、订单和观察截止；单笔客户付款跨度为0，平均首末跨度不称客户寿命。`paytime=0`识别为无付款时间，不能变1970年；未付款尝试不计消费。

用户指定理想口径时，可承受广告成本≈每客累计收入×对应采购毛利率；无逐客成本则明确为估计，不自行增加费用预留。回本期限与观察窗口一致，赛季价值不能承诺30日回本。全盘老客/免费渠道不重复加进每个广告新客价值或抵扣广告费用。具体新预算、价格、折扣仍需当前授权与必要当前数据。

## 自然搜索与页面购买

| 问题 | 来源、维度与指标 | 解释 |
|---|---|---|
| 自然访客看过商品页多少次 | GA4 `pagePath`精确URL + `sessionSourceMedium=google / organic`，`screenPageViews` | 可重复浏览，不是首次入口人数 |
| 有多少访问从该页开始 | GA4 `landingPage` + `sessions` | 首次落地会话，不覆盖从其他页转来的浏览 |
| 自然入口有购买信号吗 | 同精确入口/来源的 `ecommercePurchases` | 购买事件，不自动等于FC后台付款订单 |
| 交易收入是否可核 | GA4 `purchaseRevenue/grossPurchaseRevenue/transactionId` | 金额0或ID未设置若属埋点缺失，记unknown，不宣布零收入 |
| Google搜索表现怎样 | GSC同页/词/国家/设备的点击、曝光、CTR、平均排名 | 点击不等于GA4浏览；GSC日历时区与GA4分别保留 |

主英文页 `/Fc-27/Coins.html` 包含在全部语言页中；优先比较“主英文 vs 其他语言”，避免重复相加。语言页不等于用户国家；`/de/fc-coins.html`内容页与`/de/Fc-27/Coins.html`商品页分开。自然语言优先级用自然数据，全部来源购买排名放辅助维度。GSC单页历史不能代表全FC SEO同比；GA4历史空返回不当零。完整URL、属性、日期、来源过滤、时区、行数与阈值保留在证据中。

原Reader定位：`/opt/mmoexp-marketing/details/collect_details.py`，既有Python环境 `/opt/mmoexp-marketing/venv-ssl/bin/python`；先核当前路径和权限。完整营销快照看 `period.sources/adsAccounts`、`calculation_campaigns`和完整地域行，不以Top展示值计算全盘。来源有用即可支持方向，跨源未连接的人群只做诊断，不冒称真实漏斗转化率或精准因果。
