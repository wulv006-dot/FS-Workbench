# 流量匹配明细候选（2026-10-17）

本地候选，未发布。FC27 GSC 搜索词/页面汇总使用全部已返回匹配；明细仅展示其中 Top20，默认3行摘要，可展开。原全站Top及D4/Aion专属范围不变。经营关联保留会员宏观，其他三表默认3行、展开当前返回记录。

缓存消费者只对同rule旧投影缺rows的GSC两维补充显示合同：只读既有原始数据库，同日期、同collected_at、相同聚合及匹配数才补投影；不写缓存、不触发采集。缺少原件或快照漂移保持旧汇总并明确缺明细，不从全站Top推算。

发布对象为两项后端Python文件及下一immutable UI的google.js；UI由原最小发布构建/桥生成，不能直接覆盖当前历史资产。现场旧SHA见SOURCE-MAP；正式发布前仍须重核基线、冻结head与保护对象。

验证：`python -B -X utf8 releases/fs-dashboard/traffic-content-details-20261017/tests/test_content_details.py`（3项）；`node releases/fs-dashboard/traffic-content-details-20261017/tests/check_content.cjs`；既有details14项通过。私有目录browser-content-details.cjs实际shadow合成测试通过，覆盖两维/三表/会员/旧缓存/缺失/空/失败及无新增网络请求。浅色/暗色/390px截图为合成数据，不代表线上验收。
