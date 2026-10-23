# Order 探针执行环境累积修复

状态：19:53:29 已由主任务统一发布，原 native upkeep 真实 ready=true、login_attempts=0、probe_seconds=1.481；37 项隔离 Linux 检查通过。浏览器未重启、profile 保持。活动源及 SHA 见 `order_worldless_probe_20261023/SOURCE-MAP.json`。原基线为 `89e8b6bb…c0353`，不能用早期 e94 覆盖；执行环境不再增加和长期内存仍须自然观察另验。

## 已证实与归因边界

原 8768 每 20 秒创建新的 Playwright 浏览器连接；该版本为每个页面加入带随机名称的 utility world，断开后未移除。19:21:20—19:21:42 的纯 raw CDP 观察中，同四个空白页均由 57 增至 58，原名称及执行上下文 ID 全保留。详见 `ORDER-WORLD-READONLY.md`。观察器没有创建 world。

这证明原探针持续累积执行环境。18:43:13 的 1 GiB cgroup OOM 已有内核证据；未将整次 OOM 的全部内存归因于该机制，未声称找到每一份内存的分配函数。19:00 原容器受控恢复、19:07 进程组超时补丁的原回执保持，不重放恢复。

## 最小改动

- 服务只替换探针源码和执行命令：原 Node 24 运行独立 helper，显式 `node - --order-probe`，避免 stdin 下 `require.main` 不可靠而无回包。helper 在服务启动时从同目录读取，不复制认证材料。
- raw 浏览器连接仅用 `Browser.getVersion`、`Target.getBrowserContexts`、`Storage.getCookies`、`Storage.setCookies`，不接入页面，不启用 Runtime，不创建执行环境。
- HTTP 保留原 Playwright APIRequestContext 的 CookieJar 和 Set-Cookie 解析；独立 CookieJar 使用 Chrome 原 User-Agent。已核安装源码：旧浏览器上下文使用浏览器 UA，独立默认 UA 则不同，因此必须显式传入。
- 原身份路径、HTTPS/主机/状态/退出链接/密码输入框判据不变。保留 12 秒及 8 秒两次运输预算和 20 跳重定向上限。使用同一个 CookieJar 逐跳检查响应头，避免 Partitioned 在中间 302 被库静默丢失；总预算包含全部跳转。
- 先比较 seed 后 CookieJar 与 HTTP 后 CookieJar，避免默认 SameSite=Lax 造成无变化误写。仅 Order 域和实际变化的 name/domain/path 键参与提交，保留 priority/sourceScheme/sourcePort；删除只对原键设置过去的到期时间，不清全库、不延长原会话期限。
- 提交连接重读 Cookie，并与初始全属性比较；发现同键并发变更即拒绝，不覆盖。单次提交后真实读回变更/删除结果。分区 Cookie 及无法保真的属性显式拒绝，不降为普通 Cookie。

原单飞锁、20 秒 TTL、HTTP health、UID、Unix socket、33 秒容器进程组 TERM/加 1 秒 KILL/35 秒宿主期限保持；不登录、不改 profile、不触发改价或新调度。

CDP 没有服务端条件写命令。本实现是同一提交连接的乐观比较、单次提交与读回；能拒绝已观察到的冲突，不能将其宣称为覆盖所有外部 Chrome 客户端的原子 CAS。跨消费者强原子写入需要所有 Cookie 写入者共同遵守互斥合同，不能由此 helper 单方面保证。

## 验证

2026-10-23：11 项 Python、26 项 Node 在隔离 Linux 环境全部通过，无跳过。测试容器使用原镜像、原 Node 24.21.0/Playwright 1.63.0，网络禁用，仅合成本地 HTTP 服务，不连接生产 Chrome、Order 后台或会话。CI 缺少原 Playwright 依赖、或 stdin 测试未明确声明隔离环境时直接失败，不跳过或探测现场端口。另已真实加载原 b811b3ad 发布器在临时目录核新文件原子发布及权限/UID/GID 保持，无生产目标修改。

