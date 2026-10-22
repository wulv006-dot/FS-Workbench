# 经营看板采购毛利接入：施工验收

## 当前状态

代码、正式CI、正常合并、受控静态发布和真实wulv入口均已通过。用户最终确认收入以Admin为准、对应Order订单成本准确可用，汇率非实时造成的字段差无需追平，也不凭差额推测税费扣减。最终来源合同及Notion第21节已同步读回。此次没有新增模型调用，不能据前端发布声称Hermes已通过新模型验收。

独立PR：[331](https://github.com/wulv006-dot/FS-Workbench/pull/331)，源码`0b77cf82ad25c7c3fa2df3b3ad00e2e6e7cd414e`，起始main `f60e49660fd4e80023f0a343d6e4754eb1fbe7f3`；最终正式[CI](https://github.com/wulv006-dot/FS-Workbench/actions/runs/39705508975/job/119584490772)成功，merge `6df4d667ca629a3058c1471e5cec60fdee37eb9e`。

实际发布`nav-20261022T012809Z`（北京时间09:28:09），manifest SHA `7885f94f7832d4b064699b48bb63f90448453a9988cb7c7446043dac239100f6`。4目标及132保护共136文件真实读回一致，两个既有FS服务active；发布回执businessWorkerTimerActions=0，价格、调度与开关未变。

## 实施范围

维护源`fs_business_procurement_20261022/`；私库`releases/fs-dashboard/business-procurement-20261022/`。复用现有渠道接口denominator，包含主站推广与自然对照订单，不用推广子集冒充全盘。主站日区间优先展示CNY采购毛利、同一已完成收入/成本覆盖群体加权率、覆盖/缺口和两源读取时点。保留Admin订单/销售及原字段优先/Order补缺规则；原跨来源估算另列参考。全网站、小时和无对应成本合同的FC细分保留原参考，不冒套主站全游戏率。

不改后端、成本/收入原数据、权限、定时器、价格、原硬红线、自动化开关或流量页。三份不同的活动业务JS分别继承当前分析页8b7908、首页72d7、保留入口fd4，保留其各自折叠及后续来源修复。只发布三个新静态文件与Nginx三个精确alias所在配置，共四个目标；旧文件及URL保留。

## 已有验证

- 本地23项金额/覆盖/时间/游戏/身份与异步取消断言通过；4项精确发布边界检查通过。
- 三个版本实际指标渲染器的Chromium离线回归通过：15卡结构、USD销售/CNY毛利、覆盖、读中/拒绝/失败、负毛利、参考回退及主题状态。新增沿实际workspace折叠代码检查覆盖说明始终可见，不能被收入折叠来源区。
- 初始候选9a45e12服务器Linux27项及原publisher inspect通过，4目标/132保护。该stage不是最新候选，不用于最终发布。
- 初始正式CI因新模块未命中原Playwright准备条件而失败，未跳过；只在既有pr-fast工作流条件加入本模块，沿原固定依赖。9d516646正式CI成功；随后追加覆盖说明可见性修复为0b77cf82，最终正式CI与Linux27项/原publisher inspect均已通过，最终stage为`/opt/fs-release-stage/fs-business-procurement-0b77cf82ad25`。

## 真实入口与三边同群体复核

Chrome真实wulv入口`/dashboard/analytics/`，选择FC27、MMOEXP主站、10月15–21日：已显示CNY采购毛利、同群体率及常显覆盖说明。平台切PS时回到原标注参考估算，恢复全部平台后重新显示逐单结果；没有把全游戏率冒充PS实际率。截图和字段原值只在受控审计目录。

09:30读回时2,696完成/2,696覆盖，同群体Admin CNY收入、Order实际成本的独立Decimal合计与API四项字段精确一致；2,696单全部匹配原ES身份与USD金额，缺单/金额差为0。ES旧状态不因后来完成而倒改。随后Admin在09:32刷新出另外2笔完成单，09:35再读为2,696/2,698覆盖，2笔收入或成本待补、215笔未完成；两笔缺口未填零、不参与毛利，原后台补核继续。09:30与09:35是两个快照，不把前者全覆盖冒称后者也无缺口。

匿名401、无权限账号403、wulv200均真实核过；源全局cost.status=partial并不自动等于本批SCM，当前SCM计数0，实际本批缺口以逐单覆盖为准。两个快照共用的2,696覆盖单逐行身份/USD与独立采购合计均再次匹配。

## 接续及边界

本次已保留PR327活动`/opt/fs-hermes-fc/coins_evidence.py` SHA `c0ff06d49d8d4f8b56e62738a6b5360071202c8df5477a06da3d94939a178336`，不得回退旧版本。活动核心v12不在本次目标内。最终仅归档文档/Notion，代码上线不因文档另合并而重复发布。

所有私有PR意图、head、原失败、CI、stage、发布及读回脚本在`.agent_runtime/fc27-week-reconcile-20261022/`，服务器对应`/opt/fs-release-stage/fc27-week-reconcile-20261022/`。原09:30读回已另存`procurement-runtime-readback-0930.json`；后续`procurement-runtime-readback.json`为09:35状态，截图`procurement-live-20261022.png`；source→artifact→runtime见同目录SOURCE-MAP.json。不重放已有Git写入或未知发布。

未完成：两笔新完成单成本补核、卫星/小时/FC细分的同范围实际采购利润仍缺独立合同或覆盖，保留原参考能力；长期稳定、完整净利润及新模型迁移不由本次前端验收证明。
