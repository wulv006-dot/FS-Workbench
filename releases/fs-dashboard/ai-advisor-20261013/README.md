# FS AI 运营顾问一期

把既有 FS 项目目录与原生区间摘要用于个人经营报告。支持全局、球类、RPG、综合组和单项目；日、周、月、季度、近七/三十日及自定义范围。目录的查询窗口不等于历史数据完整覆盖，含今天的区间标记进行中，各项目独立保存实际读取时间。

`ai_advisor.py` 在既有 range 服务内运行一个有界队列，使用独立的私有 SQLite 保存本人报告与追问。GET `/advisor` 读取配置及本人历史，GET `/advisor?id=…` 仅返回本人任务；POST `/advisor` 创建报告或基于已有快照追问。现有动态管理员列表控制生成，排队后再次校验。入队按用户和请求编号幂等，重复活动参数合并，全局至多八个活动任务，每人每日三十个。源读取复用现有缓存/采集，单项目最多一百五十秒、整单最多十五分钟。重启中断显示失败，不丢失此前结果。

金额、订单来自 Admin 主站频道；人数、比率只保留原生区间并标注原范围。Order 参考指标标注全站及 RPG 已完成范围。只合计完整同范围订单和金额，不合计跨项目去重人数/日比率。独立分销业务归属不完整、来源水位未知均明确展示。全局直接使用 MMOEXP，不与其他项目相加。没有同口径对照不推算增长或原因。

`fc_daily.py` 将原模型账本提取成共享 `bounded_model(projected, model)`，原 FC09:15 昨日日报行为保持。Advisor 与双工作区通过同一账本、同一服务端配置调用已有模型，所有功能合计每日最多三次，相同脱敏投影复用回执，调用前持久记录，不确定请求不自动重试。模型只有定性解释/待人工核对建议；本模块没有改价、派单、退款、订单写入或网络搜索。

POST `/boss-insight` 复用双工作区提供的纯校验库 `boss_insights.py`，SHA256 `0bc0ca3ccdc536a036cd22a7df9afb311bb37cd1bba5b4e7f30b7a20c99fadd6`。management 实际订单/金额由服务端按当前目录重新读取，客户输入不能替代事实；目标标注用户设定，估算利润仅是跨范围参考，不是实际利润。game-monitor 仅读取导入的公开事件摘要，不访问 URL。前端单次 POST 后用同一 job_id 从 Advisor GET 轮询；只有 completed 且结果 succeeded 才显示成功。

前端由“双工作区”任务统一发布：不可变 `advisor.html` 指向旧 `/dashboard/marketing/weekly/` 和 `index.html` 精确入口；原 weekly index 原字节作为不可变 `weekly-legacy.html`，旧 JS/CSS/历史 JSON 保留。该任务单一负责首页、导航和 Nginx；本包不改共享前端或 Nginx。新 API 必须通过现有 auth_request，覆盖客户端身份头，POST 同源、JSON、16KiB 限制。后端只能接收 loopback8931。

后端使用原 publisher 的精确五文件范围，CAS、共用锁、备份、失败回滚与仅范围服务重启保持。`fc_daily_model.py` 作为未变测试依赖与生产保护项，不发布，不写密钥。运行库、客户原单、配置秘密不进包。`source/test_*.py` 与 `check_ui.cjs` 由既有 pr-fast 最小路径映射执行。

原独立周报 timer 仅在新入口真实报告读回通过后按单独可恢复记录停用；不移除历史、单位文件，不影响营销采集、FC 定价及其它任务。回滚用实际 deploy 发布回执的 backup 与 approved-manifest SHA 执行 `release_navigation.py rollback`；数据库与模型账本保留，前端由对应统一发布器恢复。

一期验收后由用户确认再进入二期运营动作/复盘；三期联网只预留能力字段，不开新服务。真实模型、实际角色、来源覆盖与自然定时验收另记，不以离线测试代表上线。
