# 2026-11-09 部署与真实入口验收

本文件接续开发期 ACCEPTANCE.md；各阶段分别记实，不以公开入口通过替代登录后数据验收。

## 合并

- PR #929 已合并：`cb87b4901a81ffd313e06e4882a3b33918519ea2`，最终 PR fast `42563340661` 成功。
- 真实安装的 Codex 0.167.0-alpha.3.2 注册包含 `application_type=native`，旧 allowlist 返回400。隔离回环捕获确认后增加 native/web 兼容；原重定向、scope、grant、none 认证与未知参数检查保留。
- 修复 PR #932 已合并：`f291f5306df70b5af7dfc3c526c6e14dc33f7aa3`；测试 head `1d9ebb452772e8aa6f5dddca8fa85a9cf8382d95`，正式 CI `42566033775` 成功。Windows完整156项155通过、1项POSIX权限条件跳过，Linux由正式CI覆盖。

## 独立服务已发布

公开入口：`https://47.85.224.112/connector/mcp`。初版固定镜像 `sha256:3caead07927408c26da245d25ad3aeeef8ba795a8b0936b2e909b772b85dc152`；183隔离测试实际Python3.12.15，完整依赖与26个源码文件哈希见 deploy/connector 的回执。

187只监听127.0.0.1:8937，1CPU/768MiB/128pids；根文件系统和原知识根只读，独立OAuth目录0700、数据库0600。未修改原Python3.9、FS成员权限、FC调度或writer。

同一部署回执：`/var/backups/fs-data-connector/connector-20261109-787b5c0/receipt.json`。首次nginx reload后立即探测未过；没有重放安装，随后核当前文件哈希、实际镜像与监听，再通过完整HTTPS探测，于05:07:58Z记为 `anonymous_entry_verified_after_readback`。两项discovery、MCP匿名401及challenge、4资产、错误页CSP、未知路由404、原dashboard302均通过。

原业务服务状态保持。定时器快照差异仅为fc-ops-readonly-monitor从running变waiting、host-load-probe从waiting变running，属于自然执行状态变化；本次未写定时器配置。

Codex注册兼容修复已更新为固定镜像 `sha256:abfab1a8a0f5abed1591a0d71c66c833dba068c62ca62644708aa14639e03b59`。同ID回执 `/var/backups/fs-data-connector/dcr-1d9ebb/receipt.json` 为 `updated_anonymous_entry_verified`；全部公开探测通过、原服务状态保持，OAuth目录及nginx未改。准备阶段系统python3缺_ssl，仅预检失败；未重放解包或载入，改用现有 `/opt/python39/bin/python3 -B` 预检通过后执行一次apply。真实OAuth和业务数据验收继续进行，公开检查不代表已完成。

ChatGPT真实新增页面能打开，但自动发现未通过。正常UI重试的 `/backend-api/aip/connectors/mcp/oauth_config` 返回404，正文称服务器未实现OAuth；callback_id返回200。该反馈与公开元数据探测结果不一致，原因仍在核查，未宣称ChatGPT已接通，也未降低TLS或关闭FS鉴权。

## 用户要求删除的旧定价评审

用户先要求检查，随后明确指示“两天前了且已经正常了……删掉吧”，因此没有恢复旧模型输出或重新提交。

唯一旧cid `2e78ccd96e234b6e8573df4d97d5b11e`、turn `25e40b0a9864443f8ecf72fa65f66753`，原绑定停止，只有1轮、74条事件、0附件。按精确记录SHA和当前真实文件权限，在原锁及事务下备份后删除events74、native_conversation_runs1、turns1、conversations1；其它行、索引和sequence保持。

2026-11-09 05:17:42Z回执 `deleted_single_old_review`；备份 `/var/backups/fs-pricing-review-delete-20261109-25e40b0a9864443f8ecf72fa65f66753`，备份数据库SHA256 `ad1555156ef0622ebc40a08055d7c1fcb2b2b0e4b287806c8303b1bce11975e4`。0模型请求、0改价，未清其它UNKNOWN。

