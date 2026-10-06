# Revision4 NBA 两项 P2 有限独立只读复审

日期：2026-10-05 UTC；审阅任务：task-5。输入为 `E:\WorkBuddy\大超服务器\fs_platform_integration_20261005\candidate_revision4_nba_receipts`，外部交付入口为 `docs/planning/fs-platform-integration-20261005/revision4-nba-receipts/README.md`。已读继承 AGENTS；依外部入口认定本轮精确输入，继承 revision3 文档不是新版上传清单。

## 结论

**R3-01、R3-02 两项 P2 在本次候选代码及合成证据层可关闭。有限范围未发现新的已证实 P1/P2。** 关闭限于下列明确合同：浏览器同源持久记录与同 ID 回执核对；Linux 在可信、既有持久父路径上的目录 fsync 调用顺序。不能写成跨设备无条件幂等、真实 Linux 掉电耐久或生产发布通过。

独立核对 313 文件 / 12,138,621 字节；逐文件 SHA/大小与冻结清单无差异，5 改、2 加、306 不变、无删，与 delta 一致。复算集合 SHA 为 `1b89d8184c1be9034d56479b96554d1127a7cee10b1ce3525b2f5e3bfffbe06f`。采用交付工具 `tools/build_evidence.py:13` 的 Windows pathlib 排序，而非 POSIX 大小写敏感字符串排序；这是集合算法复现时应说明的排序条件，不是候选内容差异。20 项外部证据文件（含原始测试输出与 diff）全部符合 evidence-sha256 清单；revision3 的 311 文件原快照未变化。修改/新增的 3 个 Python 文件仅做可信标准库 AST 解析，均通过。

独立机读证据：`revision4-security-evidence.json`。审阅人没有执行/import 候选代码，也没有重跑作者测试、安装依赖、读取真实凭据、接触生产或写候选。

## R3-01：请求 ID 与回执未贯通 — 候选代码层关闭

文件/行与证据：

- `var/www/nba2k27/index.html:809` 至 `:817` 保存/读取非秘密计划记录；`:838` 至 `:840` 依赖同源 Web Locks；`:844` 使用确定 payload 指纹；`:853` 人工确认后产生 ID，`:858` 保存 unknown 和确切 payload 后，`:859` 才 POST 包含 requestId 的数据。`:891` 将平台排序。相同计划 ID 稳定，跨标签/刷新依赖同源记录与锁。
- `index.html:845` 至 `:851` 对 unresolved 或同计划 completed 只 GET 原 ID 回执；not-found/pending/读取失败不能解除 unknown；未完成原请求时不发另一计划。完成核对后若计划不同，要求重新操作确认，才建新 ID。此前“缺 ID 每次生成新键”的正常 UI 路径已修。
- `index.html:821` 至 `:826` 检查已记录 ID/hash/operator、保存完整 body（含失败 detail）并展示状态；`:830` 185 秒 AbortController 超时；网络/解析/绑定错误留下写前已存 unknown。`:867` 增加只读核对按钮，`:871` 刷新恢复展示。清日志按钮不清回执记录。拒绝且无效果的同计划须再次人工确认，复用原 ID。
- `opt/nba-reprice/backend/server.js:548` canonical hash 继续绑定排序价格、确认标记与已认证 operator；`:617`/`:622` 复用请求身份；`:742` 保留 unexpected error 的 unknown context；`:750` 失败返回身份和 state、detail；`:753` 成功返回完整 write 回执；`:758` 保留绑定后异常 context。认证/非法计划无可信 hash 时字段为 null，是诚实的未绑定拒绝，不伪造成功回执。
- `server.js:651` 至 `:664` receipt 仅合法 32hex 文件名，路径固定在 WORK_DIR/receipts；`:693` 至 `:701` 先现有认证再 GET 限制与 admin 检查；`:657` 校验 operator，other actor 与不存在同样隐去内容；pending/损坏/缺失保持 unknown。读取不运行 Python/login/上游，不列举回执。三管理员白名单与 readonly 限制沿用未变的 `api_security.js:2`、`:3`。

影响：正常前端能保留/核对写请求身份，错误 detail 不再丢失；无结果不能通过改计划直接发新 ID。每个新写仍有人工确认，未选择或引入无人值守模式。相同已完成计划只查回执，不再次写入，也不把查回执当新写确认。

证据覆盖：新增 `tests/integration/test_nba_ui_receipts.cjs:36` 至 `:72` 在实际 doApply 提取代码的 VM 中覆盖同计划点击/双标签/刷新、不同计划、效果后断网、not-found 继续 unknown、完成核对后重确认、partial、拒绝复用、错绑、缺锁/存储失败、实际 AbortController 分支；`:94` 至 `:114` 在实际 HTTP handler VM 中覆盖 success/partial/timeout/refusal 绑定、read-only 403、匿名 401、other actor 隐藏、非 GET 405、路径/ID 400、pending/损坏/缺失及无读回副作用。浏览器 DOM/storage/locks、HTTP、writer 均 fake；不是浏览器/真实代理端到端验证。原 bound-writer 仅改实际函数提取边界，保留两独立计划延迟读取与错绑拒绝测试。

