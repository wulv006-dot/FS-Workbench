# Hermes运行接线、部署与使用验收工作包

2026-11-01用户明确安排Business部署和测试，Personal最终审核功能、视觉规范及人类操作便利性。沿唯一主方案阶段1/2，不另造路线。Business A为本包唯一施工/发布执行者；Personal负责总控、合并、最终审核和必要B接口修复，不并行发布。现阶段模型保留DeepSeek，其他通道仅验证。

## 当前起点与终点

PR711已merge88ac65d9337f20da71864ff48ebebc5284b89963，reviewed7275612c/basecc33dbcb独审通过、project-only P2解决，LinuxCore125/user-analytics253及ready重跑成功。本包开工已fetch/ff main为fc77dd1b8743c8c54dd6c943fffa0fadfa6f30a2，工作区干净；其新增为其他活动分析，不覆盖其成果。

上述不代表本轮已部署。Business已回交最小现场只读活动源/路径/版本、服务、入口和发布器核验，并形成完整候选；历史SOURCE-MAP/manifest只作定位，不直接重放或从旧快照覆盖当前活动文件。

首要终点：原授权人员在实际FS入口用DeepSeek完成小CSV/XLSX上传、显式绑定、分页读取、已支持确定性修订、真实可打开产物下载和新turn显式追问，刷新/unknown原ID/停止/权限围栏有效，界面清楚可操作。冻结调查接入实际任务时必须有host真实身份/scope和显式检查点；缺scope/接口/额度的链明示未完成，不能只传py文件或HTTP200就称功能生效。

不把任意计算、全部格式、完整持续目标/自动到期、团队派发或全套阶段2作为首包前置。未接通入口诚实不可用，不做假按钮/假数据；不宣称阶段1/2整体完成。

## 单一修改者与发布方式

- A继续独占conversation前端/files/http/store、A2 context、core conversation_service及相关测试，复用现有UI。
- 必要共享接点候选：core source/conversation_service.py、strategy source/runs_contract.py/proxy_gateway.py、fc-review-channel-20261026/source/proxy_gateway.py、实际活动controller与conversation/core deploy装配封装。候选不自动等于活动源。
- A先回精确路径/目标/唯一修改者；Personal登记本包共享controller/schema/allowlist/manifest的唯一A维护并确认知悉后改依赖，不两端并改，不用DB迁移/IAM/安全配置绕接线。
- B1/B2/material_evidence/conversation_file_tools语义仍由Personal B维护，A消费接口，有缺口回主控限定修复，不复制或直接并改B源。
- tools/pr_fast.py及总主文件/进度仍由Personal维护。A只给精确CI缺口；部署附录放hermes-conversation-20261018/DEPLOYMENT-ACCEPTANCE.md，不改全局主文件。

必要工程在A原独立分支形成完整候选，Personal正常merge一个集成PR；Business Sol High独立worktree审查覆盖最新SHA，必要CI/无冲突后主控按授权合并，A再部署与测试。沿原publisher和锁/CAS/备份/回退，不新增第二发布链或重放旧stage。

### 2026-11-01现场接点登记

根据A回交的现场哈希及Git精确匹配，本包以下路径唯一修改者登记为Business A；Personal不并改这些接点。此登记不代表代码、发布或验收已完成。

| 精确路径 | 本包允许的增量与保留边界 |
|---|---|
| `releases/fc-coins/fc-pricing-v3-20261026/source/conversation_service.py` | 接入已交付附件能力；保留当前FC接点 |
| `releases/fc-coins/fc-pricing-v3-20261026/source/conversation_http.py` | 消费A文件HTTP接口；保留现行鉴权和FC接点 |
| `releases/fc-coins/fc-pricing-v2-20261022/source/runs_contract.py` | 在当前活动allowlist追加必要B文件名，不扩大工具/业务权限 |
| `releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py` | 用当前main已有B增量对活动基线制作精确补丁，不整体覆盖 |
| `releases/fs-dashboard/hermes-conversation-20261018/deploy/runtime_prepare.py`、`deploy/runtime_release.py`及对应新增测试 | 作为既有publisher的本包装配封装，复用原锁/CAS/备份/回读，不改冻结base、不另建发布链；测试精确路径随候选回报 |
| 生产目标 `/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf` | 仅两个已定位会话location的body上限定向调整，以支持HTTP严格不超过10MiB的上传；其余路由、鉴权、原0600权限保持。prepare只生成候选，发布前固定完整manifest/hash并按原发布锁/CAS实施 |

