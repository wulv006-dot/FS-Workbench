# 四固定组合正式发布

用户澄清“四个素材不用同步”仅指RTTK推广素材；四个固定组合继续按原批准清单处理。RTTK已交付桌面横幅、移动端竖版、推荐位、透明组件四PNG及前端动效示例，未挂载生产。四包原图另包是此前误解产物，不替代RTTK交付。

## 原位升级与恢复源码

- PR964 / CI1854成功，main3353d7a。products.js单文件部署nav-20261109T153338Z，原publisher备份/CAS及Nginx检查通过。
- 原UI一次保存草稿28，save operation5808b688-14e0-4d21-a47d-07633c24dd70。53条旧模型和其余草稿摘要保持，新增4个真实模型后总57；三页原缺省product_keys保持。
- 真实review出现Nginx504但服务端已完成，未盲重放保存或发布。恢复缺陷与48分钟浏览器工具中断分别保留，见[恢复施工记录](REVIEW-RECOVERY.md)。
- PR965 / CI1855成功，main c4787e0。两文件恢复补丁部署nav-20261109T164013Z，仅管理服务换PID，runtime/marketing原PID保持。2源码和47保护项均读回匹配。16:43:09 UTC原producer自然恢复ready；没有手动回填旧缓存或新建producer。

## 实际审批发布

实际三页新标签私有预览均核对四包、卡图、参考价格与禁买状态，SBC仍9核心/18搭档。新审阅961caf4a…对应proposal74f77ccc-3ae8-4c21-bbd5-7105bd96135e；候选差异仅Weekly/SBC新增24条绑定，原1626条逐字保留，其中Trio原legacy12及admin12、非FC绑定均保持。

原UI人工确认后完成发布并读回：

- activity revision29 / release `campaign-preview-29`
- operationId `9fdcc5b1-5429-4d03-a999-4e9c05525a9e`
- config hash `ce4f605aaa3f6126b4250bf059c2f21ac31c74afb7eecf682129eb8fe6888dd0`
- rule hash `5411324c1cc95235b46d17b92a06ce9aaa3ac993507e7f22ec917b66269326c4`
- policy installed SHA `506a9a2235acbfb271ba2f0f10f3fbbf617bbf7a91f5243f2f685eda7c6bae6f`；原备份SHA c512f7e461c05d0d75beb7510edd0210614caea4657806d080132ccfa05405ab。

原workflow phase completed、policy receipt installed、center/public29、三工作单published29均核实。策略1626→1650，未删除或修改原绑定，三页各4包×3平台共36个现代可售映射。三页benefit_refs均为原discount6049，FCSCOUT10/10%/site266/game1327/Items保持；没有优惠券写入、社区发送、计划或Hermes开关修改。旧store的schedule_enabled/status不是宿主真实任务状态，不能据此断言实际计划启停。

## 正式取价与未验项

发布后的第一份cache29为unavailable；原producer于2026-11-09 16:49:28.445 UTC自然生成ready缓存，16:50:12 UTC读回确认release29/config一致。未手动刷新、回填旧缓存或另建producer。三平台fresh USD覆盖Weekly 7/7、SBC 31/31、Trio 7/7；四包36条原生可售映射与fresh报价逐一关联通过。

实际公开三页分别切换PS、Xbox、PC，共9组页面状态、36张包卡：均有图片、可用价格、10% OFF、划线原价和可用选择按钮；只有顶部3个平台控件，无横向溢出。逐卡以十进制核对原价×0.9、四舍五入至美分，与展示优惠价一致。SBC图片滚入视口后懒加载完成，最初未加载证据保留，最终36/36图片完整。

未增加用户原购物车行或修改既有两件PS商品，未下单或付款；新包的实际加购/付款、自然周更与成交正例不在本轮验收内。支付归因仍是共享优惠码汇总，不能拆成三页各自成交收入。

证据位于本机`.agent_runtime/weekly-console/`：`bundle-save-live-readback.json`、`bundle-three-private-previews.json`、`bundle-policy-latest-readback.json`、`review-recovery-after-warm.json`、`bundle-published-readback.json`、`bundle-published-receipt.png`、`bundle-price-natural-warm.json`、`bundle-offers-live-readback.json`、`bundle-live-36-price-initial.json`、`bundle-live-36-price-cases.json`、`bundle-live-sbc-four.png`。完整policy及回退备份仅保留服务器原目录。
