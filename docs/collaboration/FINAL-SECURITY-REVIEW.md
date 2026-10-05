# Revision3 有限增量独立只读安全复核

审阅日期：2026-10-05 UTC。审阅人：独立只读 review 任务（task-5）；本报告不修改原工程指导、不修改候选。具体候选为 `E:\WorkBuddy\大超服务器\fs_platform_integration_20261005\candidate_revision3`，证据入口为同项目 `docs/planning/fs-platform-integration-20261005/revision3/README.md`。承接本任务前两份独立报告，仅复审原三个 P1 和直接引入的回归，不扩为全平台审计。

## 结论

原三个 P1 的指定漏洞机制均有明确候选修补，未发现新增**已证实 P1**。可确认的是静态代码与合成测试记录范围内的改善，不能写成生产发布通过。FC 外部页面四个内部共享资源仍拒绝，完整页面兼容未闭环；NBA 逐轮确认与无人值守策略尚未选择。以下另列两项 P2：浏览器请求/回执未贯通，以及 Linux 回执目录持久化缺口。后者的实际掉电丢失尚未验证，不能当作已发生事故。

独立核对 311 文件、12,111,256 字节，每文件 SHA/大小及文件集合与精确清单完全一致。清单声明集合标识为 `f1d7ce1d3cb2c73ccaae58744ef2ff2a34cef69070d098193b2cac86b7ae532c`；这里核对逐文件清单，不冒称另行推导清单集合算法。182 个 Python 文件通过标准库 AST 解析，未执行候选代码。原 227 和 revision2 的 301 文件集合均无增删改。独立机器证据见 `revision3-security-evidence.json`。

## 三个旧 P1 的逐项结论

### R2-01：FC 会话兼容与内部扩权 — 指定桥接缺陷已修，完整兼容仅设计阻断

文件/行：`opt/auth-portal/fc_read_scope.py:8`、`:20`、`:28`；`opt/auth-portal/auth_portal.py:687`、`:694`、`:699`、`:704`、`:706`、`:713`。

证据：FC 回退限定 GET/HEAD 与两条归档 FC 路由，拒绝内部 dashboard/tasks/docs/admin 路径、点段、编码路径、反斜杠、绝对 URL；只向本地既有 8896 `/verify` 传筛出的 `fc27sess`。只有上游 200、受限用户名和受限响应长度才输出 `X-Fc27-User`/`X-Fc27-Role: readonly`，不输出 `X-Auth-*`。用户名即便同为 wulv/DY，也没有内部登记的自动提升。正常 portal 分支继续执行组成员和中央策略检查。查询字符串可用于原读端筛选；不能仅因允许 query 就断言写入绕过，已读 Players GET 分派与 owner 绑定未见该直接机制。

测试证据：只读审阅 `tests/integration/test_revision3_contracts.py` 的四组 FC 合成矩阵，覆盖合法原路由、上游拒绝/非法用户名、内部路径与写方法拒绝、内部 readonly/admin 分离；这些是 mock 连接/提取函数，未证明实际 nginx 已正确传入 original URI/method。未使用真实 Cookie。

影响/剩余：原先完全切断合法 FC 会话的机制已修；四个 `/dashboard/fs-home/transactions/` 共享静态资源仍被拒绝，因此 FC 页面完整兼容不能判定通过。`docs/integration/REVISION-3-DECISIONS.md:3` 明确记录此阻断。

建议：父任务取得精确四资源 FC 专用只读 alias 的业务决定后另行实施并验收页面依赖；继续拒绝内部页面和经营 JSON。不得恢复整个 dashboard fallback，不得借同名用户名扩大内部组成员。

### R2-02：NBA 跨请求计划/响应错绑 — 指定并发漏洞已修，幂等仅同 ID 合同闭环

文件/行：`opt/nba-reprice/backend/server.js:548`、`:557`、`:559`、`:567`、`:571`；`p2pah_api.py:64`、`:67`、`:125`、`:197`、`:217`、`:298`；`write_contract.py:16`、`:57`、`:95`。