现场`controller.py`、`fs_evidence.py`及`range_api.py`本包不改不部署，只以现场完整SHA保护；不以旧Git快照覆盖。A2尚无可信host scope接入来源，保持不可用。实际业务HTTP解释器为`/opt/python39/bin/python3.9`，A已核其openpyxl/et_xmlfile存在，无安装需求；worker只读挂载与profile/memories/skills边界保持。

生产源码导出已由13项缩至1项：9项可复用精确Git字节，上述3项不改。仅会话`/var/www/dashboard/fs-home/hermes/conversation/index.html`未匹配且确需保留现行导航，5776字节，SHA256 `3d79a5642f1517a8c1e414702c2b7491dc0ff4ed079c7d09895a3b1251045a24`。目标为A本机ignored `.agent_runtime/runtime-20261101/live/frontend/index.html`，原始导出不入Git、不含配置/凭据/DB/业务数据。此前13项SCP被自动审批以未明确授权生产源码导出为由拒绝，命令未执行；2026-11-01用户针对上述精确文件/大小/hash/目标明确回复“授权仅此文件按上述范围复制”，主控已通知A可提交正常工具审核。只授权这一项，复制实际执行及哈希核对结果仍待A回报；再次拒绝须停止，不等价绕过。用户已选择在现有页用原账号登录，尚待完成回复，正常FS登录和真实会话/视觉验收仍未完成，不自动操作用户正在登录的页面、不提取凭据。

A已确认对应新增测试精确路径为`releases/fs-dashboard/hermes-conversation-20261018/deploy/test_runtime_materials.py`，同属A唯一维护。现有pr-fast conversation deploy使用显式列表，不自动discover；Personal仅在该列表追加`test_runtime_materials`，保留原HTTP/release及Node入口。测试模块尚待A固定候选合入，当前不将驱动接线或A回报的本地模拟通过宣称为本分支完整验收；合入后核实际执行数量及LinuxCI，目录fsync/POSIX权限、生产回退与真实模型仍分别取证。

### 固定候选集成

A完整候选为`4648d7aee6aefe08294aae77f4c954809009d60d`，父基线`e18a5b71f88c7831d291e155e3b3390d637354fc`，11个路径。主控开工fetch后main仍为`fc77dd1b8743c8c54dd6c943fffa0fadfa6f30a2`，正常merge候选为`7bab422b96bf0d9929ea2cd1828fb559682a0edc`，无冲突；相对A固定候选只差主控授权记录，运行代码/测试相同。新增测试已随候选合入，不再是仅有驱动登记。

复用A在相同运行代码及原pr-fast runner的证据：conversation30项、deploy16项均通过且0skip，另两项FC定价route/独立队列通过，原Node DOM/fetch与两套本地Chromium通过；后者使用合成响应，并非部署版验收。主控diff检查通过，代码/发布封装核心自查未见当前阻断项，仍待最新完整head独审与必要CI，不代替独审。知识closeout旧91项30错误保留未完成，无新业务规则或知识发布。

单HTML正常工具审核及复制已成功；A核源/本地均5776字节、授权SHA一致、原件ignored且未入Git。候选HTML SHA为`6ee4a6f718e1759235648190f02c5d1c79332afa830baaa7893017048d70f604`，移除新增661字节附件块后复原活动原件。用户在A线程实际回复“已登录”，A只读核验auth200/admin及conversations200/items形状，认证不再阻塞；未读取历史聊天、Cookie或密码，未触发模型。

候选pack共12个源码/静态payload，第13目标Nginx须新现场prepare派生。候选payload descriptor SHA `438c69e157c3f287408d22d2d553dafd98dfdb24dc5a19ed2d872ec7364bd468`仅对应A候选，不是生产manifest；合并后以最终合并SHA重新pack、新现场prepare并固定manifest，再按原publisher发布。实际Linux模式/fsync/compose imports、生产manifest/备份、真实DeepSeek/provider用量费用、部署视觉/缩放/停止/真实第二身份、A2 hostscope仍未验。验收后沿主方案继续，不逐阶段重复索取同范围授权。

## 当前授权边界

### 首次发布失败与必要修复接点

