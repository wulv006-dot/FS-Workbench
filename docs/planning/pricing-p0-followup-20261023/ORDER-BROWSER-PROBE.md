# Order 18:43 OOM 与探针进程边界

2026-10-23 18:43:13.570，内核确认 fs-order-browser 的 1GiB cgroup 顶满。RSS 1,041,940KB、cache 6,636KB；仅 1 个 Python 约 22MB、1 个 Node MainThread 约 124MB，三个 Chrome renderer 各约 287MB。libuv-worker 触发 OOM，Chrome PID11725 被杀。不能据此宣称多孤儿探针堆积，也不能靠清文件缓存解释或解决匿名内存增长。

18:55 现场容器仍 running、StartedAt 保持 11:57；HTTP /json/version 200，而真实 CDP 连接 8.263 秒超时。8768 ready=false/login_attempts=0/order_probe_unavailable，现行 service SHA e94f54ce…；这是浏览器连接故障，证据不支持凭据失效。此时列表为三个 about:blank 页面，不能直接套用第三方商品页 Worker 泄漏归因。

线上 get 已有贯穿 spawn/wait 的串行锁、20 秒 TTL，health 不启动探针。可证代码缺口是仅宿主 subprocess timeout35，容器内 Python/Node 没有同样期限；宿主超时仅杀 docker CLI，不能保证远端进程结束。本次尚无多孤儿导致 OOM 的实证，修复应准确称为防残留。

最小 service 候选仅在原 docker exec 内加入 GNU timeout --signal=TERM --kill-after=1s 33s python3 -B；宿主 35 秒、TTL、锁、原身份校验、cookie 和权限保持。逆替换后全文件 SHA 精确等于 e94f54ce…。6 项本地/Linux 通过；原容器 GNU coreutils8.32 真实合成试验中，忽略 TERM 的父子同组进程在两秒后返回 137，两个 PID 均消失。测试没有连接 Chrome、请求 cookie 或采集业务。

恢复脚本复用原 business idle、队列/写锁、isolation 锁、srv_exec.lock、同容器/StartedAt/service/profile CAS；已有原回执拒绝重放，失败记 UNKNOWN。主 Agent 已执行一次原容器恢复：新 StartedAt19:00:46.269976722，19:01:08 原 8768 upkeep 验证 ready/login0；profile 保留，没有读取或导出 cookie。原回执为 `/var/lib/fs-order-session/order-browser-oom-recovery-20261023-v1.json`。

主 Agent 报告防残留 service 89e8b6bb… 于19:07:21原发布器上线，并在真实 ready 与持久化 profile 验证后更新原隔离 gate 的 service SHA。当前权威版本须读最新 SOURCE-MAP/现场，不能重跑原恢复脚本或用旧隔离 SHA 阻断 FC 维护。

余项：恢复后按原探针周期检查 renderer RSS、Documents/Nodes/JSHeap、页面/Worker 数量及真实 CDP；不把 JS 堆小等同匿名内存无问题，不凭空清理空白页或延长 cookie 有效期。原内存子 Agent 正只读核查，本模块不新增 timer、自动登录或破坏性自动重启。版本及检查见 [`SOURCE-MAP.json`](../../../order_browser_probe_recovery_20261023/SOURCE-MAP.json)。

## 19:21 utility world 机制实证增量

原内存子 Agent 的 raw CDP 两次只读观察为19:21:20与19:21:42：同四个 about:blank 页逐页 utility world 数量均57→58，原57个随机world名全部仍在，新增1、移除0。观察器仅 Target.attach/Runtime.enable，没有启动 Playwright driver、createIsolatedWorld、addScript、evaluate或导航；新增对应原20秒探针自然一次。因此已证实长寿文档保留旧随机 utility world，并随原周期持续增加，不能再仅称源码猜测。

安装coreBundle SHA为549070af3acabb3efcc4f55bfe6210f9f7c2fcf633cf7eaa59bfe60719969171。createGuid使用randomBytes16；SDKObject/Page生成新guid；CRPage使用`__playwright_utility_world_${this._page.guid}`，在noDefaults分支外createIsolatedWorld并添加空的新文档脚本，未追踪该identifier。断连仅清理本地监听/session，没有对应world显式销毁；这与实际旧world驻留相互印证。

此前19:08:54→19:10:32→19:12:10，同四页Documents1/Nodes4未变，逐页JSHeapUsed约4.40→5.25→6.27MB，原始cgroup用量253,124,608→258,449,408→265,932,800。该序列包含原探针和三次受控观测，单靠它不能分摊全部内存；19:21的raw观察避免了额外driver污染。现已证持续累积机制，但尚不能把18:43整1GiB匿名内存全部唯一归给它。

镜像现有Node v24.21.0、内建WebSocket及原utilsBundle.ws可用；Python3.10.12没有websocket-client/websockets，未安装新依赖。后续避开每轮browser attach须完整保持原HTTP CookieJar/Set-Cookie回写、删除、Domain/Path/SameSite、身份核验与12+8秒预算；不以未经回归的新认证实现换取内存下降。原raw world名和协议记录保留于私有`.agent_runtime/order-memory-20261023/raw-worlds.json`，对外只投影计数/集合关系/指纹。
