# 分页运营台与正式交易验收

2026-11-09，沿原 FS 登录与原主站购物车实际验收。

## 已合并与部署

PR955，正式 PR fast1838 / run42613168877 成功，main merge `c58449272a5a5015e14fe137f9bd46832e1fe0e4`。首次1836在旧 preview-entry-browser 的 iframe 契约失败，已替换为真实新标签 DOM / 原编辑值保留 / 无持久写入断言，相关旧 iframe 契约扫描零命中，没有放宽断言或跳过检查。

代码批次 `nav-20261109T120200Z`，8个精确目标、53个保护项；备份 `/var/backups/fs-navigation-20261006/nav-20261109T120200Z`。manifest SHA256 `4c9304b35d956c0c28805a60be2a91a906f5904d307a72f34b562f6299064f19`。8文件读回全部匹配，原三服务 active，定时器动作0。

## 真实入口已通过

- 本周活动、历史、自动设置、发布确认分区可直接切换；原全页编辑入口无iframe，weekly上下文独立发布按钮隐藏。预览点击打开新标签，原编辑页保留。已发布27显示原发布回执，未新发发布请求。
- 周日12:00 Asia/Shanghai计划版本1保持开启，执行身份wulv，Hermes辅助保持允许。没有重跑模型、修改计划或发社区消息。
- 三页正式URL均可打开：`https://www.mmoexp.com/events/Weekly-Scout.html`、`https://www.mmoexp.com/events/Sbc-Companions.html`、`https://www.mmoexp.com/events/Player-Trio.html`。
- 12:03:24 UTC原报价刷新恢复ready，78模型缓存；三页当前FC参考报价分别9、81、9行，均USD。实际页面逐一切换PS/Xbox/PC，商品编号随平台正确改变，展示有效价格。三页实际显示图片正常；SBC有9核心及两处各18人的搭档选择。
- 实际原购物车：Weekly选Doku；SBC选Calafiori服务、Bastoni、Chawinga；Trio选Reuteler、Bellingham、Llorente。7条PS商品同时保留，共同码FCSCOUT10自动应用。原购物车产品金额$542.96，优惠$54.30，支付费$14.47，合计$503.13。未付款、未创建订单，7条验收商品已清除并确认恢复空购物车。页面参考价不是锁价，最终金额仍由原购物车实时确认。

版本27的center revision、公开release/config/rule hash与原发布操作 `e2bb13b1-e20c-4d61-a782-c2f771d50f90` 始终一致；policy SHA256保持 `c512f7e461c05d0d75beb7510edd0210614caea4657806d080132ccfa05405ab`。三张自动工作单关联原运行 `c478e9a6-3ca0-4a61-9fcf-3b2aa018e615`，均已发布27。没有重复发布27或安装策略。

## 预览补价增量

第一批真实验收发现普通center.preview缺少参考价，正式页面与购物车已经正常。PR956已合并，正式CI1841 / run42616494601成功，main merge `f51a2354c791bb26183048f5ca901dbc5bd059e0`。

仅补原共用私有预览入口：按完整商品/平台/规格精确匹配有效公开报价，并复用同用户、同revision/草稿摘要、未过期且策略一致的既有审阅报价。仅三个FC页面读取周更提案，损坏FC提案不会影响万圣节预览。禁止购买、原模型与发布边界保持。

增量代码批次 `nav-20261109T122600Z`，2个精确目标、59个保护项；备份 `/var/backups/fs-navigation-20261006/nav-20261109T122600Z`。manifest SHA256 `5fe922dbdc74c0ffa8370bdec90a900a2ea89da09b7b84d574dc1fb0fc8aa7aa`。两文件读回匹配，原三服务active。原报价刷新在12:27:12 UTC恢复ready/78模型，三页99行报价仍有有效USD值。

12:28–12:32 UTC实际浏览器读回：Weekly三张参考价分别$59.56、$732.58、$125.44，图片加载且购买按钮禁用；SBC待实际配置加载完成后9核心、18搭档，参考价$30.15/$11.91；Trio实际已保存球员Reuteler/Bellingham/Llorente，参考价$11.91/$223.94/$63.04。跨页加载时曾短暂读到原静态卡片，已等待实际模型和配置完成后取证，未把初始过渡画面当结果。

独立编辑器临时填写英文页面标题 `FC27 unsaved preview acceptance`，点击新标签预览，真实预览标题与参考价正确；原编辑页仍保留修改。随后仅恢复本地原值、关闭测试预览，未点保存或发布；返回运营台显示草稿修订27，最终服务器center/public均27、原policy及发布回执保持。保留浏览器中的运营台与实际已保存草稿预览，不保留未保存测试内容。

相关23项检查在183既有隔离镜像通过、0skip；最后FC/其他页面隔离分支经真实HTTP回归和最终正式Linux CI通过。没有再次加购或付款；前述原购物车证据与未变更的商务链继续适用。该加购为验收记录，不计成交或活动效果增长。

## 验证范围与未验

价格回归18项在183隔离Linux通过；运营台23项浏览器检查、原完整编辑器、新标签预览与native-page59集成检查通过；正式CI已覆盖原受影响活动检查。知识收尾104项通过，7项既有平台skip，无正式知识条目或冲突。

历史工作单仍保留商品版本差异提示，没有用推测前端补丁抹成一致；发布结果以原回执和实际公开版本独立核验。社媒/垂类资料缺口继续保留，未宣称全量外部信息已核实。首次自然周更和实际支付未验。

本地真实截图：`.agent_runtime/weekly-console/paged-live-console.jpg`；机器读回：`.agent_runtime/weekly-console/paged-live-readback.json`。截图未包含购物车个人资料或访问令牌。