A回报最终main `4077536449a3dcaa8871623989a15be3ead1552b`新pack SHA `910b31d1989cf28c77bdf1fa033fceccfce65689988874dde596ff22d43f756a`；现场stage `/var/tmp/fs-hermes-materials-40775364-20261031T182821Z/stage`，manifest SHA `2e250d648631b09c911d909f3db0fb0216d96e06667b8a141e36504eb1c5505c`的inspect通过。但apply写13目标后worker健康读回60秒失败，原publisher回退13目标，备份 `/var/backups/fs-navigation-20261006/nav-20261031T182821Z`，journal为rolled-back；旧worker启动也失败。当前回执为worker failed、range inactive、Nginx active且未reload，发布与服务恢复均不能记通过。

先由唯一发布者A在原锁/准入/provider围栏下核beforeSHA、49保护文件和journal，再沿原publisher限定恢复旧range基础HTTP；不重apply材料包、不清UNKNOWN/任务、不强杀。该恢复不等待新材料补丁，不改凭据/权限或dotenv内容。

后续A恢复回执：在原发布/live/admission/provider锁内核journal、13个beforeSHA（4新文件已移除）及49保护SHA全通过，执行原fence.stop_then_unlock_database及DEEP restart，range health已通过；未改活动文件、权限、凭据或任务。worker仍failed，Nginx保持原配置字节、未reload候选。过滤日志明确拒读路径为`/profile/.env`，仅日志路径证据，未读该文件内容或元数据。当前状态为代码回退及旧HTTP恢复、Hermes worker待修，材料/模型验收未开始。

本包必要共享修复接点新增登记：`releases/fc-coins/fc-review-channel-20261026/source/hermes_worker.py::make_adapter`唯一修改者为Business A，Personal不并改。目标仅在既有FS runtime-config/provider代理适配中阻止官方导入隐式dotenv加载；先核公开loader调用及现成skip机制的非敏感代码，不导出生产源码、不授.env读取权限、不将提供方凭据传入worker。需相关离线契约、最新SHA独审/必要CI及沿原publisher限定发布，不能凭推断宣称根因已修复。PR715已合并，此必要修复仍属同一运行工作包，若需PR使用一个完整后续修复PR，不拆函数片或重开已合并PR；实际修复候选、恢复状态和新部署证据待回交。

完整修复候选已回交并正常合入：A `230a7cf13ab04a529c369ce049fb5080b5cd98b7`，base `4077536449a3dcaa8871623989a15be3ead1552b`，实际5路径。worker仅9行，先在FS进程替换官方keyword-only同签名loader回调为空已加载路径列表，再导入config/agent；不改Path/通用dotenv、不吞异常，不影响其他进程。A通过既有image的无网络/无profile/secrets挂载只读AST核官方签名/调用和无适用skip，依据及source hash保留在模块附录，不读.env。publisher仅将现有worker加入固定SOURCES/TARGETS/KNOWN beforeSHA，成为14目标/48保护，冻结base不变；失败13目标stage不复用。

原pr-fast runner证据为conversation32、deploy16、channel12通过且0skip，两项新增实际make_adapter离线契约经注入官方边界复现旧拒读及确认零dotenv调用，构造agent/原Runs gate、runtime-config/loopback/token/model/注册/路由保持，其他RuntimeError/PermissionError原对象传播。主控核实际diff及合并后运行代码/测试与A固定候选一致，diff检查通过。新增测试已由原store.load_tests及channel分组覆盖，无新CI接线/依赖。独立最新SHA审查及必需CI待完成；真实worker启动、材料/模型/费用/视觉仍待受控新发布验收，不把离线结果当恢复。

PR716 reviewed `6fc954f1555538677cd39b0ce5e923445899a42b`独审无未解决项、Linux32/16/12零skip，通过后merge `ac58cf7f854fb4e9548db47228a110e725f99d81`。A新pack descriptor `78aa52177a57d3fd33dd7fe728e2d77996b4be9403fde5b9a4eabb7ba1f2e1fe`，但prepare在活动写入前因`docker inspect fs-hermes-fc: No such object`中止，未生成stage/manifest/backup、未安装新worker；旧HTTP/Nginx active。原unit为Restart=no、docker --rm，失败容器已移除，unit SHA `94b9cf19547ad0a4b68307ea35d4f5317fca0136048b90d78d5f9cea1dbaf011`，固定原完整image，未改配置/权限/凭据。

