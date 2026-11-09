# 页面与左侧入口实际部署 · 2026-11-09

用户明确批准“按清单上线剩余页面改版和左侧入口”，并要求四个素材单独交付、不做同步。上一轮仅执行清单第1、2项，误将四个素材理解为第3项固定组合。用户后续澄清指RTTK推广素材；素材仍不挂主站，固定组合按此前清单继续处理。以下发布回执与检查属于已完成的页面/入口范围，不冒充固定组合已同步。

## 发布读回

| 范围 | 实际release/备份尾缀 | 文件数 | manifest SHA256 |
|---|---|---|---|
| 页面与相关源码 | nav-20261109T145845Z | 18 | d3d735a723286519e75e27bab7b1b66c17d68419fe3966b97a4d783a1737bd38 |
| 左侧入口 | nav-20261109T145952Z | 18 | 8cab5733effc7ee59ff0aded6c7f772c0e8f29064d3825e01eedff46e5ed9c66 |

沿原publisher串行完成inspect、原锁/CAS/备份和apply；导航Nginx语法检查及reload通过。14:59 UTC现场读回36个目标与48个保护项全部匹配，nginx及原三个服务active。证据留在本机`.agent_runtime/weekly-console/{page-approved-apply,sidebar-approved-apply,page-sidebar-readback}.json`，生产备份位于`/var/backups/fs-navigation-20261006/<release>`。

活动配置仍27，公开release仍`campaign-preview-27`，原发布operationId `e2bb13b1-e20c-4d61-a782-c2f771d50f90`；config/rule/policy摘要保持。追踪enabled=true，登记revision11保持。未修改优惠券、定时任务、原商品及用户购物车。

## 实际入口检查

已登录真实浏览器可见主站活动区左侧“FC27 周更运营台”，实际点击后进入原weekly.html并成功读取配置与工作单。三页新样式已加载，顶部大优惠条隐藏，球员卡不再重复选择平台；卡图成功加载且同排图片纵坐标相同。SBC核心9项、两个搭档下拉各18项，未恢复Signature或旧固定三人组。

价格缓存首次读回为重启后的unavailable，14:57:08 UTC生成、0模型。未主动刷新或回填旧价；原producer首轮批量于15:01:39 UTC完成，15:02 UTC只读恢复ready、78模型，约272秒。Scout各平台3/3、SBC各平台27/27均有fresh USD；Trio三名球员有fresh模型报价，四旧包仍走原main_catalog，缺现代模型缓存投影不能解释为页面无价。证据`.agent_runtime/weekly-console/page-price-natural-warm.json`。

恢复后真实浏览器完成三页×PS/Xbox/PC共9组检查：每组仅3个全局平台radio、图片全部成功、无横向溢出；可购球员显示划线基价、10% OFF和优惠价，summary显示subtotal/savings/total。SBC已拥有核心显示Not charged并排除金额；另选第9核心Ligue 1 POTM September并加入SBC服务时，核心及Dembélé/Pedri均有价，原核心和owned模式随后恢复。Scout真实Review弹窗完成重新核价，正确显示60.92→54.83、节省6.09及原购物车交接说明；未点击Confirm this lineup、不新增原购物车行。证据`page-approved-nine-platform-cases.json`、`page-approved-review.png`、`page-approved-live.png`及`sidebar-approved-live.png`。

本轮浏览器尝试390px视口但DOM仍报告1920px，未将该尝试声称为新移动端验收；已有正式CI1850的响应式检查按原范围保留。

四个固定组合原WebP另复制单独交付，原字节和SHA一致，文件为LALIGA-EA-SPORTS、Lyon-Women、Barcelona、Premier-League，包`fc27-four-fixed-bundle-originals.zip`含来源摘要；RTTK三个PNG及前端动效示例沿原`fc27-rttk-promo-kit.zip`单独交付。两组均未投放或同步生产。

真实支付和自然周更本轮未执行。四个固定组合跨页同步不在本轮实际写入范围，不能将相关回归测试当作生产同步成功。
