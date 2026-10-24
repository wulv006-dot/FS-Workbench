# 原成果与工程来源

这些是已核实的最新交付基线；最终逐页接受/适配矩阵仍在P0核对。保留原设计，不据标题推断源码。

| 原任务 | 实际成果 | 版本与证据 | 拟复用位置 |
|---|---|---|---|
| 策划 FC 活动与落地页 / 01a16358-c1f9-7251-90cc-754f5ee358fa | E:\WorkBuddy\大超服务器\fc27_season2_live_20261022 | v6-main-site-integration-contract 开发包，155成员，SHA256 6dd453ae486bd6888df47020a6adf8eaf1cd08617380a8a891552badbe82fe7b；PACKAGE-RECEIPT.json匹配 | releases/fs-dashboard/campaign-analytics-20261023/app，先逐项比对，不覆盖原文件 |
| 设计 MMOEXP 限定活动页 / 01a1698a-8a89-7420-bb30-0df7f2f91274 | E:\WorkBuddy\大超服务器\mmoexp_seasonal_events_20261024 | 独立Git HEAD 5bfa19e051808d6b8033f7eb23132405abc853d4，工作区干净；V3 ZIP 77成员、SHA256 b0d8fa9f1fb03cd354d5046c120c1810dbdac808976955bb738d4baed00a9564 | 尚未导入私库；保留完整dist、主题/商品配置、素材及构建器，待公共合同稳定后接入 |

FC当前完整页面包括 Weekly-Scout.html、Sbc-Companions.html、Player-Trio.html、index.html预览壳及相关片段；保留已有核心/代做差异、固定包、平台、双语和手机体验。旧 fc27_season2_landing_20261022 为此前成果，不能替换当前维护源。

限定活动包含 dist/index.html 消费者主题体验、dist/creative-kit.html 素材页，固定区/随机揭晓/邀请演示、四主题和六游戏。V3为18套餐对应8底层商品ID的公开价格快照，折扣/邀请仍模拟；不当作实时报价或已接后端。原源码提交、部署回执和原包保留。

全成员路径/大小/SHA见 SOURCE-INVENTORY.json。参考旧模块、publisher、共享会话只作定位；现场SHA、可用动作和已部署状态须分别核定。Matchday相关已有历史文件保留但不进入本项目新增实现/验收。
