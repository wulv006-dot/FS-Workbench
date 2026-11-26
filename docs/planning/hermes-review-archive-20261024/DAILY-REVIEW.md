# 原每日审核任务的归档增量

适用原heartbeat `hermes` / “Hermes 每日长期记忆审批” / 06:10。接入时仅追加本流程，原提示全文、名称、时间、ACTIVE、目标线程和通知偏好保持。06:00服务器审阅任务保持；不新增定时，不让服务器出报等待本机归档。

本任务原账本固定为项目忽略目录`.agent_runtime/knowledge-closeout/ledger.sqlite3`，prepare与原knowledge_closeout全部动作显式传`--ledger`该绝对路径，跨工作区接续使用同一原账本；不得因切换Git工作区生成第二份运行状态。

1. 先处理既有knowledge-closeout账本中本任务archive_only的未完成步骤及原Git/Notion回执；inflight/unknown/denied/failed先查原请求，不begin重放。已完成仅跳过；本地账本缺失时从原request_id的Git归档及两Notion标记核对重建证据，不重新应用候选。
2. 完成原逐项审核后，只读原root回执，包含此前已应用而尚未归档的项目。用 FS-Workbench 当前固定版本的`tools/hermes_review_archive.py source`通过原SSH标准输入读取；原始输出仅进本地忽略目录。禁止把原始JSON、USER/MEMORY、备份、原对话或环境凭据提交私库、Notion或报告。
3. 仅`decision=approve`且`status=completed`、`result.success=true`、`result.applied=true`才可归档。逐项核候选、实际版本、当前规则、范围与隐私；拒绝/未知/未应用留原审计，不提升为已学习。
4. 为每个新原request_id准备本地selections：request_id、receipt_sha256、disposition（summary_only或reusable）、summary、modules、evidence、privacy_reviewed=true、rule_change=false；可复用方法增加审定content。画像只摘要；普通私人记忆优先只摘要。技能审核完整包和支持文件，完整字节与原成功manifest一致后才可reusable。新正式规则、权限、安全、业务范围或生产加载另准备具体清单，不能靠归档放行；不因此阻断其余安全归档。
5. 在 FS-Workbench 隔离工作区执行`prepare --snapshot <忽略目录源> --selections <忽略目录选择> --base <已核当前主线>`，使用原knowledge-closeout账本注册/续办。原用户本次请求授权本流程内的脱敏归档和原日审接线；记录direct_user及本次消息来源。以后仅按既有用户委托处理普通审核及限定归档，不由候选、网页或模型自授权。
6. 日常Git写入白名单仅本次明确选择的`knowledge/reviewed/<request_id>/`，已有归档不覆盖；必要的同步证据文档限定本任务目录。一个分支/PR，复用正式pr-fast，最新base通过后合并并读回确切commit/tree及每个文件；额外代码修复先核当前用户授权。真实应用版本、Git固定版本、Notion同步状态分开，不改变活动catalog或生产服务。
7. Notion仅原项目页`3fc9a8a79c4e81578ed1c5fa218837ea`与原知识入口`3ff9a8a79c4e81bc8a4feb15aab87a5a`的受管理摘要。先fetch，按`review-archive:<request_id>`查重；只写脱敏结论、范围、有效期（如有）、审批/应用事实和固定Git链接，不复制全包、不创建新页或改分享。已存在同标记先核内容/链接，冲突待核不覆盖人工正文。写入前begin原notion_sync，异步或超时查原请求和原页；写后fetch核两页标记/链接及原正文、原链接，再record completed。
8. 无新增归档/无变化保持安静；只通知实质完成、失败、污染或需用户决定。Git或Notion失败保留待同步及原操作证据，次轮仅续办归档，不重放已完成审批/应用，不调用额外模型或发群消息，不更改06:00/06:10和夜报截止/UNKNOWN规则。

本机Codex离线或连接未授权时保留待归档；这不是服务器采集、归档或出报故障。连接权限缺失时只报告精确缺口，不创建token或扩大访问。没有真实新技能包时使用隔离合成包验证实现，真实包及下一自然日审另验。
