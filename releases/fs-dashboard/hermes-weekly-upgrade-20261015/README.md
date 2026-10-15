# Hermes经营周报：数据、方法与阅读版升级

恢复行为：周报稳定读取已有每日销售/订单、当前未结池和脱敏问题原因，并新增消费准确周的现有营销汇总。以简明中文摘要、游戏情报卡、地区与获客分析、带建议角色和日期的行动呈现。

- data/：固定只读MMOEXP营销发布快照；GA4/GSC国家、GA4来源媒介、MMOEXP Ads账户/系列。无新采集、SQL或任意文件入口。当前池与报告期新增分开。
- methods/source/：哈希固定0.9.2周报方法，经营周报才注入；独立pricing方法与权限不变。新报告要求既有fs-report-v2与中文intel卡，完整研究正文保留。
- visual/：改进经营阅读版及旧Markdown兼容；完整原稿/冻结证据不改。来源元数据及图表原值可查；不把所有证据JSON嵌入阅读HTML。
- publisher/：沿原发布器固定目标、锁、CAS、备份、任务静默及回退；prepare仅准备隔离目录，不替换活动源。

实用质量：约90%可验证/覆盖为目标，允许小误差和局部未核平；核心依据足够就给合理判断和复查条件，不把目标写为已测统计准确率。

检查：data/test_weekly_data.py、methods/test_weekly_bundle.py、visual/test_visual.py、tests/test_weekly_release.py和test_prepare.py。pr-fast注册同一增量，包含原经营renderer与独立pricing消费者回归。样本全部合成，不含实际客户、报告、画像或凭据。

边界：全站流量为背景，未建立FC专属归因；Ads无真实国家分项，系列名不代表定向。所有行动仅建议，不执行改价、投放、订单处理，不增定时。真实生成与生产验收见本地DELIVERY，不用合成测试冒认。
