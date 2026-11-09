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

第一批真实验收发现普通center.preview缺少参考价，正式页面与购物车已经正常。后续仅补原共用私有预览入口：按完整商品/平台/规格精确匹配有效公开报价，并复用同用户、同revision/草稿摘要、未过期且策略一致的既有审阅报价。禁止购买、原模型与发布边界保持。代码与本地验收不能代替该增量部署后的浏览器读回，最终结果另记。

## 验证范围与未验

价格回归18项在183隔离Linux通过；运营台23项浏览器检查、原完整编辑器、新标签预览与native-page59集成检查通过；正式CI已覆盖原受影响活动检查。知识收尾104项通过，7项既有平台skip，无正式知识条目或冲突。

历史工作单仍保留商品版本差异提示，没有用推测前端补丁抹成一致；发布结果以原回执和实际公开版本独立核验。社媒/垂类资料缺口继续保留，未宣称全量外部信息已核实。首次自然周更和实际支付未验。

本地真实截图：`.agent_runtime/weekly-console/paged-live-console.jpg`；机器读回：`.agent_runtime/weekly-console/paged-live-readback.json`。截图未包含购物车个人资料或访问令牌。