剩余边界/建议：客户端记录只覆盖同源持久存储；清存储、换设备或自行发新 ID 不受这一 UI 合同保护，服务端仍仅同 ID 去重。README 已明确，不能升级为全局重复业务防护。真实 Web Locks、同源存储、有效 nginx 身份/header 路由、NBA 环境认证及真实未知效果核对仍未验；受控后续验收应保持 unknown 人工处理，不加入强制新 ID 按钮。

## R3-02：目录 fsync 缺失 — 条件明确的代码层关闭

文件/行与证据：

- `opt/nba-reprice/backend/write_contract.py:85` 至 `:93` 区分 Linux directory-fsync 与其他平台 `file-fsync-only-no-power-loss-guarantee`；Linux 用 O_DIRECTORY 打开、fsync、finally close，失败传播，没有默默降级为 Linux 成功。
- `write_contract.py:95` 至 `:101` 对新建 runtime/receipts 同步父目录及自身；已存在目录每次也重试同步，避免先前 mkdir 同步失败后下一次因目录已在而跳过。`:25` 锁入口和 `:120` receipts 入口均使用该函数。
- `write_contract.py:103` 至 `:111` 顺序为临时文件 flush/fsync、same-directory replace、回执父目录 fsync；`:132` 至 `:136` pending 同步成功才 execute，文件/rename/目录同步失败没有上游效果，返回 rejected。`:143` 至 `:145` 完成持久化失败为 unknown，不冒称成功。
- `write_contract.py:122` 至 `:131` 损坏/未完成回执 unknown，同 ID 改 hash/operator 拒绝；已完成同 ID 只返回旧回执。旧回执无能力字段标注 `unrecorded-no-power-loss-guarantee`。`p2pah_api.py:305` 至 `:312` 绑定后锁/setup/read 错误保留身份且 unknown，不声称可以放心新写。

影响：原缺失的目录同步步骤已补齐；进程正常故障路径保留 pending/完成去重。Linux 文件系统/存储硬件兑现 fsync 以及突然掉电恢复仍是未验运行条件，`persistence` 描述执行 syscall 能力，不是物理掉电试验结论。

证据覆盖：`tests/integration/test_nba_receipt_durability.py:24` 至 `:36` 检查文件 fsync → rename →目录同步 → effect 及 completed 顺序与目录父同步；`:37` 至 `:54` 注入 pending 文件/rename/目录、新目录父同步故障并确认零效果；`:55` 至 `:63` 完成持久化失败后重新调用不再执行；`:64` 至 `:71` 同 ID 四线程仅一效果和改 hash 拒绝；`:72` 至 `:78` 模拟 Linux open/fsync/close 与 Windows 不冒称目录同步；`:79` 至 `:87` partial 完成及损坏回执不重复执行。CLI setup failure 另有绑定 unknown 用例。完成失败测试在 _persist 完成前注入错误，并非真实 rename 后掉电测试。

剩余边界/建议：Node `server.js:73` 的 recursive mkdir 以及 Python `p2pah_api.py:41` 普通 mkdir 不能独自证明新建所有祖先路径持久；当 runtime 已被这些代码创建，_ensure_directory 只同步当前与直接父目录。README 已要求可信父路径预先创建且持久，此条件下不能继续保留原“目录 fsync 完全缺失”P2；若未来声称任意新祖先路径都安全则需另补全祖先同步合同。真实 Linux 多进程 flock、权限/归属、fsync 错误运行行为、文件系统/硬件和真实故障恢复尚未验。其他平台明确降低保证，不隐含 Windows 掉电耐久。

## 测试记录与覆盖边界

仅读作者归档 `test-results.json` 和原始字节输出：8 个新 Python durability + 12 个 revision3 contracts = 20 项，均 OK；4 组 Node（UI/HTTP、bound-writer、wired-routes、pure-guards）均通过，pure-guards 记录 28 断言；server/inline JS 语法及 3 Python AST 有通过记录。原始输出/工具/清单 SHA 独立核对成功。没有将其他历史套件或 17 模块作为本轮已测。

独立运行仅自写 `audit_revision4.py` 的静态哈希、差集、证据 hash 与 AST。未执行任何交付工具、候选函数或候选测试；未用真实 cookie/身份/权限/订单/价格/日志，不触生产、Git 或上传。旧 publisher 仍是已退役正常状态，本轮不恢复旧链。

仍不得宣称生产可发布：真实 Linux/浏览器/代理验收没做；FC 四资源兼容、NBA 每轮确认与无人值守业务决定及既有运行 OD 未关闭。候选继承 UPLOAD-ALLOWLIST 没更新且 releaseReady/uploadApproved 均 false，仅作为审查输入。