## FC自动改价只读核验

2026-11-09 13:08北京时间：pricing、cloud API和worker均active，自动开关true、mode auto、60分钟、smart计划ACTIVE，未暂停。monitor issues为空、pending/UNKNOWN=0、queued/running jobs=0。最近5自然轮全部done，4轮confirmed、1轮no_price_change。最新12:39:54完成，原operation `85809fbd-5a0e-5312-a554-11918dba2210` 为COMPLETED，Order_Admin_ALL及execution audit CONFIRMED、sync_confirmed=true、PUBLIC_CONFIRMED；下一轮计划13:36:56。

仅读现役投影、账本及已保存原回执，没有触发新轮、模型、改价或重放。旧Sol评审残留不影响这条正常自动链。本结果只代表该核验时点。

## 原服务发布与数据连接器范围

- 原服务9文件增量已发布，release `nav-20261109T051930Z`，9目标及48保护文件SHA读回一致。worker和range在原保护内以原镜像重新加载；FC定价相关PID/启动时间保持。实际worker加载的客户追踪描述允许按权限返回邮箱、UID、原订单号。详见 deploy/original-services/ACCEPTANCE.md。
- 用户明确收窄为“FS数据＋调取方法＋计算口径，由调用方自己的AI分析、归因与生成报告”，不连接Hermes会话/代理/报告生成。相关目录收窄仍在施工，不能把此范围声明当已上线。
- 额外Hermes报告技能管理器升级已停止，候选移至忽略目录，派生镜像未激活、原服务未切换。此前技能patch为blocked_not_applied，原失败回执保留；旧活跃技能并未被修改，不作为本连接器的报告执行入口或验收依赖。
- ChatGPT个人/工作区、Codex登录后查询、DeepSeek副机及普通成员权限矩阵尚未全部通过；全量读取面的剩余缺项仍见DATA-SOURCES.md。

## 数据范围调整的收尾验证（尚未合并/发布）

部署目录沿原pr-fast新增受影响分组。连接器部署9项及旧评审精确清理5项已通过原units隔离入口，0跳过；pr-fast路径/结构/失败传播selfcheck通过。清理测试仅保留表结构与合成记录，不携带生产preview。原服务overlay测试仍依赖私有现场输入，不能由此宣称CI已覆盖。

Codex动态注册已通过实际客户端；后续授权GET携带两个完全相同resource，旧服务返回400，尚未获取令牌。修复仅将相同resource归一，异值、其它重复key及重复JSON仍拒绝；实际GET和token表单回归通过（61项60通过、1项Windows POSIX权限跳过）。此修复及数据目录收窄仍待组合CI、发布和新登录验收。

目录与方法快照：113项业务操作、36项覆盖记录、10条可选方法及6项LF规范化源SHA；移除5项会话及6项历史报告，保留活动统计与客户业务追踪。完整连接器164项：163通过，1项Windows不支持的POSIX权限检查跳过；最终目录/方法17项全部通过。此处为本地结果，不代表已上线。

知识收尾plan `KL-20d32aff139d45d64b6ac82e`，plan SHA `8b150dd0675697a276d9adeae60fe9dcb1a09ba0aa3cff036cb20188784a4055`：affected_ids与steps均为空、无冲突，不产生Notion/业务知识发布。系统Python缺Asia/Shanghai时区数据的首次运行失败，改用已有SDK虚拟环境后104项97通过、7项Linux内核lease测试跳过；未修改原知识发布器。

已停止的技能候选 `skill:094f8390` 沿原review_queue取消，request `8bba736552ee769b4da6056eced239a79fa5a55fd3a3a6fa5ef5bf7f9df0a28b` 返回completed、success=true、applied=false、rejected=true；原blocked回执字节保持，未修改技能或manager。
