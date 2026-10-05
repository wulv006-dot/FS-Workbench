> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# 项目协作说明

- **指令作用范围**：本文件补充本项目规则；全局沟通与简化偏好不得替代已验收业务合同、生产保护和发布验收要求。业务策略变更仍须按当前任务的明确授权执行。
- **日期记录的用途**：下列带日期的交付条目是阶段快照，不据旧条目的“当前”“待验”或排列顺序认定实时状态。操作前核对同一模块最新验收材料、决策记录及现场SHA；历史安全约束继续有效，准备不等于上线，人工补跑不等于自然成功。

- 新服务器 `47.85.224.112` 的 Codex SSH 入口、已验证权限和路径见 `server_187/access/README.md`；优先运行 `server_187/access/Invoke-Server187.ps1`，不要直接使用旧 `.agent_runtime/new-server-access.pem` 或旧服务器 `No1.pem`。连接脚本会临时限制密钥权限并在结束后清理；当前环境需以 `require_escalated` 运行才能联网。
- `server_187/` 是新服务器的**统一保存与核对包**：`access/`（SSH 入口）、`bundle/`（本地程序副本）+ `manifest.json`（SHA-256 清单）、`live_snapshot/`（线上差异快照）。**`bundle/` 是副本，不是工作文件**——日常开发仍改项目根目录与各子目录的源文件。
- ⚠️ **副本同步硬约定**：凡修改被 `server_187/manifest.json` 收录的文件（FC27 页面/JS/引擎、ops、门禁、MLB、dashboard 等），改完后**必须**在项目根目录运行 `python server_187/refresh_local.py` 重新生成 `bundle/`、`manifest.json` 与 `共享资源_逐文件盘点.csv`，否则副本与源码漂移，后续线上核对会得出错误结论。
- ⚠️ `live_snapshot/` 与 `remote_sha256.txt` 是**当时**的只读核对结果，不代表服务器当前状态；下次要核对线上版本，须重新读取线上校验值，不要只跑 `compare_live.py`。
- 纯文档统一归档在 `docs/`：`fc27-coins/`（Coins 链路）、`fc27-players/`（球员链路）、`migration/`（服务器迁移与云端验收）、`planning/`（规划审阅）、`handoff/`（交接）、`archive/`（历史 evidence/quote 快照）。**根目录只保留**：`AGENTS.md`、`HANDOFF.md`、给运维的统一 API 需求主文档、3 个被 `server_187/manifest.json` 白名单收录的 MD、代码与工具脚本。新增文档放对应子目录，不再平铺到根。
- 本目录是 git 仓库（2026-09-28 起，`main` 分支，`core.autocrlf=false`）：`.pem`/`.key`、公司凭证、看板 API key、运行数据库、`.agent_runtime/`、`.workbuddy/`、`server_187/bundle/`（可再生副本）已被 `.gitignore` 排除；**新增敏感文件先补 `.gitignore` 再 `git add`**。结构性变更（移动/重命名/新建目录）除本文件外，还须在 `HANDOFF.md` 留记录。
- ⚠️ Git 本地基线（2026-09-28）：首批三个含敏感内容的本地提交已重建为清理后的根提交；旧提交经对象清理后无法读取。36 个凭据、配置、公钥及原始数据文件仅从 Git 索引移除，本机原件保留并受 `.gitignore` 排除。**本仓库只在本机使用，不添加远程、不推送或分享**；新增文件入库前仍须检查敏感内容。不要恢复旧提交或重新跟踪被忽略的文件。详见 `HANDOFF.md` 最近一次 Incremental Relay 记录。
- 当用户说“让 Buddy 接力”或要求 WorkBuddy 接手后续工作时，自动加载并执行 `.agents/skills/handoff/SKILL.md`，准备接力记录与下一步任务。
- 当用户要求“审查 Buddy 的成果”或类似表达时，自动加载并执行该技能的 Review 模式，独立核验目标、证据、结论和遗留风险。
- 交接技能在 Codex/Codex 项目侧和 WorkBuddy 侧均已安装；交接记录统一追加到项目根目录 `HANDOFF.md`，供双方读取。
- `HANDOFF.md` 只记录交接上下文，不代表 WorkBuddy 已收到或完成任务。**`HANDOFF.md` 是本项目唯一协作事实源**；此前「项目共享知识库任务卡 / 看板 / 日报」流程已于 **2026-09-28 废弃**，不再使用、不再引用。
- 只有**本工作区内可观察的产物证据**（交付文件存在于交接记录所指路径 + 完成方记录的自验结果）才能确认协作完成。不要求任何外部看板或知识库的同步更新。
- 技能安装位置：ChatGPT/Codex 侧 `.agents/skills/handoff/`，WorkBuddy 侧 `.workbuddy/skills/handoff/`（两份保持同版本、同内容）；另有全局副本 `~/.workbuddy/skills/handoff/`（纯净上游版，跨项目可用）。来源 github.com/BCS1037/wk-skills v1.2.0（MIT）。

