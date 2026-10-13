# Advisor 一期正式激活补丁

独立于 PR88 冻结包；PR88 已合并，尚未写入生产。本激活包以已验证 FC 日报线上版本为 CAS 基线，保留旧包和历史哈希。

实际 Admin 摘要在外层提供 USD，内部仅金额字段携带单位。本补丁按已校验的外层合同判断缺省币种，明确的不同币种仍拒绝；真实 FC27 昨日源验证后补了回归。Admin订单/金额是后台统计原值，与FC支付明细日报的净额口径分开显示。

用户在双模块任务 01a1345d-4b90-7602-83f5-fb7fbd4f0531 的实际 userMessage 01a1348c-9fef-7873-b96b-b04903e0893c 回答：『上限我可以放宽。情报、经营 每天一次；费用不用顾虑我会承担，人工AI解读可以放开去做』。已通过本机任务读取核验，不仅依据助手转述。取消测试固定每日三次；FS_MODEL_DAILY_LIMIT 可选配置，0（默认）不设日次数限制，正整数为共享上限。跨进程 provider.lock 保持一次并发；相同投影复用真实回执，unknown 不重试，busy 未发送。没有充值/购买/新凭据。

共用调用入口：`DailyReports(None, '/var/lib/fs-business-ranges/fc-daily').bounded_model(projected, callback)`。外部服务器自动模块不要 start/tick/enqueue FC 调度器。`ai_advisor_model.request_model(messages, projected, validator, *, max_tokens=220, timeout=40)` 复用既有服务端密钥路径和北京百炼模型，最大6000tokens、120秒、输入/输出96KiB；定时任务严格校验输出并持久化自己的调度状态。游戏和经营的独立自动任务由双模块负责人实现，不在本发布中假称上线。

前端窗口因双模块需求扩展交回本任务。本包通过原native publisher发布17个不可变资产和原3个可变引用：只新增Advisor、旧weekly原字节归档，保留已有15个资产功能。原weekly入口两个exact location指新Advisor，legacy-index指旧归档；新advisor.json exact route使用原auth_request并覆盖浏览器身份头，同源和现有管理员权限约束POST。不新增boss公网路由、双模块卡片，不动radar配置。旧weekly public文件保留。

后端仍仅五文件、仅重启原范围服务。前端CAS、共享锁、备份、nginx -t失败回滚保留。必须后端读回通过后再前端发布；旧周报timer仅在新入口真实报告验收后单独可恢复停用。

部署、真实模型回执、权限、自然定时、回滚备份另记于最终验收；此文件不代表上线已发生。