证据：Node 每次传输使用随机独立计划路径、独占创建与 0600；哈希覆盖排序价格、operator 与确认标记，返回回执必须同 requestId/hash/operator。Python curl 独立临时响应并只清理自己的响应文件；写入/login/cookie 生命周期共用锁，进程内 RLock、Linux flock 分支与 Windows 锁分支均保留。先存 pending 再执行；同 ID/哈希/actor 完成只回旧回执，pending/unknown 不再执行，同 ID 改内容拒绝。

测试证据：`tests/integration/test_nba_bound_writer.cjs:18` 延迟 A 文件读取至 B 已启动并反序完成；检查独立路径、各自价格、回执错绑拒绝、超时 unknown 与清理。它在 VM 执行实际 adminWrite 函数字符串，execFile 为 fake，没有真实子进程/上游写。Python 合成合同检查线程串行、同 ID 重放、不同 hash 冲突、异常 pending 不重复执行、独立 curl 响应。审阅人没有重跑这些候选函数。

影响/剩余：此前 A 读到 B 价格、共享响应覆盖的指定交错已由代码消除。不能把“同 ID”扩大成浏览器自动保证幂等，也不能把进程异常保护扩大成已验证掉电耐久；见下列两个 P2。真实 Linux 多进程锁、受信运行目录/同源 credential 使用、外部请求结果未知的人工核对未验。前端错误会暂停循环，没有发现错误后自动无条件重写。

建议：保留默认写关闭和授权/POST/Origin/正价格守卫；实施请求身份贯通与 Linux 持久化后再验真实运行边界。无人值守必须另作业务决定，本轮不能隐式恢复旧自动策略。

### R2-03：Cookie/batoken/Basic 静态包漏扫 — 指定 JSON 漏洞已修

文件/行：`opt/deploy-hub/bundle_policy.py:12`、`:14`、`:16`、`:27`、`:34`、`:78`、`:95`、`:133`；同目录 `deploy_client.py` 生成嵌入政策。

证据：JSON 先解析再递归，规范化转义/大小写/分隔符键并传播 credential 标记至嵌套对象与列表；识别 Cookie、set-cookie、batoken、Authorization 及无专用键的 Basic/Bearer/Header 字符串，拒重复键、非法 JSON；完整 ZIP 成员验证后才返回给 writer。客户端政策逐字节及嵌入 SHA 与服务器政策一致。

独立验证：只通过可信标准库 AST 读取常量及编译字面量正则，使用 SYNTHETIC 占位值证明 Cookie/cOoKiE/baToken/set-cookie/authorization/分隔符键均命中规范化 credential 集合，Basic/Bearer/Cookie header 值命中且不是允许 placeholder。未 import/exec 候选政策。审阅测试源码看到转义键、递归/列表、重复键、先验 ZIP、明确 placeholder 与生成政策一致性负/正例。

影响/剩余：原 `assets/settings.json` 中这些普通明文 JSON 字段放行漏洞已修。HTML/JS 为启发式扫描，二进制/编码/隐写内容和任意 JS 语义不由此证明无秘密。源代码明确允许 placeholder，不能据此作任意凭据无泄漏保证；目前未在有限增量范围发现新已证实绕过。

建议：维持文件/目录/扩展名限制及 ZIP 全量先验，交付说明保留扫描能力边界；不要用扫描作为任意可执行前端内容的同源安全沙箱。

## 新增问题与直接剩余缺口

### R3-01 / P2：浏览器未贯通 requestId/hash，正常界面无法使用同 ID 回执核对

已证实文件/行：`var/www/nba2k27/index.html:829` 请求只提交确认和价格参数，未提交 requestId；`opt/nba-reprice/backend/server.js:551` 缺 ID 每次随机生成；`:706` 成功响应仅 results/verify，未返回绑定身份；前端 `index.html:843` 失败只保留 error 字符串，丢弃后端 detail。同文件 `:1304` 错误会暂停。