- Google营销接入独立资料位于 `docs/planning/mmoexp-google-data-20260930/`，代码/非秘密模板位于 `mmoexp_google_data/`；2026-09-30独立只读页已上线，生产采集全部服务器运行；最新计划与验收见该资料目录google-production-entry-refresh-contract.txt；不要把原始凭据加入Git，不覆盖FC并行源文件。


<!-- project-governance-20260930 -->
- **统一遵循项目规则**：所有 Agent 开始本项目工作前，须阅读并遵循适用的 `AGENTS.md` 与当前 `.gitignore`；既有源码真源、归档、协作事实源和副本同步规则继续有效。
- **生产运行位置**：生产数据采集与定时自动化统一在服务器云端运行；本地和个人电脑只用于开发、测试及审核，不作为生产持续链路的在线依赖。具体上线、认证和权限动作仍按当前任务授权执行。
- **任务归档与索引**：任务结束及时将最终代码、脱敏资料、非秘密配置模板、部署说明和验收记录整理到本项目明确的独立子目录；纯文档归入 `docs/` 对应分类，保留来源与状态，维护任务索引并在 `HANDOFF.md` 留可追踪记录。文件归档不代表 App 任务分组已调整。
- **并行改动隔离**：开始修改前核对最新文件和已有未提交改动；使用独立任务目录或明确的文件边界，不覆盖、重置、混入其他任务改动。必须修改共享文件时最小追加并重新读取核验；不以仓库治理授权获得额外的业务变更权限。
- **凭据与 Git**：私钥、token、密码、会话、敏感配置和运行数据库不得纳入 Git、报告或可共享产物；原件保持受控。归档只包含代码及脱敏材料，入库前核对 `.gitignore` 和敏感内容；发现缺失忽略项先提出具体修正，不擅自执行 `git add`、commit、push 或扩大持续访问权限。


<!-- google-weekly-details-first-phase-20260930 -->
- Google营销细化第一阶段已发布：GA4/GSC自然周细分与3个白名单Ads账号，RSOrder两广告账号分别列示；有效合同/验收见 `docs/planning/mmoexp-google-data-20260930/weekly-details-delivery.md`，最终证据/页面图见该目录 `archive/weekly-details-20260930/`。既有每日09:00服务器采集、300秒UI检查、全部现有登录只读/匿名拒绝保持；利润率/订单细分消费首页任务统一Order主源、Admin补源合同，不并写其文件。


<!-- google-business-consumer-20261001 -->
- 营销页第二阶段经营对照已发布，源码 `mmoexp_google_data/dashboard_module/business-module.js`，只读消费统一经营不可变版本与SHA，不另写订单采集；业务标签60秒检查，Google仍每日09/300秒。最新字段/验收/缺口见 `docs/planning/mmoexp-google-data-20260930/business-phase-delivery.md`，档案 `archive/business-phase-20261001/`。


<!-- readonly-weekly-report-preparation-20261001 -->
- 历史准备阶段（2026-10-01，状态已被后续上线记录取代）：独立运营周报准备模块位于 `mmoexp_google_data/weekly_report/`，合同/验收见 `docs/planning/mmoexp-weekly-report-20261001/`。每周一02:00上海时间计划须准确整周Order原值与Admin去重输入验证后才启用；当时仅登录保护待接入页，无数值周报、无weekly timer。不要用今日/90天聚合或日用户/比例相加冒充整周，既有Google09/业务120分钟不变。


<!-- coze-migration-original-archive-blocked-20261001 -->
- COZE迁移说明原件归档状态见 `docs/planning/coze-release-radar-migration/archive-status.json`；当前Windows Library物化xattr失败，原MD未保存，不能把阻塞记录当原文件。


