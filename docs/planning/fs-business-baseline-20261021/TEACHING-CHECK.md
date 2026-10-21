# Hermes 教学与检验口径

这是本次检验设计，不是已完成的教学回执。最终结果另附原任务 ID、模型回执和工具证据。

## 先应用当前业务基准

新任务应冻结 `business-baseline-20261021-v1`，实际 system 输入须含该版本及 SHA；旧 Desktop 业务记忆与旧 reviewed-business 规则不再装入。保留报告方法和有效的正式经验。仅看到目录、文件或模型说“已学习”不计通过。

实际场景先让 Hermes 判断需要什么证据，再自行调用工具。例如：区分折扣码推广分类与站点归属，核优惠的 USD 字段和新老客原标记，结合原生总盘解释渠道结构。渠道表里“分销”不能直接排除为 G2G/ELD；未命中和字段缺失不能算无码。单笔原因须明确使用 Order 日志，未接入工具时不得假称已核。

## Astra 独立参考

在基准、工具与真实入口完成后，请 Astra 独立阅读业务基准、实际资源目录、当前策略与可用数据，形成有条件的 FC 动态定价参考。交付必须标出事实、假设、缺项、候选规则、约束、反例和撤回条件；缺有效当前成本或可比报价时只给公式和条件，不给具体新售价。完成此项后结束 Astra 环节。

当前引擎只读模拟支持全平台共享的四档降幅研究，不支持平台独立规则、优惠券、新产品和真实执行。可以研究超出旧降幅的规则，但不能把模拟支持范围说成所有新思路均已可执行，也不能把一次模型建议当作实测最优。

## 再检验 Hermes 独立决策

教学传递选择证据、计算、质疑与修正的方法，不直接给最终策略让其复述。保留一个未给答案的新场景，要求 Hermes 自行选择必要来源、计算或模拟、比较竞争解释，并给执行前提和反证条件。

通过依据：来源和数量口径正确；真实工具链与输出可对应；面对缺失/过期数据能收缩结论；区分售价参数与实际成本；赠送、优惠、库存费用不漏计或重复扣；尾价按实际成本预算且不突破原利润底线；保持生产周期、开关与写价边界。模型自评分数只作辅助。出现实质错误就记失败，纠正后另用新场景检验。

正式经验只发布经人工审核的方法和反例；保存原候选、审核、CAS manifest、实际新任务使用与撤销回执。当前价格和成本是任务事实，不写成长期常量。既有发布/撤销回执可复用，不能拿旧回执冒充新方法已验证。

## 可借鉴研究及适用边界

- [Google GA4 优惠记录](https://developers.google.com/analytics/devguides/collection/ga4/apply-discount?client_type=gtm&hl=en)：优惠码与实际折扣是不同字段；本项目仍以用户确认的后台 USD 实际优惠为准。码分类不是增量归因实验。
- [Dynamic Pricing on E-commerce Platform with Deep Reinforcement Learning: A Field Experiment](https://arxiv.org/abs/1912.02572)：研究包含离线评估与平台现场实验。本次只借鉴“候选先验证、效果另实测”的研究顺序，不照搬其模型、结果或部署自动调价。
- [Effects of $9 Price Endings on Retail Sales: Evidence from Field Experiments](https://www.kellogg.northwestern.edu/faculty/anderson_e/htm/PersonalPage_Files/Papers/Effects_of_9_Price_Endings_on_Retail_Sales.pdf)：该研究对象与 FC 金币套餐不同，不能据此宣称本项目 .99 必然增量。尾价先控制让利预算，真实利润影响仍待验证。

以上不是当前 FC 市场数据，也不授予实验、客户联系、优惠发放或生产写价权限。
