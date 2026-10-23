# FS 用户分析

按 [原始施工说明第17节](../../../docs/planning/fs-user-analytics-20261022/IMPLEMENTATION-SPEC.md) 完成W0后连续推进。主程序已部署并读回，最新PR380合并8217d849/发布nav-20261023T011936Z；按用户更正默认以全部已覆盖订单邮箱建池、末购距今天分阶段，期间筛选只筛购买经历。09:28已补齐2026-07-01起历史，最早覆盖购买记观察D0，真实首购仍待证；不继续补更早历史。真实增量、付款修正和原失败片自然续跑已验，跨午夜推进待2026-10-24。见 [DELIVERY](../../../docs/planning/fs-user-analytics-20261022/DELIVERY.md)、[SOURCE-MAP](../../../docs/planning/fs-user-analytics-20261022/SOURCE-MAP.json) 和 [通俗使用说明](../../../docs/planning/fs-user-analytics-20261022/USER-GUIDE.md)。

`source/` 提供独立客户事实库、可续跑日片、生命周期/成熟二购、冻结快照、权限查询、HTTP与两类Hermes工具。共享源复用现有Admin批量分页和8767会话，不重新登录或逐客户扫描。`user_runtime.py` 绑定当前IAM，`user_jobs.py` 使用原渠道采集锁并为前台采集让路，日推进不依赖新增订单。

`ui/` 复用当前FS令牌、浅暗主题和导航，展示今天阶段、期间经历及显式历史回看、趋势及替代表格、项目对比、成熟队列。管理员名单/详情/导出与购买沉睡时间线均冻结到同一snapshot；现有Hermes会话提交保留请求ID，未知结果核原回执后处理。

邮箱、订单及身份密钥只在服务器 `/var/lib/fs-user-analytics` 私有目录，不入Git或公开聚合。主站以外范围、终身起点及可靠退款变更游标未核，缺口按指标展示；不把窗口首见当终身新客或未成熟队列填0%。

验证：Linux/Python3.9执行 `python -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests`，JavaScript使用现有Node语法检查。正式CI沿现有 `tools/pr_fast.py` 受影响分组。

回退沿当前publisher本批备份及精确CAS，只撤本次入口、薄接线与新作业，保留私有账本/密钥/覆盖/旧快照。不得整包覆盖同期FC定价、原Hermes、渠道、归档或站点。