<!-- readonly-weekly-report-active-20261001 -->
- 历史上线阶段（2026-10-01，首次自然结果见2026-10-05记录）：运营周报准确输入已接通，旧待接入状态更新为已上线：`/dashboard/marketing/weekly/`，唯一周一02:00 Asia/Shanghai timer已启用，当时计划的下一次为2026-10-05 02:00；当时首次自然周期待验。最终代码 `mmoexp_google_data/weekly_report/`，合同与真实18区间/发布/门禁/定时证据 `docs/planning/mmoexp-weekly-report-20261001/input-contract.md`、`exact-live-delivery.md`、`archive/exact-range-activation/`。只通过首页现有准确区间服务消费，不复制采集、改主页/权限或Google09/业务120min计划。

<!-- server-source-archive-buddy-20261001 -->
- 2026-10-01代码归档/升级索引与Buddy开发准备位于 `docs/migration/server-code-archive-20261001/`：README、MODULES、UPGRADES、BUDDY及latest/VERIFICATION。717文件本地源码快照保留原路径；不是Git HEAD或自动部署包。线上本次405文件SHA盘点含历史release，339匹配、66未匹配（49历史/17其它路径）；未匹配清单见DIFFERENCES，不宣称全线上备份。批量源码导出被自动审批拒绝、未执行，不绕过。后续仍修改真源，manifest规则不变；本次HANDOFF为准备交接，不表示Buddy已收到，新基础功能由用户另定。

<!-- approved-source-review-20261001 -->
- 后续用户明确授权17路径逐项审查/脱敏导出，指定归档缺口现已补齐：同目录 `approved-live-review/` 含7原样筛查文件/10脱敏或去运行数据审核副本、双SHA、ZIP和验证。文件索引共734条（旧717快照不改）；49历史release差异保留。用途与边界见 `approved-live-review/USAGE-REVIEW.md`，副本均非部署包；FC源目录.service不等于有效systemd单位，Madden只核实文件存在未验证生产链路。保留Buddy并行说明/审核工具，后续新功能仍须核定源码真源与单独授权；原大范围导出拒绝没有被绕过。

<!-- open-decisions-register-20261001 -->
- **未决事项统一登记在 `docs/decisions/OPEN-DECISIONS.md`**（2026-10-01 建，初始 9 条）。纪律：只追加 + 就地关闭（OPEN → RESOLVED 并补结论），永不删行；**每轮工作开始时先读本文件**，逐条判断能否关闭，能关的就地关闭；影响架构或口径的关闭后另存 ADR。发现「定不下来 / 先放一放 / 等外部条件」时**立即登记**，不等有结论。只写事项与边界，不写任何凭据值。
- 同目录 `approved-live-review/README.md` 给出 17 份副本的**本地对应关系**，并列出 **8 个本仓无有效基线的线上文件**（统一认证三件套 / 当前完整经营主页 `/var/www/dashboard/index.html` / FC 两个浏览器别名 / **Madden27 两个文件**）。线上经营主页比本仓任何版本还多约 355 行。复核用 `python docs/migration/server-code-archive-20261001/verify_approved_review.py`（SHA 对齐）与 `scan_approved_review.py`（敏感值启发式扫描）。

<!-- taskboard-live-20261001 -->
- **站内项目工作任务台 v1.0.0 已上线**（2026-10-01）：`https://47.85.224.112/dashboard/tasks/`，后端 `/opt/mmoexp-taskboard/`（stdlib + SQLite，**零第三方依赖**，仅监听 `127.0.0.1:8932`），前端 `/var/www/dashboard/tasks/`，systemd `mmoexp-taskboard.service`，nginx 片段 `/etc/nginx/taskboard.locations.conf`（经 `iggm-web.conf` 的 `# >>> taskboard-20261001 >>>` 标记块 include）。源码与完整交付说明见 **`taskboard_module_20261001/`**（`HANDOFF.md` 面向 Codex，`docs/PERMISSIONS.md` 是权限唯一口径）。改 nginx 只能走 `deploy/patch_nginx.py`（幂等 + `nginx -t` 失败自动还原）；**绝不删除或覆盖 `data/taskboard.db`**；`GUARD_ADMINS = (wulv, chenchao, DY)` 必须与 `fs_permissions_unification_20260930/access_policy.py` 的 `ADMINS` 同步。
- **首页入口**：`fs-home/module-registry.json` 第 3 张大卡已由「FC 运营看板」替换为「项目工作任务台」，**`tools` 里保留 FC 运营看板**（能力未减）。⚠️ `fs-home/app.js` 第 18 行有**硬编码模块白名单** `['analytics','marketing','tasks','ops','weekly']`，改 registry 加卡必须同步改这里，否则卡片**静默不渲染且不报错**。线上 registry 是**混合换行**，改动请做字节级定点替换，勿整体反序列化重写。
- **验收基线（回归用）**：本地 `tests/test_backend.py`(34) / `test_http.py`(20) / `verify_browser.py`(50，需装 playwright 的 python)；线上 `deploy/verify_deployed.sh`(30) 与 `tests/verify_live.py`(19，需临时会话令牌，用完即删)。**四套全绿是改动的放行条件**。
- **待老大拍板**：模块 `HANDOFF.md` 第七节 **9 条优化方向（P1/P2/P3，均未实施）**；`docs/decisions/OPEN-DECISIONS.md` **OD-10/11/12**。老大明确约束：**优化建议只提方案、不擅自实施**。


