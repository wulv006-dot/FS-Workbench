> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。

# NBA R3-01 / R3-02 独立 revision4 审查交付

本候选仅供审查，未部署、未提交/推送 Git。来源为冻结 candidate_revision3 的 311 文件精确清单，拷贝前和交付后均逐文件核对 SHA/大小/集合。候选独立目录：`E:\WorkBuddy\大超服务器\fs_platform_integration_20261005\candidate_revision4_nba_receipts`。

仅改 5 文件：NBA `server.js`、`p2pah_api.py`、`write_contract.py`、`var/www/nba2k27/index.html`，以及原 `test_nba_bound_writer.cjs` 的实际函数提取边界。新增 2 个 NBA 测试文件，合计 313 文件，306 原文件逐字节不变。候选中继承的 revision3 README/清单/决策是历史材料，未改其共享文档；本目录的精确库存与 delta 才描述本次审查输入。继承的 UPLOAD-ALLOWLIST 未更新，不能将本候选作为上传或部署包。

## R3-01：请求与回执

正常 `doApply` 在明确人工确认后、POST 前生成 32 位 requestId，并先保存确切计划。相同计划复用 ID；完成的相同计划仅核对回执。拒绝且确认无上游效果的计划可重新人工确认，用原 ID 重试；变更计划才生成新 ID。价格、成本和确认参数一起进入 UI 指纹，平台先排序。后端原有 canonical plan SHA (`planSha256`，即 planHash) 仍绑定排序价格、已认证 operator 和确认标记，没有修改定价算法。

localStorage 保存非秘密计划/ID/回执，刷新恢复展示；同源 Web Locks 串行覆盖重复点击和跨标签页。缺少 Web Locks、无法保存本地记录或记录损坏时拒绝发出写请求。浏览器 185 秒 AbortController 超时、网络/解析错误和回执错绑均保留 unknown 记录。unknown 未经同 ID 回执核对完成前，禁止发送新计划 ID；not-found、读错和 pending 不代表无副作用，均继续 unknown。不能清空浏览器存储或换设备来声称该保护仍在：客户端保护仅覆盖该同源持久记录，服务器去重仍是同 ID 合同。

新增 `GET /api/receipt?requestId=<32 hex>`：沿用当前认证，只允许既有管理员读取自己 operator 的该 ID；不列举、不读取其他 actor、不触发 Python/login/上游。readonly 403、匿名 401、非 GET 405、非法 ID 400；other actor 隐去回执内容，与不存在一致。原 WRITE_READY 默认关闭、管理员白名单、POST、Origin、JSON、正价格、Python 锁和每轮人工确认均保留；没有选择、设计或启用新无人值守策略。

合法计划成功、partial/失败和 timeout 回包均保留 requestId/planSha256/operator/state，错误 detail 及结果保存在 UI 记录。合法管理员 POST 因写关闭/Origin 被拒仍返回绑定拒绝。认证失败或无效/未解析计划无法生成可信 hash，字段为 null，UI 保留已保存 ID；绑定后未预期服务器错误返回相同身份与 unknown。UI 增加核对按钮与身份/状态展示。查询得到 completed 仅说明读到了回执；unknown 在本候选没有“强制新 ID”按钮，进一步人工处理另审。

## R3-02：持久化能力

Linux 分支对新建 runtime/receipts 目录同步父目录及目录自身；每次执行也重新同步，避免前次 mkdir fsync 失败被忽略。pending 顺序为临时文件 flush/fsync → same-directory replace → receipts 目录 fsync，成功后才执行 fake/真实调用者提供的效果。completed 同样同步目录。pending 文件/rename/目录同步失败拒绝执行；上游后完成持久化失败返回 unknown，原 pending 禁止重放。已有损坏回执保持 unknown，不当作可安全新写。

能力字段 `persistence=linux-directory-fsync` 描述代码执行的 syscall 合同，不是已验证物理掉电保证。部署前 runtime 的可信父路径必须已创建且持久，目录归属、权限和文件系统须另验；Node 的 recursive mkdir 不能独自证明新建祖先路径持久。Linux fsync 错误保持拒写；文件系统/存储硬件是否兑现 fsync、真实 flock 多进程与掉电恢复不在本次 Windows 合成测试证明内。

Windows/其他平台不尝试或冒称目录 fsync，回执明确 `file-fsync-only-no-power-loss-guarantee`；只承诺文件 fsync/原子替换与现存回执去重，不承诺突然掉电后目录条目必存。旧回执没有能力字段时读取标记 `unrecorded-no-power-loss-guarantee`。本轮没有在任何平台制造真实进程/机器崩溃、断电或生产故障。

## 实跑证据与边界

`test-results.json` 与 `raw-tests/` 为逐次最终检查的原始 stdout/stderr 字节，不从旧总结拼接：新增 Python 持久化 8 项；既有 revision3 合同 12 项；新 UI/HTTP VM 矩阵、原 bound-writer、wired-routes、pure-guards 4 组 Node（pure-guards 28 断言）；server 与全 inline JS 语法检查、3 编辑/新增 Python AST，全部通过。不是完整 17 模块或 revision3 全套测试。

新测试执行实际 doApply/HTTP handler 的隔离 VM 代码；浏览器 DOM/storage/locks/网络为 fake，未开启真实浏览器、socket、listen、Python 上游进程、真实登录或改价。Python 使用隔离临时目录和 fake effect，网络/DNS/子进程被禁止。覆盖成功/拒绝/partial/超时、重复点击/跨标签页/刷新、变更计划、同 ID 核对、缺失/损坏回执、其他 actor/readonly/method/路径拒绝、同 ID 线程并发与 hash 冲突、文件 fsync/rename/目录 fsync 故障顺序及完成失败后重读。Linux syscall 分支在 Windows 上 mock；未验 Linux 实际 fsync/多进程锁/真实故障注入。

保留原服务器 failclosed 和有限授权/每轮人工模式。没有生产、真实身份/权限/凭据/定价/Git/Ponytail动作；未读 raw 凭据/订单/生产日志。冻结 rev3、父任务接口文档及共享 HANDOFF/OPEN-DECISIONS 均未改。两项小修在本地代码/合成证据层交付，正式独立复审与真实运行门槛仍待根协调，不关闭任何生产 OD。

精确资料：`revision3-input-inventory.json`、`revision4-exact-inventory.json`（集合算法在文件内）、`revision4-delta.json`（双 SHA/大小）、`nba-receipts.patch`（原始行尾的统一 diff）、`evidence-sha256.json`、`delivery-verification.json`。重跑工具在 `tools/`，以本任务工作区中的 candidate 为测试目标；独立复核时可将检查脚本 ROOT 对准此准确候选，仍只使用 mock。
