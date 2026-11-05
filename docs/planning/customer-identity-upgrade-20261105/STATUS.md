# 客户身份与日更升级：当前进度

核查时间：2026-11-05，北京时间。本文随实际结果更新；准备、合并与上线分开记录。

## 当前结论

1. **历史ES确有buyer_id/UID；全年按buyer查询仍待有效接点。** 日期+FC26游戏gid=833+buyer_id完整组合导出187行，只有1行为目标buyer；游戏筛选有效，顶层buyer未筛选。前端ES列表`/admin/order.OrderEs/esindex`当前HMAC身份返回业务401，未绕权限。用户已确认该筛选缺口可接受，优先保留历史并每天补昨日订单；日增量按日期与订单键工作，无需buyer筛选。
2. **原80人9月核对暂未发现旧方法漏计。** 两条方法各94单，付款时间与USD金额多重集一致。未直接核订单ID，不能外推全年；旧约46美元仍是收入乘毛利率估计。
3. **日更已上线并从真实页面读回，下一自然周期未验。** [PR830](https://github.com/wulv006-dot/FS-Workbench/pull/830)，合并`9f8e1b588bb18d09ce2d299bc7ccc535dc730119`，正式CI41964626604成功。Linux293项、UI日期4项通过；实际部署组合178项通过。每天补新/缺日，复用存档，不每日重拉全历史；保留原每日晨窗、周一90日修订、有界旧日轮巡/回补、按ID定向旧单修订和按需整库备份。
4. **知识已进Git，服务器新知识/新会话学习尚未验。** [PR831](https://github.com/wulv006-dot/FS-Workbench/pull/831)，合并`0885db15ec9e320e5862464fe6b3811098b9a992`，正式Linux CI41965423407成功。入口仍为`FC知识库/README.md`，取数页版本20261105-2；未将候选方法说成全年重算成功。

5. **身份补充已合并，尚未生产应用。** [PR832](https://github.com/wulv006-dot/FS-Workbench/pull/832)，合并`0be9a76887557e6aba02dd56ebd550c3de5c14d6`，正式CI41967943557成功；320项隔离回归及同CI路径326项通过。复用原ES归档，按确切订单关联buyer/UID；旧buyer冲突保留原值并标冲突，旧快照不穿透新字段。私有追踪可检查覆盖，匿名Hermes只收覆盖/冲突，不收原ID。客户主键仍是既有邮箱口径。核查时11/04档972行buyer全有效、UID565行有效；该日尚未入Store，未宣称真实关联已完成。详[身份补充实现与验收](../buyer-tracking-incremental-20261105/IDENTITY-EVIDENCE.md)。

## 发布现场与原记录

- 准备目录：`/opt/fs-release-stage/user-daily-7312aa31-v1`；来源7312aa31经上述PR合并。9个现有目标。user_query沿实际生产363f7972版本应用本次三处日更改动，不顺带启用仓库尚未上线的分页功能。
- 初次prepare发现候选包缺`candidate/`布局；在同stage按原清单SHA补齐相同字节，保留原检查记录。后续inspect曾等待Range成本采集持有的admission共享锁；只结束自有inspect，未终止业务进程或改锁。
- 业务锁自然释放后，主控沿原stage重新capture。747项仅`.curator_state`和`.usage.json`内容hash变化，owner/mode未变，9目标与其他保护项无变化。原manifest/plan保留为`*-before-dynamic-review.json`；复核两动态hash后最终manifest SHA为`006f87c82fa253c4644682685cda5df2c42fbca738cddb105678c39011d6607c`，原清单SHA为`f5b154fcb4072c50b9365a3169aaa57ea335b66aeec13fd4a5f0ad30ec45b4ae`。
- 主控完成发布`nav-20261105T052700Z`，备份`/var/backups/fs-navigation-20261006/nav-20261105T052700Z`。apply退出0，9目标SHA读回全部一致，host-runtime为all_readers_loaded，Range/Hermes均active，Range健康接口通过；未单独调用Hermes健康接口。
- Chrome真实`/dashboard/users/`可读取4917人及完整原快照，顶部已显示每日更新。旧快照仍为weekly、截至2026-11-01、旧next为11月9日；保留其原冻结信息，不声称新日数据已产出。下一自然窗口2026-11-06北京时间04:18—05:00未验。

## 后续收束

日更已完成应用及真实入口读回；次日04:18—05:00自然轮实际结果单独验收。身份补充与知识发布仍未验，本次文档收尾不部署。身份补充复用每日ES原档按准确订单关联，保留customer_id和旧快照；身份覆盖、冲突可供私有详情及追踪使用。客户去重主键/跨邮箱历史与全年价值，须待有效客户查询或足够历史映射证据后再切换，当前不冒称完成。既有按ID复核并非完整的状态变更流，不能据此取消周一90日修订或保证所有旧退款已捕获。

原始客户、订单、导出及回执保留受控`.agent_runtime`和服务器私有目录，不进入Git。具体字段、脱敏请求与计算约定见[身份核验与重算进展](../fc26-buyer-value-20261105/身份核验与重算进展.md)。