<!-- taskboard-prototype-20261001 -->
- **站内项目工作任务台（历史原型，已被上面的 v1.0.0 取代，保留供追溯）**：本地单页原型在 `mmoexp_taskboard_prototype_20261001/index.html`（4 视图 × 15 游戏项目 × 9 下发部门；自检清单为完成前放行闸门），说明与 6 项待决事项 `docs/planning/taskboard-prototype-20261001/README.md`，机械自检 `python mmoexp_taskboard_prototype_20261001/verify_prototype.py`。原「服务器版需先定权限口径」的缺口已于 2026-10-01 由 v1.0.0 的三层权限 + 未登记账号拒绝解决（OPEN-DECISIONS **OD-13** 已关闭）。



<!-- dashboard-controlled-release-20261001 -->
- **统一经营页发布防覆盖（2026-10-01）**：规范源 `共享资源/MMOEXP统一看板/dashboard.html`；仅首页入口 `/dashboard/` 与完整经营页 `/dashboard/index.html` 是不同页面，不互相覆盖。完整经营页须同时保留120分钟/60秒统一快照、准确区间、Order主源/Admin补缺、等待/失败/缺失状态和利润销售/日历/结构三图。
- 当前受支持发布：`Invoke-Server187.ps1` 上传到存在的独立 staging，再用 `/opt/fs-dashboard-release/release_gateway.py --manifest ...`。必须在发布锁内重读真实HTML及共享前端哈希、版本账本；替换前再次检查。旧/同版本、旧基线、并发、缺合同拒绝；已有版本有意回滚需明确审核后使用 `--ack-intentional-rollback`，不直接scp旧源码。共享资源旧 `publish_to_server.py` 与服务器 `deploy_refresh.py`/`finish_frontend.py` 已停用。
- 当前源和离线交接必须附精确SHA/发布版本、前后端依赖目录与不含秘密的契约；`server_187/bundle` 只是核对副本，运行 `refresh_local.py` 不等于部署。禁止用旧嵌入数据的build产物替代当前规范源。直接root/SSH Run任意写入不受软件门禁完全约束，不能称绝对防覆盖；后续统一私库由用户另行提供，本轮不建库、不commit/push、不邀请。


<!-- business-metrics-view-20261002 -->
- 统一经营页历史版本 `20261002-metrics-view-v3`：按用户许可删除「项目利润地图」和指标区下方重复来源表格；14项指标、准确区间、利润/销售趋势、销售日历、03结构分析保留。指标渲染器仅内联于规范 `共享资源/MMOEXP统一看板/dashboard.html`；构建源 `fs_business_prune_20261002/metrics-only-renderer.js`。共享 `supplement-insights.js`/FC页面未改，后台dimensions保留。维护不可从旧shared渲染器整页重建恢复已删除区块；仍走受控锁/版本/真实哈希发布入口。原因/验收/备份见 `docs/planning/fs-business-prune-20261002/delivery.md`。

<!-- fc27-players-manual-images-20261003 -->
- FC27 Players当前cloud.9：源码真源 `fc27_players_cloud/`，本次交付索引 `docs/fc27-players/model-images-20261003/README.md`。用户已批准指定HTTP公开库例外、手动上新，以及原Coins价格锁单文件uid992读取ACL/只读bind；全局和自动写仍false，只新卡/模型图片逐计划确认可写。图片按PNG文件名FUTBIN ID唯一对应模型icon附件ID，默认跳过已有图；未知上传/编辑保留范围锁不重试。当前45源码SHA已与容器核验，原37计划未执行。首批真实图片/导入写验收见OD-17；OD-03以明确HTTP例外关闭，不能声称HTTPS已修复。