同一A独占prepare/release及相关测试继续最小支持这种已验证恢复态：仅容器确不存在、unit完整hash及inactive/failed状态与原ExecStart固定image、本机image inspect交叉核实均通过时允许识别准备镜像；其他docker错误或漂移拒绝，正常容器仍核实际image。必须标明镜像来源和发布前失败状态，不冒称运行容器。主控同时核出`runtime_release.py`的runtimeRequired全active校验及冻结base guards的实际服务状态核对会阻断此恢复态；本次完整候选应一并限定处理发布前状态，不修改冻结base或全局关闭guards。保留其余服务/保护文件/CAS/围栏，发布后仍要求实际容器/image/worker健康及HTTP/Nginx读回，fallback不能充当成功证明。具体补丁/契约/独审/CI及真实恢复仍待回交，不重放旧stage、不造容器或改服务配置。

完整恢复态候选A `961467bf8d7b4de70d401ad686c86b04f2b4c31f`（base `ac58cf7f854fb4e9548db47228a110e725f99d81`）已正常合入，四路径仅prepare/release/原deploy测试/模块附录，运行代码与A固定候选相同。manifest显式增加runtimeBefore及workerImageSource，成功runtimeRequired仍全active；发布前用基线状态交原guards，进入restart后永久切回实际容器/健康/active检查，之后才reload Nginx。严格missing分支还核唯一有效unit/drop-in、无待daemon reload及本机固定image，与原unit/drop-in SHA及保护CAS绑定；不把本机镜像存在称作运行成功。冻结base、14目标/48保护/4新增不变。

复用相同运行代码的原pr-fast deploy三模块19项通过、0skip，新增3项含容器/单位/image/状态漂移及原inspect/apply/journal合成生命周期：失败基线CAS、成功active、启动异常、健康后容器缺失或服务再停均拒绝并保留回退字节。主控核diff及状态切换核心，未见当前阻断；最新集成完整SHA独审及必要LinuxCI待完成，真实worker与材料/模型/视觉验收仍未完成。新Gitpack仅本地候选证据，合并后仍须最终SHA重pack/新现场prepare，不复用旧descriptor或stage。

PR717 reviewed `67e3c0107615dede37ae08befe4c6feb5b9e7157`独审无未解决项、Linuxconversation32/deploy19零skip通过，merge `ba972abbba87f4afd9f18374faf6ed6ccff61ec1`；独审完整本地19项遇旧Windows socket WinError10054，未冒报本地全绿。A新pack SHA `07287dcdaf9008df2b87789eaf1c2bfc5c4516223c8e5a0005558e2c0f21a868`，stage `/var/tmp/fs-hermes-materials-ba972abb-20261031T191240Z/stage`，baseline `2026-10-31T19:13:06.830141+00:00`，manifest `f5187838dea263cf4951255f4221bb0f80585fadf9b6e7c5293bab4e0fc78d9d`，真实inspect的14目标/48保护CAS通过。

该stage仅apply一次，原worker健康流程返回后，post worker_observation因现场systemd219不支持`systemctl show --value`失败。原journal已回退14目标（4新增移除），48保护hash及全部beforeSHA匹配，journal SHA `16899358bdd37050f36534f5623b3ad1400f2673ecdaf679f9576558e0fd3a88`，备份 `/var/backups/fs-navigation-20261006/nav-20261031T191240Z`；候选Nginx未reload。旧worker重启仍因旧dotenv代码失败，A在原锁/围栏核回退后用原DEEP restart恢复旧HTTP。当前仍为发布失败、旧HTTP/Nginx可用、workerfailed；未创建模型/合成验收任务、未操作用户页，不把曾返回健康当完整恢复。

完整最小兼容候选A `d5a640e9dd64d39a10a4e46c319c565e468fab9d`（base ba972abb）已正常合入，实际三路径：runtime_release正常容器分支去`--value`并按`ActiveState=...`解析、现有契约断言完整兼容命令及模块失败/恢复附录。A已真实只读核`systemctl --version=219`与原`-p ActiveState`返回`ActiveState=failed`。worker语义、冻结base、14/48/4集合、恢复态及原guards均未改。主控核同封装直接命令仅此处使用不兼容参数，运行代码/测试与A固定候选一致，diff检查通过；复用原deploy三模块19项零skip证据，不重复无关旧套件。最新完整SHA独审/必要CI、新最终SHA现场pack/prepare及真实恢复仍待完成，旧stage不重放。