覆盖：服务其他 AST 守恒；单飞与 health 不阻塞；TTL；进程组期限；真实 stdin 入口；身份判据；Cookie 值/到期/会话/删除/Domain/Path/HttpOnly/SameSite；优先级/来源属性；并发值或属性冲突；分区拒绝；原 HTTP 302 与 Set-Cookie 解析；每跳分区响应；Chrome UA；20 跳/总超时；失败与资源释放；禁止页面连接和清全 Cookie 命令。跨 Python 版本 AST 空字段差异及测试 URL 常量遮蔽已修正，原失败未作为通过证据。

另一次生产纯 raw 只读检查仅输出字段名集合、数量和分区存在性：当前 3 个 Order Cookie，13 个已支持字段，无分区，候选形态校验通过；没有输出 Cookie 值或修改 Cookie。

## 发布与自然验收

主任务使用原发布器、原业务互斥、精确基线 CAS 和备份完成两目标发布：helper 为 `53ee945a…13425`，service 为 `35b950f2…e76b0`。新文件由现成 FC `publisher.publish(source,target,info)` 先交付，服务再由原 Order 发布器交付。短暂停止的原空闲 RPG executor 已在 finally 解锁后恢复；未杀活动单、未重启浏览器、未清 profile 或登录。仅在原 native upkeep 真实 ready/login_attempts=0 后，增量更新原 isolation 回执的 service/helper SHA，旧耐久证明保持。

首次发布发现旧 Order 字典发布器对新 helper 执行 `path.read_bytes()`，以 FileNotFoundError 在第一次新文件读取处失败。主任务原 ID 对账确认服务仍 89e8、helper 不存在、isolation 字节未改、executor 已恢复；没有盲重试。修正适配器后，仅以显式 `--resume-verified-prewrite-failure` 在精确原 OP/unknown/FileNotFoundError/基线 SHA/helper 不存在/原 proof 哈希相同的条件下续接；原 operation、started_at 及完整失败保留于同回执的 initial_failure。错误类型不同、部分已写、来源/proof 漂移或已有续接均拒绝。原回执为 `/var/lib/fs-order-session/worldless-probe-recovery-20261023.json`。该发布错误没有业务价格写入。

原 native 健康已通过。后续等待旧在途探针自然退出，再沿同 container/StartedAt/同 target 的两次 raw 观察跨越原 20 秒周期，证明旧集合保留且新增为 0；不能用换页、重启或新文档归零冒充停止累积。原自然物品工单、21:14事务轮及长期内存趋势独立观察；当前本文件不声明这些后续验收已完成。


20:01后验增量：19:57:09.539→20:00:59.144，同原4页每页144个utility world及145个context名字/uniqueID集合完全保留，新增0/移除0；8个cached health点实际年龄回落两次，均ready/login0。容器、StartedAt、双SHA均不变，读后RSS317808640→317042688字节。详ORDER-WORLDLESS-POSTCHECK.md/json；只证明此窗口停止增加，不称12轮长期完成。


## 20:12父域Cookie兼容补丁

主Agent收尾审读发现首版只将exactOrder域Cookie带入独立Jar，原BrowserContext.request还会带合法父域.p2pah.cn Cookie；父域会话轮换/删除会被首版过滤。当前ready不能替代此兼容性证明。已最小补齐请求Jar/差分/CAS/读回的合法父域域Cookie，父域host-only不发送到子域，最终发给原调用方仍只exactOrder根路径。原请求同父域跳转设置Partitioned父域Cookie明确拒绝，原身份/UA/预算/20跳/锁保持。

14Python+30Node共44项在原镜像隔离Linux全过，无skip，含真实原APIRequestContext通过仅回环的合成CONNECT代理核父域发送/刷新/删除/HostOnly不泄露、原属性/CAS/终端输出。首次该测试未提供CONNECT响应而失败，已修测试代理合同，原失败保留，生产源不因测试失败而放宽。

20:12:11沿原publisher/CAS/空闲锁发布helper-only 53ee→0368c010，service35b950保持；原broker加载新helper后native ready/login0/probe1.571秒才更新proof helperSHA。浏览器/container/StartedAt/profile保持，空闲executor恢复，未中断在途任务、未采价或写价。原19:57–20:00的144→144证据仅绑定首helper53ee，最终0368版本的同页原周期证据另记，不冒用旧版验收。回执ORDER-WORLDLESS-PARENT-DEPLOYMENT.json。