<!-- dashboard-overwrite-restored-20261003 -->
- 统一经营页历史恢复版本 `20261003-restore-v4`：线上曾在2026-10-03 12:17:23北京时间被不经网关的旧模板写回，具体写入者未获证。已恢复v3原功能，仅变版本标记；规范源仍 `共享资源/MMOEXP统一看板/dashboard.html`，新网关真源 `fs_dashboard_overwrite_20261003/release_gateway.py`。正常发布规则不变；明确未管理恢复只接受最新已记录页面、现场/备份/7依赖SHA，并在锁中及rename前重查。保全、版本、测试和边界见 `docs/planning/fs-dashboard-overwrite-20261003/delivery.md`；OD-18仍开放，不称root直接写入已被强制防护。


<!-- dashboard-republish-20261004 -->
- 统一经营页历史版本 `20261004-republish-v5`（606eb8846a6e9bd5662d253e953b47b523cac59b6f23cbdba3eb17ce52d950ae）：用户要求再次上线，严格按已验v4恢复，仅变版本标记。当前工程旧publisher已停用；本机可读计划任务未见匹配，不代表同事电脑任务已停用。仅发布经营HTML，原网关/7依赖/FC赠送定价/权限/120分钟采集保持。规范源仍共享资源/MMOEXP统一看板/dashboard.html；现场/验收/同事最小上传调整建议见docs/planning/fs-dashboard-republish-20261004/，没有远程操作同事电脑。


<!-- aion2-production-verified-20261004 -->
- **统一经营页2026-10-04已验收版本20261004-aion2-v6**（2026-10-04 09:10:39 UTC受控发布）：ARPG新增Aion2，Order游戏826/Admin游戏891，隔离Aion167与Classic512；所有网站Order主源/Admin补缺、真实区间、原120分钟采集/60秒检测保持。FC分类扩展保留，FC页面/Coins/timer/权限未改。规范源仍共享资源/MMOEXP统一看板/dashboard.html，不能旧包全量覆盖。
- 2026-10-04验收快照：首次自然快照20261004T092448Z-8703355689040946于09:24:48 UTC发布；Aion2今日截至17:19为43单/$836.75/-3.85%。FC分类同快照及真实页面回归通过。最小源码/测试/6张真实截图/备份/检查模式回滚/SHA索引：aion2_dashboard_20261004/；最终说明docs/planning/aion2-dashboard-20261004/delivery.md。collector SHA a6378ee4f80bcbd8de969953a0e162689377de49c68db1bf9e3f980e1c669c30；range保持FC的c80ecad9e910f8bbecf187ccda37580d25af2f2ce617671526f6c8998f26e4d9。只读角色未验，旧同事自动上传停止未独立确认（OD-18保持）；无Git操作。


<!-- weekly-first-natural-failure-20261005 -->
- 周报首次自然周期2026-10-05 02:00已观察：02:05:42退出2、目标Sep28–Oct4未发布，旧报保留；本次自然失败证据 `docs/planning/mmoexp-weekly-report-20261001/first-natural-cycle-20261005-acceptance.md`，只读取证源码 `mmoexp_google_data/weekly_report/natural_acceptance_20261005/`。共享range时长解析遗漏w及周报AION2独立范围差异已登OPEN-DECISIONS；后续先核实时下共享SHA，不用旧代码覆盖FC/Aion2，不把补跑当自然成功。


<!-- weekly-range-parser-prepared-20261005 -->
- 历史准备阶段（2026-10-05，状态已被下方批准发布记录取代）：共享准确区间timer解析最小补丁已本地准备，代码 `mmoexp_google_data/weekly_report/range_parser_fix_20261005/`，方案/59项离线验证 `docs/planning/mmoexp-weekly-range-parser-fix-20261005/`。仅基于当时be8ff834…共享FC/Aion2源修复w及严格解析；未部署/补跑。上线须先核实时下SHA，不能旧包覆盖；OD-WEEKLY-RANGE-PARSER-20261005当时OPEN。


<!-- weekly-range-parser-released-20261005 -->
- 2026-10-05已批准解析补丁上线及9/28–10/4人工补跑：当前共享range规范源 `mmoexp_google_data/weekly_report/range_parser_release_20261005/source/range_api.py`（0a03f802…），FC旧release档案保留，不能再部署be8旧整包。周报两JS规范源已与云端同步，人工/覆盖标签真实；最终合同与证据 `docs/planning/mmoexp-weekly-range-parser-fix-20261005/approved-release.md`。每周一02/Google09/经营120min保持；解析事项RESOLVED，下一自然验收及Aion2周报范围仍OPEN。
