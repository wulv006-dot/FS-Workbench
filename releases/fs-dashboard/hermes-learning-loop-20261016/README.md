# FS/Hermes真实日报交付修复

Desktop保存的明确规则在新FS请求受理时发布不可变知识版本，复用判断包含版本身份；运行中与原request_id保持原版。该接线已由PR189接入，PR190保留早期阅读修正。本轮修复真实FS新生成暴露的交付问题。

维护源为source/，当前精确七文件范围见SOURCE-MAP-ACCEPTANCE.json；原SOURCE-MAP.json（九文件）与SOURCE-MAP-FOLLOWUP.json（三文件）只对应历史阶段，不重发旧包。

- 具体任务日期和交付要求进入实际Runs输入，完整冻结业务知识仍必须出现在真实system消息中；缺失拒绝。生产skip_memory=True仅隔离共享home原生通道，业务记忆并未跳过。
- 六篇官方文章逐篇提取Hermes原文中文简介，支持Markdown转义竖线、标题及版本绑定，拒绝行动计划串文。
- 完整研究默认折叠，移除历史原文显示；五个数据模块后各显示Hermes自己写的一句判断。
- 支付保留订单数和金额；趋势显示实际14日。参考利润按对应原生率估算，单日可用已核平总量；主对照缺项可单列前日辅助，不补零、不倒推成本。
- 计算器正式注册名及内部名称都能返回受控400参数错误的修正提示；鉴权、未知错误、参数/值/证据绑定保持。持久方法明确百分比分母、七日均值复算、原生率时点、事实与原因假说边界。

先线上候选真实验收，再整理同一PR、最终CI与合并。真实验收详ACTUAL-FS-ACCEPTANCE.json：2026-10-16从wulv默认昨日日报入口、原问题/daily/reuse=true生成新任务c1b96d42a95773fdaf1c26d55be0803b；14项核对通过，原六文件未改写，50份证据，request COMPLETED/task SUCCEEDED。不是Codex手工补写报告。

候选operation nav-20261016T041827Z，7目标及290保护SHA一致；发布时sourceCommit=null明确本地候选，最终入库须逐blob与已验运行文件对齐，不能倒改旧journal。锁/CAS/admission/备份/未知结果保护保留；原任务、费用、业务价格、权限与定时器不改。

直接检查：python -X utf8 -m unittest discover -s releases/fs-dashboard/hermes-learning-loop-20261016/tests（44项）。正式最终CI结果由对应commit的pr-fast记录，不将本地检查当CI。

限制：参考利润不是实际结算利润，成本缺失明示；业务原因和建议仍待负责人核验，未测得整体置信度。周/月/定价未另做付费质量验收、下一夜间自然周期未观察。FS下载按钮已点击但浏览器下载事件未确认，交付文件取自同一已生成服务器成品并逐字节核验；完整HTML像素验收未完成。截图为真实FS总览完成状态。成功apply及付费任务不可盲重放；回退只用原精确备份和当前CAS，不恢复旧数据库覆盖新会话。
