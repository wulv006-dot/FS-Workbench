# RS经营看板适配交付（2026-10-24）

已在原经营看板发布RS适配，并用原wulv登录入口读回验证。网站与类目为常用筛选；区服在“更多筛选”，默认全部。FC保持原功能，本次未迁移。

入口：[RS经营分析](https://47.85.224.112/dashboard/analytics/?mode=business&b_profile=RS&b_grain=day&b_range=yesterday&b_rs_site=rsorders&b_rs_category=all&b_rs_server=all)。方案见[PLAN](PLAN.md)，利润字段见[SHIPPING-CONTRACT](SHIPPING-CONTRACT.md)。

## 最终行为与口径

- 网站：全部、RSOrders、RSMalls、RSFast、MMOEXP；类目：全部、货币、代练包、物品。低频区服保留全部、Runescape 3、Old School。筛选随URL保存，刷新恢复；缓存、归档、迟到结果及逐日利润都带范围身份。
- 订单、USD销售、销售趋势、国家、支付方式与设备沿Admin原生同范围；低频指定区服按完整明细查询，不能用上游忽略的aid伪造汇总。新客/复购等无法确认区服定义的指标保留明确参考范围。
- 用户补充指定的利润准确源为Order“统计管理→发货统计”。人民币利润金额=该页销售总额−采购总额，利润率用原生率，逐日曲线同源。交易时间与Admin付款时间分列，不跨来源推算美元利润，不称净利润。有效零不丢失，零销售利润率不适用；失败不补零，负值保留。

## Git、正式检查与原发布器

| 阶段 | PR / 合并SHA | 正式CI |
|---|---|---|
| 首版适配 | [429](https://github.com/wulv006-dot/FS-Workbench/pull/429) / 86345f45dd96156a7f810889f13bda369fbfa50a | run40080309917，通过 |
| 归档范围修复 | [430](https://github.com/wulv006-dot/FS-Workbench/pull/430) / f0676ee290d6bce895056e38ceb2a76d8ce57e3e | run40080982397，通过 |
| 发货统计利润 | [431](https://github.com/wulv006-dot/FS-Workbench/pull/431) / 48044458dbad293f5d1b9ff4af0534244c4bc0a7 | run40082258060，通过 |
| 有界就绪等待 | [432](https://github.com/wulv006-dot/FS-Workbench/pull/432) / ede67f618850d7b659ef68944dc5cfc7376e0e86 | run40082767646，head492081c5c2dd133527f5564fbb7cd0a4c946eaf8，通过 |

首版及归档修复分别13/5目标；最终利润增量11目标，版本`rs-shipping-20261024-3318ca1016cf`，发布ID`nav-20261024T094000Z`。manifest SHA `e027ac88931d496a8fc28fa28068ed9990b917ba144d6a36557d627737b76153`；最终包SHA `b6f703ee94b1d8fa98cbd98057e18eb648cf87346f233ff87383040b14a07e2d`。

原publisher完成CAS、准入、锁、备份、原子写入、健康及nginx检查。最终11目标SHA全部匹配，64保护文件无漂移；经营查询、Hermes、auth服务active，/health ok=true、用户分析ready，匿名range仍401。原publisher journal的`applied-awaiting-actual-http-role-acceptance`保留；本文件单独补真实入口验收，不改写原回执。

活动维护源码统一在`rs_business_adapter_20261024/source/`；14个最终活动目标逐文件映射见[ACTIVE-SOURCE-MAP](ACTIVE-SOURCE-MAP.json)。首版、归档修复与发货统计映射按顺序接续，旧不可变资产保留；不以旧目录整包覆盖。server187清单未收录这些源码，无副本刷新对象。

## 已通过的验证

- 56项Python口径/参数/缓存/归档/发布检查；原采购利润23项、原三版本指标DOM回归；真实活动HTML/生命周期/主题的离线浏览器检查，含新人民币卡片、每日曲线、网站/类目、有效零、快速切换、晚响应、明暗、390宽度及FC隔离。全部模拟值明确标注，未冒充经营数据。
- 原共享Admin只读核对8组网站/类目组合及1个区服明细；趋势单量/美元总额与原生汇总核平。原生aid汇总无效及关联重复行诊断保留，只有完整相同记录才去重，冲突失败。
- 原共享Order发货统计4组真实读取；2026-10-23 00:00至10-24 00:00的RSOrders：¥24,700.02销售、¥18,961.09采购、¥5,738.93利润、23.23%，61订单/70交易，与用户截图一致；物品¥1,022.60/20.84%，全部网站¥7,996.89/23.50%，MMOEXP有效零。
- 真实原wulv页面：RSOrders全部类目显示60付款单/$3,441.70、¥5,738.93/23.23%；逐日利润同sourceContract、同网站/类目/区服，1日已提供；Admin销售趋势21个小时桶。切物品显示5付款单/$749.97、¥1,022.60/20.84%，趋势随选项更新；切MMOEXP显示0/$0/¥0，率为“不适用（无销售额）”。加载过程中清空上一范围值。

本机忽略的真实回执：`rs_business_adapter_20261024/baseline/live-final-rsorders.json`、`runtime-final-readback.json`；最终真实页面截图在同目录evidence下，模拟图保留原名不混用。常用日期与数字是本次历史窗口，不代表未来实时结果。

## 原失败保留与未验范围

早期远端提交被自动审批拒绝，用户随后明确回复“允许”，授权提交/CI/合并/发布，拒绝仅保留历史。首轮CI缺浏览器安装步骤失败后补进既有pr-fast安装分支，未放宽检查。

归档修复最初两次被原collector.lock拦在写入前；核到原定时采集进程1205，未停止该任务，待自然完成后发布。利润增量第一次`nav-20261024T093500Z`健康检查失败并完整回退，11目标已核原SHA，原失败及备份保持。后续仅增加同进程有界就绪等待，断言/准入/回退不变，最终已通过；具体首次耗时原因未证实。详见[PUBLISH-READINESS](PUBLISH-READINESS.md)。

尚未观察长期自然缓存到期、多日经营收益或全部权限角色；新数据源不是完整财务净利润核算。小时选择支持区间卡片和销售趋势，利润历史曲线沿原完整北京自然日；FC相似改造未实施。未新增模型、定时器、业务写入、登录或长期跟踪。

本地重跑：`python -B -m unittest discover -s rs_business_adapter_20261024/tests -p test_*.py`，及既有Node/Playwright的`tests/test_rs_projection.cjs`、`test_procurement.cjs`、`test_views.cjs`、`test_browser.cjs`。不需新依赖。已发布ID不可重放；需修改时重取当前现场与最新Git、生成新清单，沿原CAS发布器，不重复业务请求。
