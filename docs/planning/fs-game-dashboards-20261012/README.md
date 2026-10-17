# 七游戏经营看板与全部网站参考范围 · 2026-10-12

负责人：吴律。用户本轮指定新增七款游戏看板，并把含 ELD/G2G 参考合计替换为 Admin All。仅扩展经营读取/展示，沿用当前 Admin 主站默认、Order 利润率补充、自定义日期和身份保护；不改售价、账号、数据库、采集定时器或机器 API 客户端授权范围。GitHub/main 与生产状态以 DELIVERY.json 为准，候选不是已上线。

| 游戏 | 分类 | Admin ID | Order ID | 订单状态 |
| --- | --- | ---: | ---: | --- |
| RS | 综合游戏 | 506 | 506 | 全部状态 |
| MapleStory Classic World（冒险岛） | 综合游戏 | 1333 | 1300 | 全部状态 |
| ARC Raiders | 综合游戏 | 925 | 864 | 全部状态 |
| Dark and Darker | RPG | 589 | 588 | 已完成 |
| WoW Forever | RPG | 1367 | 1364 | 已完成 |
| 暗区突围无限 | 综合游戏 | 897 | 836 | 全部状态 |
| CoD BO7 | 综合游戏 | 859 | 838 | 全部状态 |

两套 ID 已在已登录 Admin 游戏选择器及 Order 游戏选择器/发货汇总行独立核对。RS 对应既有 `RS / 506`，不混入 Runescape/OSRS；Dark and Darker 不含 Mobile，MapleStory Classic World 不含其他冒险岛版本，BO7 不含 BO6。

游戏清单通过现有不可变快照供给“经营范围”下拉、历史序列、图表、区间原值及分组对照；新增“综合游戏 · 全部状态”，RPG 保留既有已完成口径。沿用现有 reader 和区间服务，不另建七个采集器或调度。采集器预算与原十款游戏记录保持；新游戏历史由原接口读取，缺失不补零。

参考展示范围新增 `All · 全部网站`，替换原含 ELD/G2G 项。订单数、销售额和可用客户指标直接读取 Admin 同游戏/同区间/全部网站原值，不把部分渠道相加冒充 All。标题及卡片改为“全部网站”。利润率继续标 Order 参考；预估利润为 Admin 全部网站销售额 × 同区间 Order 利润率，并明确不是后台实结利润。后台日期不一致、源缺失或网站范围未经确认时不计算估算；已验证的零值保持零。默认 MMOEXP 主站保持。

实现源 `fs_game_dashboards_20261012/source/` 与 `frontend/assets/business.js`、`shell.js`；后端运行载荷恰好 collector.py 和 admin_summary.py 两份。原源码/冻结清单/并行改动不覆盖；source→runtime、候选哈希见 evidence/game-map.json 与 evidence/candidate.json。

本地验收：9 项 Python 游戏/发布接线检查、9 项既有工作台 CAS/故障恢复检查、Node All 总额/缺失/零值/非法订单数/时间不一致/主站回归检查、实际原渲染器的七游戏切换和自定义日期/分类/All 指标/权限清空浏览器检查。浏览器与发布器测试使用合成响应/临时目录，不能称为真实后台统计、Linux发布或新游戏自然采集已验。真实后台目前仅完成 ID 与现有活动基线核对。

发布准备见 RELEASE.md；复用两个原 publisher，不新建发布入口。当前两个清单 releaseReady=false，未 merge/deploy；GitHub PR 只作可审候选。普通浏览器图片 `evidence/synthetic-board.png` 是合成预览，图中金额不是经营数据。
