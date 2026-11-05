<!-- users-current-20261029 -->
## 当前维护入口

PR653已合并8c56e2fd3e90bffc5f923ba5b173dba3d3179837，由原publisher nav-20261029T114203Z发布并读回；最终head d99754735d9fa9103e49022f62ded45725790edf、CI40866887275/141项零失败跳过，三个运行源与原审版本逐字相同。

旧单日期合同修复PR659已合并d7c48bccd24a126871857383f08f27e4c69d0518，head a2395a4e5f68b9bdfca7b738e7363453cb802155、CI40875135782/149项零失败跳过；原publisher nav-20261029T125628Z只更新user_source.py（SHA6d9ce4cefcd4c68fe07936798b1a57780e1879da77bbb812ac37e4e62f9b9244）。按原付款日用≤28天分组并经原共享适配器带render=datetime，仍只查询最多400个已选ID；最多16组、完整GET6000字节和180秒读预算，全部组验证后一次原事务。失败不改事实、不进游标；超过组预算会明确失败，不能保证每次都能完成400条。180秒是在原单请求超时基础上检查读预算，不宣称能抢断网络调用。

修复后原自然任务21:03:11至21:05:01北京时间成功结束；定向400请求/400返回/0缺失/178实际更正，当次版本1899，178条修订与实存记录对应。观察器没有手工补跑或额外业务请求。此为修复后这一自然选择批次，不冒称11:49首次0返回的相同ID集合已逐一重放；首次失败和partial原记录保留。

Admin沿现役8912 HMAC（容器8913桥），8767已退役。运行源按[当前映射](../../../docs/planning/fs-user-analytics-20261022/SOURCE-MAP.json)逐文件维护，不整包覆盖。

已按明确清单删除16个文件及4个空日期目录；实际删除文件逻辑字节44,924,296,011，文件系统可用空间由64,683,573,248变为109,607,972,864字节。

使用说明、工具合同与业务基准均沿现有文件维护；未改变生命周期、有效购买或财务口径。
<!-- /users-current-20261029 -->

# FS 用户分析

当前日更与周一自然月复核见[实施与实际状态](../../../docs/planning/buyer-tracking-incremental-20261105/IMPLEMENTATION.md)及[月复核合同](../../../docs/planning/buyer-tracking-incremental-20261105/MONTHLY-RECONCILIATION.md)：平日补昨日与真实缺日，周一复核当月及前两月；旧在途任务沿原ID和原合同完成。首次自然日更和周一窗口的验收状态按上述记录核对，不用页面可读代替自然周期。历史覆盖与各次部署事实见原交付、JANUARY-ACCEPTANCE及SEARCH-ACCEPTANCE，不从旧阶段待确认文字恢复现行限制。

## 已有部署与验收记录

2026-10-23后续用户已验收OK：范围名称统一“全部”，PR395/nav-20261023T072552Z已部署，1月订单补数进程已启动，1—6月新老客ES标签已完成。当前补数仍进行中，原7月完整覆盖证明保留；不得将目标下限当已齐。详JANUARY-ACCEPTANCE及交付尾部。以下旧阶段“待用户OK/不启动1月”已被本次确认取代。

2026-10-23后续：PR388/390/392已部署完整邮箱查询、字段问号与FS主题适配，最终nav-20261023T065100Z。实际本机Chrome与8目标/105保护已核；详交付尾部和SEARCH-ACCEPTANCE。该阶段的等待用户OK限制已由上段后续验收取代。

原施工参考：[原始施工说明第17节](../../../docs/planning/fs-user-analytics-20261022/IMPLEMENTATION-SPEC.md)（不再作为当前执行清单）。最新PR384/mergea4580dd2、nav-20261023T024225Z已部署读回；默认期间邮箱建池，只有开始日，结束固定昨日，首单取ES新老标记，期间复购及复购后沉睡提供交叉筛选。85项隔离Linux、正式CI、四范围独立对账、已有Chrome与两工具完成，该次记录时用户尚未验收OK；此前全历史模式保留辅助。该次记录时只补到7月1日；之后用户验收与1月启动以上段后续记录为准。真实午夜仍待10月24日，详 [DELIVERY](../../../docs/planning/fs-user-analytics-20261022/DELIVERY.md)、[SOURCE-MAP](../../../docs/planning/fs-user-analytics-20261022/SOURCE-MAP.json) 与[通俗使用说明](../../../docs/planning/fs-user-analytics-20261022/USER-GUIDE.md)。

`source/` 提供独立客户事实库、可续跑日片、生命周期/成熟二购、冻结快照、权限查询、HTTP与两类Hermes工具。共享源复用现役Admin直接8912 HMAC API（容器8913桥）与原批量分页，不恢复8767会话。`user_runtime.py` 绑定当前IAM，`user_jobs.py` 使用原渠道采集锁并为前台采集让路，日推进不依赖新增订单。

`ui/` 复用当前FS令牌、浅暗主题和导航，展示所选期间截至昨日的阶段、复购细分与辅助全历史回看、趋势及替代表格、项目对比、成熟队列。管理员名单/详情/导出与购买沉睡时间线均冻结到同一snapshot；现有Hermes会话提交保留请求ID，未知结果核原回执后处理。

邮箱、订单及身份密钥只在服务器 `/var/lib/fs-user-analytics` 私有目录，不入Git或公开聚合。主站以外范围、终身起点及可靠退款变更游标未核，缺口按指标展示；不把窗口首见当终身新客或未成熟队列填0%。

验证：Linux/Python3.9执行 `python -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests`，JavaScript使用现有Node语法检查。正式CI沿现有 `tools/pr_fast.py` 受影响分组。

回退沿当前publisher本批备份及精确CAS，只撤本次入口、薄接线与新作业，保留私有账本/密钥/覆盖/旧快照。不得整包覆盖同期FC定价、原Hermes、渠道、归档或站点。
