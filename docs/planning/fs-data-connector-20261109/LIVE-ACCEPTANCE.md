# 2026-11-09 部署与真实入口验收

本文件接续开发期 ACCEPTANCE.md；各阶段分别记实，不以公开入口通过替代登录后数据验收。

## 当前状态

- 已上线：113项命名业务读取、按模块提供参数/口径、按需展开大结果及数组展示分页；不接Hermes会话或报告生成。
- 当前生产版本：PR #938 / source593c1a2 / image8eed105b；184项Linux检查全部通过。后续章节按时间保留早期失败与发布前记录，不代表当前仍运行旧版本。
- Codex已真实授权并读到业务数据；新版模型完整显示验收见本文件末尾。
- ChatGPT尚未接通：浏览器授权回跳已通过，云端token兑换503；单次诊断有浏览器阳性对照但无token POST，根因仍未定位。DeepSeek副机和普通成员/工作区矩阵未实机验收。
- 原上游存在网站范围冲突，跨源分析须读实际filters/normalisedScope，不按请求标签假定同范围。全量数据面的剩余缺项见DATA-SOURCES.md。


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
- 用户明确收窄为“FS数据＋调取方法＋计算口径，由调用方自己的AI分析、归因与生成报告”，不连接Hermes会话/代理/报告生成。该目录收窄已在PR #933发布，详见下方版本回执。
- 额外Hermes报告技能管理器升级已停止，候选移至忽略目录，派生镜像未激活、原服务未切换。此前技能patch为blocked_not_applied，原失败回执保留；旧活跃技能并未被修改，不作为本连接器的报告执行入口或验收依赖。
- ChatGPT个人/工作区、Codex登录后查询、DeepSeek副机及普通成员权限矩阵尚未全部通过；全量读取面的剩余缺项仍见DATA-SOURCES.md。

## 数据范围调整的发布前验证（历史阶段）

部署目录沿原pr-fast新增受影响分组。连接器部署9项及旧评审精确清理5项已通过原units隔离入口，0跳过；pr-fast路径/结构/失败传播selfcheck通过。清理测试仅保留表结构与合成记录，不携带生产preview。原服务overlay测试仍依赖私有现场输入，不能由此宣称CI已覆盖。

Codex动态注册已通过实际客户端；后续授权GET携带两个完全相同resource，旧服务返回400，尚未获取令牌。修复仅将相同resource归一，异值、其它重复key及重复JSON仍拒绝；实际GET和token表单回归通过（61项60通过、1项Windows POSIX权限跳过）。此修复及数据目录收窄仍待组合CI、发布和新登录验收。

目录与方法快照：113项业务操作、36项覆盖记录、10条可选方法及6项LF规范化源SHA；移除5项会话及6项历史报告，保留活动统计与客户业务追踪。完整连接器164项：163通过，1项Windows不支持的POSIX权限检查跳过；最终目录/方法17项全部通过。此处为本地结果，不代表已上线。

知识收尾plan `KL-20d32aff139d45d64b6ac82e`，plan SHA `8b150dd0675697a276d9adeae60fe9dcb1a09ba0aa3cff036cb20188784a4055`：affected_ids与steps均为空、无冲突，不产生Notion/业务知识发布。系统Python缺Asia/Shanghai时区数据的首次运行失败，改用已有SDK虚拟环境后104项97通过、7项Linux内核lease测试跳过；未修改原知识发布器。

已停止的技能候选 `skill:094f8390` 沿原review_queue取消，request `8bba736552ee769b4da6056eced239a79fa5a55fd3a3a6fa5ef5bf7f9df0a28b` 返回completed、success=true、applied=false、rejected=true；原blocked回执字节保持，未修改技能或manager。

## 113项数据与方法版本已合并发布

PR #933：正式PR fast `42569578638`成功，source `153e066a8489ab1ae564857494609c8995253843`，合并 `17dd62eccfd6c0d267ef1fc6f226082fba70cb7c`。183实际派生镜像完整164/164通过、0跳过，26运行文件SHA吻合，方法教材仅测试挂载不打入运行载荷。镜像 `sha256:f24fe4a0cb68d057186b7f78e772e80b1f02e95c0f3a98985b4bff3d69ca96cc`，gzip SHA `2d5ce43d7aee45f8a6f14d4161703a69685c2f192f1cfc920273ee7e20ac92ad`。

187同ID `/var/backups/fs-data-connector/data-153e066/receipt.json` 为updated_anonymous_entry_verified，原服务状态保持、nginx及OAuth目录保持。准备阶段先因清单新增外层metadata而在解包前停止，改为精确验证source/image/files后继续；解包、载入和只读预检均完成，包装shell末尾CR空行返回127，未重放；之后原runner仅apply一次并验证新镜像。