### 软件发布成功，真实使用验收进行中

PR718 reviewed `0a3e595ad7045ec9bcf919947eead55fda188c91`独审无未解决问题，受影响独立case/18异常边界及Linuxdeploy19零skip通过，正常merge `1f8ddc57c37e16df7c802de358eefb6585d078ee`。主控核merge树与reviewedhead一致，A clean/ff后新Git LF pack descriptor `346d3b5659593a5b78a5043fd7c4ec717e0f3824815bef83ba024620bd010014`。

A实际发布回执：stage `/var/tmp/fs-hermes-materials-1f8ddc57-20261031T192312Z/stage`，baseline `2026-10-31T19:23:40.580450+00:00`，manifest `b129179049dc9ff4b575075ebd1b47c1f6edf325936ac70b1286ca990bd73a05`，runtimeBefore为failed、来源configured_unit_and_local_image。inspect source/protected CAS通过后仅apply一次，返回`applied-awaiting-actual-http-role-acceptance`；备份 `/var/backups/fs-navigation-20261006/nav-20261031T192312Z`，journal SHA `c902e8f3d1d613c80f1f0573647dbcf17184466579fdfbc77539d8f8846c24fc`。

独立现场读回14个afterSHA均与manifest一致，root owner/原mode匹配，48保护文件原SHA保持。worker/range/nginx均active/running；实际`fs-hermes-fc`容器Running=true、image为原`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`；range health200/oktrue，匿名worker capabilities401。原健康、实际容器及成功active guards通过后才reload限定Nginx增量。未改unit/凭据/权限、未清UNKNOWN/DB或做业务写。此前失败stage/journal保留，不据本次成功抹去。

该回执只计软件发布与基础服务恢复。A在正常Default登录态独立新tab核auth verify200、同源创建专用合成会话201，cid `0884f9a7a4ee4b66a220e20651e4e54c`；尚未提交模型，用户历史页未操作。真实材料/DeepSeek分页修订下载追问、原ID/停止/可用权限、当前部署版视觉/键盘/窄屏/缩放正在取证，Personal最终审核尚未通过。A2真实scope、真实第二身份等仍未验，不标完整Hermes或阶段1/2完成。

### 真实材料证据及视觉退回

A已回交上述合成会话两轮实际completed闭环：首task `efae1d897b2d494816ca594eb519b953`，仅该task白名单provider metadata显示requested/response model为deepseek-flash，5次成功回执；实际backend版本unknown、cost_microcny为null，不补0或外推全部费用。实际CSV offset0/200、limit200及XLSX两sheet读取、一次固定request_id修订；浏览器下载v2 5401字节解析a10/b25、说明页不变。v2显式卡片追问并刷新仍仅选v2，第二task `9c511c44d5f9df7a1a87efccb31c7a7a` completed生成v3（fid `708c96a51f2b4332d3323bd332dc4f07`），5400字节解析a10/b30，parent=v2/version3、说明页保持。完整下载SHA/各sheet total与cursor覆盖链待附录，主控不从两个offset推断全量或451行。

同原request_id/附件集合重POST仍返回原turn，变附件422且turn数保持2，无模型重发。unknown上传是明确浏览器丢弃服务端真实201回执的故障注入：刷新保留unknown，同名同大小不同SHA重选UI拒绝且0POST，GET核对原request_id恢复原fid，无换ID/重复上传。无附件微任务实际完成；一次过早结束的任务不算stop成功，另task在queued时经真实按钮cancelled/空回复，后台收敛仍待核，queued与running取消分开，不能声称provider计费已停止。

视觉明确未通过：A实际查看当前部署桌面浅/暗后回报长标题挤压connection竖排、messages可视高度35px、历史sidebar约15211px撑长页面。主控尚未亲看这轮截图，按A实际取证列为阅读/操作阻断，退回同包A修CSS/JS；须保留unknown/失败核对入口及原绑定语义，只在发送确被接受后可收起附件。需新部署版截图/viewport/theme/time/必要键盘/缩放等复核，不重复付费外观生成。隐私样式注入被CSP阻止的首图已弃用，后续仅遮非当前标题且核visibility生效、保持布局；不读用户历史或凭据。