可复核证据：两次相同的当前浏览器 payload 到达 adminWrite 时，每次走随机 ID，因此 receipt 去重键不同；前端既未提前保留 ID，也未从成功/失败响应保存核对身份。现有 delayed Node 测试显式传入 ID，覆盖不到真实 doApply 的这条路径。此结论来自源码数据流，未触发实际写入。

影响：进程内原错绑已修，但正常 UI 对网络断开/未知写结果没有可复用的请求身份；管理员重新确认将生成另一 ID，绕过“同 ID 只回旧回执”保证。这是核对与重试合同缺口，不是已证实自动重复写或未授权写入；现有错误暂停是有效缓解。

修复建议：在发出写请求之前生成并保留请求 ID 与确定计划，响应返回 ID/hash/operator/state；展示 unknown 与核对身份。未知结果应先查询/核对原 ID，确认前不另生成 ID 继续写；新业务计划另建 ID。补充实际前端 payload/HTTP 响应与断线重试合同的合成测试，不访问真实上游。

### R3-02 / P2：文件 fsync 后 rename 未同步目录，Linux 掉电耐久声明尚不成立

已证实文件/行：`opt/nba-reprice/backend/write_contract.py:84` 至 `:93` 对临时文件 fsync 后调用 os.replace，没有目录 fsync；`:99` 新建 receipts 目录也无父目录同步；`:107` 注释称“durable before first upstream effect”，随后 `:109` 执行上游。

条件性风险：文件内容同步不能独自构成 rename/新目录条目跨突然掉电的持久保证。若目标文件系统在上游副作用后、元数据落盘前重启而丢失 pending 条目，后续同 ID 可能被视为初次执行。该丢失窗口依赖 Linux 文件系统和实际崩溃条件，未实施掉电/崩溃试验，不能报告为已发生重复写。正常进程异常/同 ID 已有 pending 的代码路径仍会拒绝重放。

测试证据：现有合成异常/pending 测试使用仍存在的回执文件；Node timeout 测试是 fake 子进程，均不覆盖文件系统元数据丢失。真实 Linux 锁/运行目录验收本已列未验。

修复建议：Linux 下原子替换后 fsync 回执父目录，新建 receipts 时同步其父目录；pending 的耐久确认完成后才允许 upstream execute，持久化失败保持拒绝写。完成回执同样同步目录。为其他操作系统写出明确合同，补充可信临时目录/故障注入验证与受控 Linux 运行验收。

## 测试、覆盖与未验边界

主负责人归档记录 `revision3-targeted-evidence.json` 声明 47 项 Python（46 pass、1 Windows symlink skip），3 组 Node；`fullRevision3SuiteRun=false`。独立读到相应源码和清单哈希，不冒称独立执行，亦不把 revision2 的 170 项作为 revision3 全套重跑。迁移和 rev25 数量/公式例本轮只核归档范围，没有扩审全部策略或真实历史数量。

本轮实际独立运行仅自己工作区的可信标准库审阅脚本：候选逐文件哈希/大小核对、AST 静态解析、政策字面量合成判断、原快照未变检查。D4 `gates.py:87` 有既有 invalid escape SyntaxWarning，未列为本增量安全漏洞。报告及脚本写在审阅人工作区；候选、原件、生产及原工程 AGENTS 均未写入。

未验：生产 nginx/systemd 有效配置、FC gate/portal 真实 cookie 与身份、四资源 alias 实际页面兼容、真实管理员/内部只读账户、Linux flock 多进程与文件耐久、文件 ownership/目录旧权限/root 绕过、真实采购/改价/部署请求、容器/CDP/依赖齐备、全部 17 模块、Ponytail。311 文件数量不是 17 模块齐全证据。前两轮的运行数据/凭据剔除结论仅在当时候选范围成立；本轮对新冻结候选逐文件清单核对没有恢复这些文件，也没有读取 raw 实际 cookie/运行数据。

旧 publisher/旧链退役是正常已验收状态，本轮没有恢复、建议恢复或重新打开旧链。第四管理员 fstech 不因本轮 FC 同名身份桥接获得内部管理员；三管理员授权、root/旧权限边界仍保留为历史审阅与真实运行验收限制。本报告不关闭生产 OD、不授予发布许可。
