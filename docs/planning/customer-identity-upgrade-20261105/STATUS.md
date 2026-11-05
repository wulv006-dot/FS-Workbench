# 客户身份与日更升级：当前进度

核查时间：2026-11-05，北京时间。本文随实际结果更新；准备、合并与上线分开记录。

## 当前结论

1. **历史ES确有buyer_id/UID；全年按buyer查询仍待有效接点。** 日期+FC26游戏gid=833+buyer_id完整组合导出187行，只有1行为目标buyer；游戏筛选有效，顶层buyer未筛选。前端ES列表`/admin/order.OrderEs/esindex`当前HMAC身份返回业务401，未绕权限。用户已确认该筛选缺口可接受，优先保留历史并每天补昨日订单；日增量按日期与订单键工作，无需buyer筛选。
2. **原80人9月核对暂未发现旧方法漏计。** 两条方法各94单，付款时间与USD金额多重集一致。未直接核订单ID，不能外推全年；旧约46美元仍是收入乘毛利率估计。
3. **日更与三自然月复核已上线，真实页面可读，自然周期未验。** PR830日更基础上，[PR834](https://github.com/wulv006-dot/FS-Workbench/pull/834)合并`2b96801d9905e635687ac67ed6d945bbaf6e109d`、CI41979275770通过；[PR835](https://github.com/wulv006-dot/FS-Workbench/pull/835)合并`bd308d1a`、CI41980053777通过。当前每日补昨日/缺日，周一按当月及前两个月全状态复核；跨日新单优先，完整月及最新日发布成功后自动清理无引用冗余件。新策略代替固定90日与每日重复旧日轮巡，不改旧在途任务原合同。生产回执与真实入口见下节；未人工触发全月采集或清理，首日11月6日04:18—05:00、首周11月9日待验。
4. **知识已进Git，服务器新知识/新会话学习尚未验。** [PR831](https://github.com/wulv006-dot/FS-Workbench/pull/831)，合并`0885db15ec9e320e5862464fe6b3811098b9a992`，正式Linux CI41965423407成功。入口仍为`FC知识库/README.md`，本轮取数页继续更新为20261105-3、方法入口为20261105-2，仅Git方法源更新，服务器冻结知识仍须单独发布与读回；未将候选方法说成全年重算成功。

5. **日更核心身份附加已应用，PR832其他生命周期/追踪工具未上线。** [PR832](https://github.com/wulv006-dot/FS-Workbench/pull/832)，合并`0be9a76887557e6aba02dd56ebd550c3de5c14d6`，正式CI41967943557成功；320项隔离回归及同CI路径326项通过。复用原ES归档，按确切订单关联buyer/UID；旧buyer冲突保留原值并标冲突，旧快照不穿透新字段。私有追踪可检查覆盖，匿名Hermes只收覆盖/冲突，不收原ID。客户主键仍是既有邮箱口径。核查时11/04档972行buyer全有效、UID565行有效；当时该日尚未入Store；本次未人工跑新日，不宣称真实关联已完成。详[身份补充实现与验收](../buyer-tracking-incremental-20261105/IDENTITY-EVIDENCE.md)。

## PR830初次发布记录（历史依据）

- 准备目录：`/opt/fs-release-stage/user-daily-7312aa31-v1`；来源7312aa31经上述PR合并。9个现有目标。user_query沿实际生产363f7972版本应用本次三处日更改动，不顺带启用仓库尚未上线的分页功能。
- 初次prepare发现候选包缺`candidate/`布局；在同stage按原清单SHA补齐相同字节，保留原检查记录。后续inspect曾等待Range成本采集持有的admission共享锁；只结束自有inspect，未终止业务进程或改锁。
- 业务锁自然释放后，主控沿原stage重新capture。747项仅`.curator_state`和`.usage.json`内容hash变化，owner/mode未变，9目标与其他保护项无变化。原manifest/plan保留为`*-before-dynamic-review.json`；复核两动态hash后最终manifest SHA为`006f87c82fa253c4644682685cda5df2c42fbca738cddb105678c39011d6607c`，原清单SHA为`f5b154fcb4072c50b9365a3169aaa57ea335b66aeec13fd4a5f0ad30ec45b4ae`。
- 主控完成发布`nav-20261105T052700Z`，备份`/var/backups/fs-navigation-20261006/nav-20261105T052700Z`。apply退出0，9目标SHA读回全部一致，host-runtime为all_readers_loaded，Range/Hermes均active，Range健康接口通过；未单独调用Hermes健康接口。
- Chrome真实`/dashboard/users/`可读取4917人及完整原快照，顶部已显示每日更新。旧快照仍为weekly、截至2026-11-01、旧next为11月9日；保留其原冻结信息，不声称新日数据已产出。下一自然窗口2026-11-06北京时间04:18—05:00未验。

## 2026-11-05月复核版本已应用

- 归档PR834：合并`2b96801d9905e635687ac67ed6d945bbaf6e109d`，正式CI41979275770通过；调度PR835：合并`bd308d1a`，正式CI41980053777通过。
- 原发布器release为`nav-20261105T062800Z`，stage为`/opt/fs-release-stage/user-monthly-bd308d1a-v1`，manifest SHA256为`6147bf6dc96910d8717f55d9e134aabdc21cfb59650b40b466cb4d2fa5117d6a`。7目标SHA读回一致，host-runtime为`all_readers_loaded`，Range/Hermes均active；P0定价PID24231未变，原timer仍active/enabled。
- 7目标为`/opt/fs-hermes-fc/`中的`user_weekly.py`、`user_customer_types.py`、`user_store.py`、`user_query.py`、`es_order_structure.py`、`channel_source.py`，及`/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js`。Store仅沿live基线加入PR832按确切订单附加buyer/UID、刷新保留identity和revision记录；query仅沿live日更基线加入归档短锁与状态字段，未带main未上线的version/member索引。
- 日更核心身份附加已上线；PR832其他生命周期/追踪工具未上线，客户主键未改为buyer，未验证全部历史关联完成。字段支持不代表已跑新日，更不代表FC26全年重算完成。
- Chrome重载真实`/dashboard/users/`可读4917人及原完整快照；旧快照仍截至11月1日。由同页导航进入`/dashboard/channel-effects/`，2973单分页、金额和成本表可读；原覆盖及新老客未提供状态保留，未手动刷新源端或触发额外采集。
- 本次未人工触发全月采集/清理。首日11月6日北京时间04:18—05:00、首周11月9日自然窗口尚未验收；真实页面可读不等于生产月清理后已验收。知识Git更新与FS冻结知识发布分开，新版知识加载及新会话应用仍未验。

## 后续收束

日更与月复核代码已应用，真实页面已读回；首日与首周自然结果分别验收，不能用测试或人工采集代替。客户主键仍为既有口径，buyer全年价值未重算；新增字段关联与整套追踪能力需逐项区分实际发布范围。新知识服务器冻结版本及新会话读取尚未验，文档Git更新不表示Hermes已学会。月复核覆盖当月及前两月，不能由此保证更早所有旧退款已捕获；真实缺口与旧在途任务恢复保留。

原始客户、订单、导出及回执保留受控`.agent_runtime`和服务器私有目录，不进入Git。具体字段、脱敏请求与计算约定见[身份核验与重算进展](../fc26-buyer-value-20261105/身份核验与重算进展.md)。