ChatGPT自动发现与自动DCR仍未通过；正常UI提供的手动配置已注册一个public none客户端并成功创建FS数据插件配置（尚未授权/取数）。后续原跳转带标准ui_locales=zh-CN，被当前授权参数allowlist拒绝；正在最小兼容，未修改URL绕过或弱化FS权限。不能将配置创建成功写成连接成功。

## 真实客户端授权兼容修复的发布前证据

ChatGPT的ui_locales语言提示经有限格式/长度检查后丢弃；不改变scope、state、PKCE、redirect或身份，原AuthStore闭合参数保持。Codex真实同意提交失败时，原pending尚未过期且未消费，code/grant/token为0；无凭据Chrome原生表单复现no-referrer导致POST Origin=null，same-origin保留精确原origin。修复只改响应Referrer-Policy为same-origin，不向外部回调发送Referrer，继续拒绝null/缺失/异源Origin。

组合server/auth/portal回归65项：64通过、1项Windows POSIX权限跳过；真实ui_locales GET登录/同意路径、非法/重复提示，以及null/缺失Origin不能消费pending、随后原同源表单可成功均已覆盖。旧失败流程已停止且未发放token，不改URL或重放未知授权。

Chrome无凭据回跳对照补充：同源POST正常而form-action self阻止跨源302，callback未收到；仅加入对应callback origin后页面到达成功页且callback服务器收到请求。修复只在原validate_authorization通过后，将选中的已注册callback origin加入本次同意页form-action；查询串不入策略，CSP分隔符/通配符编码，原表单action、精确redirect、Origin和CSRF保持。最新相关66项65通过、1项Windows POSIX跳过，独立复核无阻断。

一次性自动发现诊断已结束：原三处location仅在90秒窗口记录time/method/无query URI/status，单次正常UI发现仍失败，限定日志为空。原include逐字节恢复、临时格式文件已移除，回执 `/var/backups/fs-data-connector/discovery-once-20261109/receipt.json` 为restored；不把空记录解释为ChatGPT未请求（未覆盖fallback/前置拒绝或服务端缓存）。无ACL、路由或鉴权变更，无常驻诊断。


## 浏览器授权修复已合并发布（PR #935）

最终组合head `764bb1638930165095b515f26f10a2324efbbb98`，正式CI `42573890860`成功，合并 `ad50dc2e020152d025b642956c8231189595b917`。实际169项Linux测试运行于7889a6e；运行源码5c2b5c2的26文件、6方法源及全部连接器测试与该测试版本、最终组合head逐字节一致。运行镜像 `sha256:5b08ab82517e8e9a1abf70a4ad4868a99f39d25cfe963079871e565455cca7db`；不将不同源码标签冒充同一次测试。

187固定stage `/opt/fs-release-stage/fs-connector-client-5c2b5c2`，包SHA/7成员/清单及现役镜像预检通过后仅apply一次。回执 `/var/backups/fs-data-connector/client-5c2b5c2/receipt.json` 为updated_anonymous_entry_verified；TLS及公开探测通过，原服务状态、nginx和OAuth目录保持。

ChatGPT沿已有FS数据插件重新连接，真实ui_locales授权GET已显示原账号同意页，原生提交成功回跳ChatGPT `/connector/oauth_callback`。但插件仍显示继续连接；只读数据库计数为该ChatGPT客户端code=1、redeemed=0、grant=0、token=0。浏览器授权回跳已恢复，云端令牌兑换与实际取数仍未完成，不能称ChatGPT已接通。未读取凭据值，未降低鉴权或TLS。

ChatGPT浏览器已有回调响应进一步确认：`/backend-api/aip/connectors/links/oauth/callback`返回503，`OAuth token request failed, try again later`；这条响应证明兑换失败，不证明具体网络或参数根因。

一次独立token诊断窗口已结束：浏览器授权GET 200及POST 302记录正常，同窗ChatGPT回调仍503，观察location无token POST。回执`/var/backups/fs-data-connector/token-once-20261109/receipt.json`确认原include逐字节恢复、临时格式移除。此证据定位为外部通道未定位，不能判定具体TLS/ACL/平台网络原因；未反复重试或放宽权限。


## Codex原生取数验收与响应截断修复

CLI 0.167.0-alpha.3.2沿原账号正常授权成功，浏览器callback显示Authentication complete，login退出0。两次原生exec退出0，9次FS调用、0其它工具，无Hermes调用；目录返回113操作及10方法，4项客户追踪与原Store数据SHA一致；身份覆盖subject=admin返回422。月汇总按同一2026-10范围与rangeId从202续读一次到200 available，stale=false、consistentPeriod=true，各源status=available；时间一致不自动证明跨源网站/人群口径一致。

