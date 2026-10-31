# Hermes运行接线、部署与使用验收工作包

2026-11-01用户明确安排Business部署和测试，Personal最终审核功能、视觉规范及人类操作便利性。沿唯一主方案阶段1/2，不另造路线。Business A为本包唯一施工/发布执行者；Personal负责总控、合并、最终审核和必要B接口修复，不并行发布。现阶段模型保留DeepSeek，其他通道仅验证。

## 当前起点与终点

PR711已merge88ac65d9337f20da71864ff48ebebc5284b89963，reviewed7275612c/basecc33dbcb独审通过、project-only P2解决，LinuxCore125/user-analytics253及ready重跑成功。本包开工已fetch/ff main为fc77dd1b8743c8c54dd6c943fffa0fadfa6f30a2，工作区干净；其新增为其他活动分析，不覆盖其成果。

上述不代表本轮已部署。Business先最小现场只读核对真实活动源/路径/版本、服务、入口、发布器和已有权限。历史SOURCE-MAP/manifest只作定位，不直接重放或从旧快照覆盖当前活动文件。

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

生产源码导出已由13项缩至1项：9项可复用精确Git字节，上述3项不改。仅会话`/var/www/dashboard/fs-home/hermes/conversation/index.html`未匹配且确需保留现行导航，5776字节，SHA256 `3d79a5642f1517a8c1e414702c2b7491dc0ff4ed079c7d09895a3b1251045a24`。拟复制到A本机ignored `.agent_runtime/runtime-20261101/live/frontend/index.html`，不入Git、不含配置/凭据/DB/业务数据。此前13项SCP被自动审批以未明确授权生产源码导出为由拒绝，命令未执行；本次单文件仍待用户明确许可及正常工具审核，禁止等价绕过。正常FS登录和真实会话/视觉验收仍待完成。

A已确认对应新增测试精确路径为`releases/fs-dashboard/hermes-conversation-20261018/deploy/test_runtime_materials.py`，同属A唯一维护。现有pr-fast conversation deploy使用显式列表，不自动discover；Personal仅在该列表追加`test_runtime_materials`，保留原HTTP/release及Node入口。测试模块尚待A固定候选合入，当前不将驱动接线或A回报的本地模拟通过宣称为本分支完整验收；合入后核实际执行数量及LinuxCI，目录fsync/POSIX权限、生产回退与真实模型仍分别取证。

## 当前授权边界

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