已安装follow-up支持仍归原A prepare/release/tests：用本次真实成功applied journal/manifest及1f8ddc57合并Git载荷精确匹配绑定当前合法baseline，不把任意现场hash直接当合法来源；4个初次新增模块在follow-up必须有已有beforeSHA，失败回退恢复已安装字节而不删除。Nginx现10m保持已核成功字节，不重套16k模板。冻结publisher、14/48/4集合、锁/CAS/准入/provider/UNKNOWN/权限保持，优先沿原静态增量能力避免UI-only重启worker/HTTP。A在同一个完整UI修复候选收口并测试首次安装/已装更新/漂移/回退，Personal集成独审/CI后复核实际使用，最终功能/视觉仍未验收。

### 可读性修复与精确静态跟进候选

A完整候选`d4a9f6fd1cabbe247e2a5eae171955182a24bb51`（base `1f8ddc57c37e16df7c802de358eefb6585d078ee`）已正常合入，无冲突，运行代码/测试与A固定候选一致。仅模块内8路径：CSS/JS、原两项UI测试、prepare/release/原deploy测试和附录；B语义/冻结base/CI驱动未改。标题视觉两行但保留完整DOM/native title，状态nowrap、侧栏限高、展开消息区至少160px；普通turn被接受后才收附件，unknown/失败/steer原语义保持，附件操作触控区及人类可读进度标签补齐。

pack绑定已发布1f8的13个Git LF源哈希和已核Nginx；follow-up只接受b129 manifest/c902 journal的精确成功proof，核14当前已装afterSHA、48保护/模式/实际image。4模块均有已有beforeSHA，Nginx10m字节保持。仅前端差异且三服务active/来源container时materialStaticOnly沿原writer/journal/每一guard执行，12个不变目标只CAS不写，CSS/JS两目标调用原atomic；最终仍核实际image/active，静态路径不重启worker/HTTP、不reload Nginx、不调模型。失败回退恢复4个已有模块；非静态仍原restart/readiness。实际发布载荷与变更目标在新现场prepare后再次核定，不把本地pack当生产manifest。

A同代码原deploy三模块21项零skip、原Node实际DOM/fetch、本地Chromium合成下载/99历史/长标题/1280x800展开/浅暗/390通过；主控已亲看现网light及390问题截图，及候选本地expanded/mobile，确认现网阅读挤压和候选方向改善，尚未看修后部署版。主控另用原始Git字节独立比对附录14 afterSHA表：13源载荷全部匹配，Nginx匹配已核成功hash。尝试只读附录v2/v3浏览器下载路径时首个FileNotFoundError，不能声称主控已独立解析下载；已请A提供稳定合成artifact或由主控最终同fid正常下载，不追加模型。最新集成完整SHA独审/必要CI、新静态部署及最终视觉/字节复核仍待完成，生产继续稳定1f8。

附录已补齐实际合成任务/文件完整ID、SHA及provider分层：两材料任务各5回执，另自然完成微任务1及queued取消1，共12回执；backend版本unknown、费用null。CSV同SHA重解析总206含表头/205数据行、sum205，实录成功参数offset0/200 limit200覆盖[0,200)/[200,206)，末页complete仍false；两XLSX sheet各3/2行。十条coverage链由实录参数/成功事件及同SHA确定性解析重建，非原raw工具回执；不据此声称业务全量。取消到19:41:05Z仍cancelled/空回复/0工具，provider3token回执保留，不称计费停止；running取消未验。真实匿名下载401、跨合成cid404；第二身份/撤权过期/A2scope未验。200%快捷键未改变实际缩放，仍未验，不以CSS缩放或窄屏冒充。

下载收据交接已补正，A代码候选d4a9f6fd未变：原真实下载缓存经正常工具审核复制到新共享Temp目录`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Receipts-1f8ddc57-20261031T200731Z/`，仅result-v2.xlsx/result-v3.xlsx两份合成产物，无新模型/HTTP/生产操作。主控已独立只读读取并用openpyxl核：v2 5401字节/SHA `1b731736326470071e596abf684ef0844add1ca0447b3b83304bd5337c76b390`、v3 5400字节/SHA `8bc7f4b7dbab1645d91c10ce7c90ad2d04e4c3530606837396c0b282ec5e1f11`，两sheet均可读，数据分别a10/b25及a10/b30，说明sheet均为FS synthetic acceptance only且一致。旧浏览器临时路径缺失保留为历史交接问题，不再列为下载内容核验阻塞；新的稳定收据及独立字节内容核验不替代修后部署版视觉验收。

