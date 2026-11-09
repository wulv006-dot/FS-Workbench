# FS 全量读取覆盖盘点

日期：2026-11-09。用户要求：全部现有可读取数据。状态：接口盘点，尚无连接器已接通项。

本地已实现 124 个候选操作，精确路径、参数、源码来源与缺项以 `fs_mcp_connector/catalog.json` 为准。下表仍表示未完成现网核验；不把本地代码存在标为已接通。[验收记录](ACCEPTANCE.md) 区分本地通过与真实入口。

下表从当前 main 的 `ui-system/modules/native/navigation.json` 提取全部工具入口，仅为导航事实，不证明接口或生产可用；不得将页面入口直接作为通用代理白名单。实施时逐项补充活动数据接口、参数合同、身份／权限、发布映射及真实读回。

| 模块 | 页面入口 | 连接器状态 |
| --- | --- | --- |
| 活动转化分析（campaign-analytics） | `/dashboard/analytics/campaigns/analytics/` | 待接口及权限核验 |
| 用户分析（user-analytics） | `/dashboard/users/` | 待接口及权限核验 |
| FC27 SBC 上架工具（fc27-sbc） | `/dashboard/fc27-sbc/` | 待接口及权限核验 |
| 渠道效果看板（channel-effects） | `/dashboard/channel-effects/` | 待接口及权限核验 |
| 数据分析工具（data-analysis-tools） | `/dashboard/data-tools/` | 待接口及权限核验 |
| 数据看板（unified-business） | `/dashboard/analytics/?mode=business` | 待接口及权限核验 |
| 项目工作任务台（tasks） | `/dashboard/tasks/` | 待接口及权限核验 |
| FC27 金币控制台（coins） | `/dashboard/fc27-coins.html` | 待接口及权限核验 |
| FC27 运营看板（ops） | `/s/wulv/fc27-ops/` | 待接口及权限核验 |
| FC27 球员维护（players） | `/tools/fc27-players/` | 待接口及权限核验 |
| FC27 收藏馆调价（gallery） | `/tools/fc27-gallery/` | 待接口及权限核验 |
| MLB 新卡工作台（mlb） | `/mlb/` | 待接口及权限核验 |
| NBA2K 自动改价台（nba） | `/nba2k27/` | 待接口及权限核验 |
| RPG 游戏改价系统（d4） | `/d4/` | 待接口及权限核验 |
| 部门手册（docs） | `/docs/` | 待接口及权限核验 |
| 团队工具目录（sites） | `/s/` | 待接口及权限核验 |
| 现有部署工作台（deploy） | `/deploy/` | 待接口及权限核验 |
| 运营报告（weekly） | `/dashboard/fs-home/brain/index.html?report_kind=weekly#reports` | 待接口及权限核验 |
| Madden 金币看板（madden） | `/dashboard/madden27-coins.html` | 待接口及权限核验 |
| FC26 库存与交付（历史工具）（odds） | `/s/wulv/fc-odds/` | 待接口及权限核验 |
| 游戏监控台（game-monitor） | `/dashboard/game-monitor/` | 待接口及权限核验 |
| 经营管理台（management） | `/dashboard/management/` | 待接口及权限核验 |
| 智体决策报告（brain） | `/dashboard/fs-home/brain/index.html` | 待接口及权限核验 |
| FC27 捆绑包改价（fc27-bundles） | `/dashboard/modules/sports/bundles/` | 待接口及权限核验 |
| G2G 自动改价（g2g） | `/g2g/` | 待接口及权限核验 |
| 销售部系统（sales） | `/sales/` | 待接口及权限核验 |
| Discord 机器人控制台（bot-console） | `/bots/` | 待接口及权限核验 |
| 持续对话（hermes-conversation） | `/dashboard/fs-home/hermes/conversation/` | 待接口及权限核验 |
| 智体客单追踪（customer-tracking） | `/dashboard/fs-home/hermes/customer-tracking/` | 待接口及权限核验 |
| FC27 进化商品改价（fc27-evolutions） | `/dashboard/fc27-evolutions/` | 待接口及权限核验 |
| 商品编辑与预览（campaign-products） | `/dashboard/analytics/campaigns/analytics/products.html` | 待接口及权限核验 |
| 营销系统（marketing） | `/dashboard/modules/marketing/` | 待接口及权限核验 |
| SEO监控台（seo） | `/dashboard/analytics/seo/` | 待接口及权限核验 |

## 不能遗漏的非导航数据

- 知识库、正式业务规则与已有归档／报告：按原访问范围提供检索和读取，保留版本及来源。
- Google Ads、GA4、GSC、流量、渠道：从对应经营／营销模块继续展开，不能因没有独立导航项而遗漏。
- 活动、优惠券、商品、成本、竞品、汇率、执行记录：展开各模块已有读取接口；读取执行状态不触发重试、对账写入或新采集。
- 账号与权限的已有可读信息按原管理权限单独核查；凭据材料不属于业务数据导出。
- 私有会话、附件及追踪对象按原 owner/session/private 边界处理，不以模块访问权代替对象所有权。

## 全量验收规则

每个现役读取面须有对应的连接器操作及实际读取证据，或记录客观不可用原因与影响；存在未接通现役面时只能报告部分交付。已退役和历史页面须有退役证据，不能凭目录日期排除。新发现的现役面继续加入本清单，不把当前导航列表当作完整数据合同。

连接器不增加改价、发券、发布、成员改权等业务写入操作；原系统这些能力保持。查询内部缓存／审计等既有必要持久化按原模块合同处理，不将所有 POST 误判为业务写入，也不将所有 GET 默认视为无副作用。