但实际模型明确报告目录（原58232 tokens）及月summary响应被截断，所以本阶段不能宣称模型完整接收或日覆盖已验。原始SDK事件完整不等于模型上下文完整。私有验收回执SHA `c973867b2a1487109244b93077147b16f491162e1cc7c5efca68009e05ef4919`，原始明细不入Git。

针对真实截断，目录改为无参简短导航、按module读取完整参数与方法；默认10753字节，各模块不超过13315字节。月数据保留原业务值，按需展开与展示分页仍在施工及验收，不将已部署5b08镜像误称已含该改动。普通成员权限矩阵、强制会话失效、DeepSeek副机尚未实机验收。

原上游范围冲突已从实际响应核实：query.site为www.mmoexp.com，但profile.primary标all-websites且filters无网站字段，profile.supplement标all-websites且filters.site为空；shipping才为www.mmoexp.com且source[]=该站、selection.site=main。故website_scope_consistent=false；不得把三个来源当相同网站/人群合算，不能仅凭consistentPeriod宣全口径一致。本连接器保留该证据，不修改原业务聚合。

本轮响应展开本地验收：184项，183通过、1项Windows POSIX文件权限跳过；目录按module与data_path/数组展示分页覆盖，744行合成数据全部分页重组一致，祖先来源scope冲突保留。pr-fast显式纳入test_response_view，selfcheck通过。仍待Linux、组合CI、发布及模型真实读取无截断验收。


## 分块读取版本已发布（PR #938）

source `593c1a2c1c62d4ad6c8c61647180f18e7d932ff5`，正式组合head `2c7bbaaea975da92988015f930c5cc6550203224`，CI `42576784379`成功，合并 `8fbdbb0f22117e1ac7f711d169b6d63af4471087`。组合中无关周报交付未改变连接器运行、测试或6项方法源。183派生镜像实际184/184通过、0跳过，27运行文件hash一致，新增仅response_view.py；publicprobe/DCR正负向通过，测试资料未打入运行载荷。

镜像 `sha256:8eed105bffce5cf27cde1cc2aaae59dbeccb4a691e29fc70ec65ac4e903b7716`，gzip SHA `0a3bd8f9d404c246e71bb0c6a84554196c8defed5c213eeb5161a5b88ad03e78`，更新载荷SHA `2bb2d294caf12332b162a583e42ea2f2e5493630a32a0526a3c0dd9264648013`。187 stage `/opt/fs-release-stage/fs-connector-navigation-593c1a2`，校验与只读CAS预检通过后apply一次，回执 `/var/backups/fs-data-connector/navigation-593c1a2/receipt.json` 为updated_anonymous_entry_verified，原业务服务、nginx、OAuth状态保持。

实际月响应的离线展示复核：默认索引3517B、Admin metrics6228B、Order primary13989B、Shipping4922B、games首段5727B、rows前两页4214/4217B。返回分支与切片SHA均等于原始值，原响应SHA不变；Admin祖先all-websites及空site过滤完整保留。这是已取得响应的离线验证，模型无截断结论以之后真实客户端读回为准。


## 新版Codex模型可见性通过

复用原OAuth，原生exec退出0，9次既定FS只读调用完成：简短导航10753B、unified-business模块10819B、月根index3517B、Admin metrics6228B、Order primary13989B、Shipping4922B、rows前两页4214/4217B、games首页5727B。模型最终逐项确认无truncated/省略标记；正确读取rows的0→20→40/total744及games的0→20/total90。没有为了验收读取全部744行。

模型明确识别Admin/Order全站与Shipping主站及币种不同，没有把consistentPeriod当同网站、value_complete当业务全覆盖。0重试、0重新登录、0Hermes调用，不生成长月报。跨源网站冲突属于原数据问题，本次保留而未重算。

知识收尾plan `KL-03c6a2f65d6b246bcbb5a32d`，SHA `056fdc13b928695fa7776662176cbc57cd1ac574186aef11e35fd2797f47ed4d`，affected_ids/steps为空、无冲突，无知识发布、Notion写入或额外重启。

根索引中的/rangeId另补一次同arguments的原生读取，HTTP200且原生exec退出0，与首次202请求的`0653850f9be18264672bc77a22cd7a88113eacb58fe7c2f3f51038f88153b81e`一致。此后停止取数；新版真实验收合计9+1次，不更换任务或查询范围。
