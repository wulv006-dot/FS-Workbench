# 本地候选验证（2026-11-01）

范围：04 V2.1 任务2/6/10的首个候选包和任务1只读清单工具；11项整体未完成。所有测试是合成/本地，无客户事实、真实源、模型或生产请求。
环境：Windows，Python3.14.7，SQLite3.50.4。任务目录单独安装tzdata2026.6；未改生产依赖。

| 命令（仓库根） | 结果 | 限制 |
|---|---|---|
| python -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests -p test_missing_store.py -v | 5通过 | 冷启动/运行中缺库、key保护、空/错误schema、HTTP503；未测Linux provisioning与宿主build异常映射 |
| python -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests -p test_revision_range.py -v | 5通过 | 合成SQLite，Store.__new__只用于跳过无关POSIX初始化；不声称Linux权限检查已通过 |
| python -m unittest discover -s releases/fs-dashboard/tiered-data-access-20261101/tests -v | 8通过 | 6日期合同+2只读清单；没有UI/API/Hermes接线 |
| python -X utf8 -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests -v | 175项，137 errors，0 failures，未通过 | 122 private_directory_permissions、15 fcntl缺失（含3个模块导入失败）；不关闭检查或模拟Linux权限来造绿 |
| python -m compileall -q 两受影响source包；git diff --check | 通过 | 语法/空白，不代替集成验收 |

首轮默认GBK的整套回归另有89个文本解码错误；已用-X utf8重跑，剩余错误如表，旧日志不作为最终依据。首次时区缺失和fixture连接未关闭错误已修正并重跑相关测试。

性能证据：查询固定2026-10-01到2026-11-01（半开）；在相同1条窗内数据之外，增加20,000当前行+20,000历史版本行。SQLite progress handler逐VM步统计：165→165；两个查询计划分别SEARCH purchase_time和user_version_date。此实验不能外推11GB生产库或证明迁移空间收益；更多同窗版本增长会有真实成本。

历史等价反例：10月→9月和9月→10月、退款/invalid→valid、客户/站点/游戏变更、目标revision边界、未完成/过期索引回旧读、事务故障回滚。未运行真实冻结recipe批量shadow、生产SQLite3.7兼容、百万行/RSS/WAL/锁峰值。

最终复跑记录见任务目录final-checks.log（18项）；完整既有回归失败日志见users-regression-utf8.log。pr-fast完整分组在该Windows环境不能通过相同POSIX依赖；新增独立包CI注册仍待审查，未声称CI通过。
