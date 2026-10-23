# FS 用户分析

2026-10-23后续用户已验收OK：范围名称统一“全部”，PR395/nav-20261023T072552Z已部署，1月订单补数进程已启动，1—6月新老客ES标签已完成。当前补数仍进行中，原7月完整覆盖证明保留；不得将目标下限当已齐。详JANUARY-ACCEPTANCE及交付尾部。以下旧阶段“待用户OK/不启动1月”已被本次确认取代。

2026-10-23后续：PR388/390/392已部署完整邮箱查询、字段问号与FS主题适配，最终nav-20261023T065100Z。实际本机Chrome与8目标/105保护已核；详交付尾部和SEARCH-ACCEPTANCE。原截止昨日口径及用户OK前不补1月保持。

按 [原始施工说明第17节](../../../docs/planning/fs-user-analytics-20261022/IMPLEMENTATION-SPEC.md) 完成W0后连续推进。最新PR384/mergea4580dd2、nav-20261023T024225Z已部署读回；默认期间邮箱建池，只有开始日，结束固定昨日，首单取ES新老标记，期间复购及复购后沉睡提供交叉筛选。85项隔离Linux、正式CI、四范围独立对账、已有Chrome与两工具完成，用户尚未验收OK；此前全历史模式保留辅助。当前只补到7月1日，1月回补必须等用户验收后，不能以自验替代。真实午夜仍待10月24日，详 [DELIVERY](../../../docs/planning/fs-user-analytics-20261022/DELIVERY.md)、[SOURCE-MAP](../../../docs/planning/fs-user-analytics-20261022/SOURCE-MAP.json) 与[通俗使用说明](../../../docs/planning/fs-user-analytics-20261022/USER-GUIDE.md)。

`source/` 提供独立客户事实库、可续跑日片、生命周期/成熟二购、冻结快照、权限查询、HTTP与两类Hermes工具。共享源复用现有Admin批量分页和8767会话，不重新登录或逐客户扫描。`user_runtime.py` 绑定当前IAM，`user_jobs.py` 使用原渠道采集锁并为前台采集让路，日推进不依赖新增订单。

`ui/` 复用当前FS令牌、浅暗主题和导航，展示所选期间截至昨日的阶段、复购细分与辅助全历史回看、趋势及替代表格、项目对比、成熟队列。管理员名单/详情/导出与购买沉睡时间线均冻结到同一snapshot；现有Hermes会话提交保留请求ID，未知结果核原回执后处理。

邮箱、订单及身份密钥只在服务器 `/var/lib/fs-user-analytics` 私有目录，不入Git或公开聚合。主站以外范围、终身起点及可靠退款变更游标未核，缺口按指标展示；不把窗口首见当终身新客或未成熟队列填0%。

验证：Linux/Python3.9执行 `python -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests`，JavaScript使用现有Node语法检查。正式CI沿现有 `tools/pr_fast.py` 受影响分组。

回退沿当前publisher本批备份及精确CAS，只撤本次入口、薄接线与新作业，保留私有账本/密钥/覆盖/旧快照。不得整包覆盖同期FC定价、原Hermes、渠道、归档或站点。