本轮用户授权本包软件部署及必要使用测试：原合法SSH/会话、publisher、发布/准入锁、现场CAS、备份、定向服务重载、读回及回退。保留全部DB/任务/文件/UNKNOWN与原自动化；活跃或不明任务按原发布器处理，不强杀/清状态制造空闲、不旧整包覆盖。

不新增账号/凭据/权限/安全配置或费用，不启用待配置模型，不改价/发券/订单/触达客户、不真实购买支付。测试仅新增明确标记的小合成验收会话/附件，不删除旧业务数据。真实数据只读现有授权scope的必要匿名摘要，原客户/订单/密钥不进Git或截图。

必要真实任务只用既有DeepSeek及当前额度/停止设置，保留provider回执/用量，费用未知写未知。不新增预算、换供应商/账号、改到额停止或为外观重复付费生成。缺配置/额度准确标阻塞；部署和非模型可验部分继续，真实模型链不得假报通过。

## 功能验收标准

| 检查 | 通过证据 |
|---|---|
| 现场/发布 | 精确源/目标、before/after哈希、manifest/stage/备份/锁/CAS、服务与URL读回，旧业务保护对象保持 |
| 材料闭环 | 真实身份上传→绑定→DeepSeek工具/分页覆盖→确定性修订→有效文件下载→显式追问；核内容、parent/version和真实字节 |
| 恢复/停止 | 刷新/断线不重复任务，unknown查原ID；停止后台状态收敛、不再发新工具/动作，迟到不覆盖新turn；不冒称供应商计算/费用已停 |
| 权限 | 原授权正向，未登录/实际可用低权身份、越owner/cid/turn/scope拒绝；无真实第二身份则未验，不造账号或认证头冒充 |
| 冻结调查 | 实际host scope、原冻结引用、完整cursor链、截止/检查点及缺项/更正/无新单边界；没接worker/工具就标未接 |
| 故障/回退 | 过期/损坏/丢失不授下载；沿原备份回退代码、保留DB/回执/自动化；未演练就不称回退已验 |

## 视觉、交互与审美

依据ui-system/README.md、tokens/fs-tokens.css及现场活动版本，复用组件、字体、语义色、留白、圆角、主题和状态，不复制局部系统或全站重构，不改业务口径/权限。

- 当前版真实浏览器：桌面浅/暗、390px窄屏、必要200%缩放；无横向溢出/遮挡/裁切/挤压，长名称/中文可读，正文/表格/文件卡层次清楚。
- 主任务操作易发现且合理：附件→上传状态→明确勾选→发送/停止→版本卡→下载→追问。保持已选集合/输入/焦点，异步metadata错误不覆盖停止或当前任务状态。
- 键盘Tab/Enter/CtrlEnter沿原约定、焦点可见，异步checkbox不丢焦点，触控目标适合手指，不仅靠颜色表示状态。
- loading/空/成功/失败/unknown/撤权/过期准确简洁且可恢复。内部SHA/审计不堆主界面；覆盖/缺项可查且不歪曲主结论。
- HTML守既有下载/隔离边界，不同源裸执行模型HTML；下载URL仅由已鉴权服务端metadata构造。
- 图表按比较/趋势价值使用，单位/时间/分母/图例/对照正确，留白和标签清楚，不用装饰图掩盖缺数据。

A提供当前部署版新截图/录屏，标版本/时间/视口/主题/步骤，先实际检查不是空白/加载页；附真实操作步骤、内容/下载字节、相关console/network错误及修复前后对照。DOM/正则/HTTP200/服务active不能替代视觉和操作验收。原报表/主题/导航保持。

## 回交与最终审核

A通过原聊天及t3_thread_send主动回Personal：先接手/现场接点，后完整可审候选，再实际部署/测试证据。包含PR/SHA、源/目标、manifest/hash/服务/URL、真实任务/文件回执、fresh截图路径、问题与未验项；不用用户搬运。普通细节自行处理，仅超授权或无法排除的真实阻塞找用户。

Personal依据当前版功能证据、截图及关键浏览器复测给出通过/带未验项/退回修复，不能仅凭CI或发布日志通过。修复留同包，新head按既定独审复查，UI变化看新渲染结果。截图审查遵循product-design:audit，但不引入原型重建、Sites发布或新设计体系；实际FS为唯一产品目标。
