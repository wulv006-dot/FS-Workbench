# Admin统一8767：生产部署记录

2026-10-21，用户明确授权“部署好，后台凭证统一使用FS全局8767，关闭旧独立凭证获取服务”。负责人为当前Codex执行方；生产写入串行。现行私库HOTFIX已从main核对，允许业务已授权的受控发布先行、再补PR；未依旧历史候选整包覆盖。

## 已部署范围

| 对象 | 已执行 |
|---|---|
| sales | 部署已交付补丁，移除独立Admin登录、缓存token回退/落盘和源码凭据默认值；复用既有root/0600 `/etc/sales-dashboard.env` |
| NBA | login/ensure_token改读8767，每次Admin请求取当前全局token，不再读本模块token文件或凭据文件；拒绝独立登录/续期路由 |
| MLB Admin写入客户端 | 原login_with_ocr保持调用/返回合同，实际改读8767；请求头取当前全局token，拒绝独立登录/续期；未执行任何业务写入 |
| FC商品包vendored客户端 | 与MLB同一原始字节、同一增量；业务价格、锁、队列、回执保持 |
| SBC | login改读8767；authenticated真实反映全局会话可用性，每次鉴权请求更新全局token；禁用本地认证缓存保存/恢复，不改变FS角色检查和写权限 |
| 旧dashboard采集器 | do_login/ensure_token均只读8767，不再自行登录/续期；对应独立service停止并禁用 |
| 旧独立认证探测 | host脚本main直接拒绝探测；当前活动源未发现其容器包装调用或驻留进程。旧镜像/历史源码没有全仓删除 |

全局只读消费者代码：`/opt/fs-shared-session/shared_admin.py`，root所有、0644，无凭据文件；固定回环地址 `/session/admin-token`，不代理、不跳转、大小/类型/控制字符校验，一次读取、不重试、不日志输出token。sales使用其collector目录内相同字节helper。

FC Players另有现成Unix socket桥；已在活动容器以其真实python3解释器只读核对 `/app/player_web/shared_session.py` 确含 `/run/fs-player-session/session.sock`，无password登录调用。本轮保留既有992身份限制，不改成对容器随意开放TCP凭据读取。

## Order边界

用户随后明确：“Order是否有统一的会话服务？如果有也统一一下”。当前systemd服务盘点及实际调用源显示，FS准确区间与交易读取复用 `http://127.0.0.1:9226` 的现有浏览器登录态；未发现向sales发放Order cookie的统一会话接口。D4的P2PAHClient为Order消费，CacheRefresher的login只核当前页面，并非另一个Admin密码登录器。因此本轮未新增Order认证服务、未迁移Order登录或复制cookie。sales仍保留既有Order登录，但在全局Admin不可用时，于Order登录前立即停止。

FS用户登录门户auth-portal、G2G token刷新等不属于P2PAH Admin凭证服务，未关闭。现有只读浏览器、业务采集器及业务策略也未因名称包含auth/collect而误停。

## 发布与读回

- sales操作ID `sales-shared-session-20261021-v1`；原字节备份与回执 `/var/backups/sales-shared-session-20261021-v1/`，目录0700、原源码备份0600。
- 跨消费者操作ID `fs-admin-single-owner-20261021-v1`；七文件原字节备份/候选/回执 `/var/backups/fs-admin-single-owner-20261021-v1/`，目录0700、文件0600。备份原件仅服务器保留，不导出。
- 受控维护源码 `/opt/sales-dashboard/maintenance/shared-session-20261021-v1/`；脚本先核SHA，再备份，使用真实Python3.9编译候选，锁内再次核对并原子替换，读回SHA。已完成操作不允许盲目重跑。
- SBC `/health` 在发布前为busy=false/running=null，商品包历史running/pending数量0；仅重载这两个常驻Python消费者，均无8767的Requires/Wants依赖。NBA/MLB按现有子进程方式加载，没有重启其业务服务。
- SHA及操作状态：同目录 `sales-deployment.json`、`admin-deployment.json`。sales活动SHA `f6a90024e5ac648fce96978cc31b3292768676669b1404aa466ed8227fb175b4`。七文件实际读回全部匹配。

## 验证状态

通过：8项本地合成测试；真实服务器Python3.9对sales两文件及七份实际候选编译；七份活动源码SHA读回；真实本机8767不可用时返回安全错误；部署后的取凭证函数在离线小环境中均失败关闭，没有执行原后台请求函数。未用降断言或吞错获取通过。

最终服务状态：

| 服务 | ActiveState | UnitFileState |
|---|---|---|
| fc27-p2pah-session | inactive | disabled |
| sales-dashboard-sync.timer | inactive | disabled |
| sales-dashboard-sync.service | failed（原失败保留、无运行进程） | static |
| dashboard-collect | inactive | disabled |
| fc27-sbc-tool | active | enabled |
| fc27-pack-bundles | active | enabled |

全程未发起后台登录、未恢复8767、未启动sales采集、未改密码/新建后台账号、未执行价格/上架/订单业务写入。副本规则：没有改写E工程原manifest收录源码或用其旧副本覆盖当前活动源；本次独立维护源及真实现场映射由上述增量/回执记录，不把旧bundle当当前运行快照。

未验：冷却后真实8767登录/身份、真实销售及各消费者业务读写、自然同步周期。最早考虑单次验证的时间仍为2026-10-22 11:30上海时间，不是已证实解封时间。恢复时先获准单次验证，通过后再恢复唯一全局会话和必要同步；不能直接拉起循环制造验收。

Git/CI历史：原create_commit曾因部署授权未明确包含Git提交被自动审批拒绝，已停止而未绕过。用户随后明确允许提交、PR及CI通过后合并；本次据此补交脱敏维护源与回执。现行pr-fast为本目录增加最小映射，直接执行原8项离线测试，不新增workflow、不放宽检查。最终PR/CI/合并回执另行读回。

## 2026-10-21 13:50 单次真实登录复验

用户后续明确要求服务器验证是否能正常登录，覆盖原“明天前不尝试”的时间安排，仅授权此次验证，不自动恢复循环。本次使用全局同一镜像与原只读配置，运行独立一次性容器；强制LOGIN_ATTEMPTS=1，且请求层额外限制登录请求最多1次，没有启动主服务或复制token。

操作ID `fs-admin-single-check-20261021-1349`，2026-10-21T13:50:30.870186+08:00结果：实际登录1次，login code=0，消息归类credentials_rejected，manager status=credentials_rejected，未进入身份检查。此次不是先前的one_day_penalty文案；不能据此断言密码已被修改，也不能宣布账号解封。一次性容器正常退出，没有第二次尝试。

随后仅在服务器内比对配置：全局配置mtime仍2026-09-27T22:41:41.686764+08:00；用户名符合原chenchao，sales与全局用户名、密码均相同且非空。仅输出布尔结果/时间/权限，没有输出密码、token或密码哈希。全局服务和sales timer仍inactive/disabled。

原明天11:30仅为早前预定最早点，不再作为完整冷却保证；本次请求是否重置惩罚未获后端证据。后续验证需核实后端账号状态后再明确安排，不自行重试或改密码。前文“全程无登录”描述原部署阶段；本段为后续本次明确授权的唯一登录。

回滚：保持旧认证service和sales timer停用；核对原operation/活动SHA后，单文件从对应受限备份回退。不得一边回退独立登录代码一边开放该消费者运行，不回滚DB/队列/价格/权限或删失败证据。新独立接口或服务以后仍需核对当前来源和8767消费约束，不能据本次有限盘点声称整机所有历史代码永久不会登录。
