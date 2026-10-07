# 注册增量 QA：统一权限合同与一次隔离验证

本修订仅涉及本目录三个 QA 文件，业务源码、角色策略、既有 workflow 与 pr-fast 映射不变。目标集成结果以本修订合并 SHA 对应的一次手动运行收据为准；静态检查与本地源码 HTTP 诊断均不能替代目标环境或真实 Nginx 验收。production_ready=false。

## 固定输入

源码 checkout 固定为 2152c8c9ea2fd68be3876349299d490d38903404。驱动校验 candidate-manifest.json 原字节、19 项 manifest 条目及 15 项既有 runtime 依赖，共 35 个输入文件，并校验干净 Git 身份与 runtime 子树。拒绝链接、路径越界、候选目录额外文件和脏输入；执行后重新核对。

config/example 仍是模板。旧入口所需的 47 项 reviewed-root/live-config 不是本入口输入，不读取或上传生产配置。原源码、历史清单和旧 43+4 结果保留，不重新执行旧套件。

## 统一权限合同

| 身份或状态 | 全局验证 | Taskboard | FC analysis GET/HEAD | 管理与写入 |
| --- | --- | --- | --- | --- |
| 既有 native admin：DY、chenchao、fstech、wulv | admin | admin | 允许只读分析 | 按既有 admin 合同 |
| 既有 native oldreader | readonly | 保留 editor 元数据；允许既有成员列表读取 | 允许 | 全局策略拒绝非 admin 写入和注册管理 |
| 新注册 pending | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| admin 批准后的注册账户 | readonly | reg:UUID、viewer；不加入 native members | 允许 | 成员列表、写入、请求管理和审计均拒绝 |
| 匿名、伪造、过期、旧 FC cookie、已注销 token | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| native 与真实注册身份冲突 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |

四个 admin 是冻结源中的既有名单，本修订不新增或移除管理员。FC 使用全局资格，不恢复旧独立账户库；analysis 是只读 JSON，不因名称被误判成 admin-only。旧 FC verify/管理/写入口继续按冻结源拒绝或退役跳转。

注册只读 query 使用允许键和值：mode=%76iew 是合法正例；probe=%2F、probe=view、mode=%2F 分别覆盖组合、未知键和非法值负例。真实 HTTP method 优先于来访者伪造的 X-Original-Method；直接来访者伪造身份头不得提高权限。

## 场景与收据

代码中的 CONTRACT_PLAN 是唯一可执行检查清单，按启动、native 角色、HTTP 登录、旧注销别名、注册审批、拒绝重申、只读边界、无效身份、旧 FC 退役、注销控制、Nginx、存储丢失、撤销、恢复和上游不可用分阶段。清单大小是细粒度检查数，不是独立测试数量。

- 注册、登录、审批、拒绝、重申、注销与撤销走实际 HTTP；正常操作之外检查 Origin、CSRF、版本冲突和非法字段
- 使用精确 HTTP 响应建立命名内存 cookie jar，保留多个 Set-Cookie；不得用初始夹具 token 代替被注销的实际 token
- native 注销只撤销当前 signed token，独立同名 session 保持；注册账户撤销推进 epoch 并失效其全部 session
- legacy logout GET/HEAD 跳转与 POST 405 不清 cookie、不修改存储，也不撤销当前 session
- recovery 保留数据库和 witness 字节，禁用注册 API，仍验证未撤销身份；旧 native login 按冻结源继续可用，不能使已撤销 token 复活
- 数据库丢失时 verify/直接 board 为 503、FC 拒绝、Nginx edge 为 5xx；不自动重建数据库。恢复及上游进程不可用另有检查
- Nginx 专用检查覆盖原生配置解析、HTTP→HTTPS、auth_request、真实 method/URI、身份头覆盖与实际 TLS 往返；trace 只匹配本次请求新增记录

每项记录预期/实际 status 和 role、断言布尔值与 PASS/FAIL/BLOCKED/NOT_RUN。前置失败只阻塞依赖项，独立项继续收集；超时或未执行绝不算通过。总 PASS 要求所有计划项通过、源码不变且自有进程和临时目录清理成功。收据不含 cookie/token/CSRF 值、请求响应正文、合成数据库、证书或原始服务日志。

## 执行

静态检查不导入候选、不读取源码 checkout、不监听网络、不启动 Nginx：

    python3 -I -B tests/registration-release-delta-qa-20261007/linux_delta_entry.py --driver-check

正式集成守卫无绕过开关，要求已具备 Linux、Python 3.9.18、SQLite 3.53.4、Nginx 1.26.1（auth_request/SSL）和 openssl；输出必须是不存在的新路径：

    LD_LIBRARY_PATH="$QA_SQLITE_LIB_DIR:$QA_PYTHON_LIB_DIR" "$QA_PY39" -I -B tests/registration-release-delta-qa-20261007/linux_delta_entry.py --source-root "$QA_SOURCE_CHECKOUT" --nginx "$QA_NGINX" --openssl "$QA_OPENSSL" --output "$QA_RECEIPT"

使用现有 .github/workflows/registration-target39-manual-qa.yml：用户在 main 手动选 mode=registration_delta，并确认至少 10 分钟免费额度。driver 绑定该次 github.sha，源码另 checkout 固定提交；禁止把 driver-check 当集成，也不重跑失败 run 刷绿。原 runtime43_multiprocess4 模式保持。

既有 workflow 使用只读权限、无持久 checkout 凭据、私有前缀构建和精确固定工具版本。运行于 loopback-only 网络及 PID namespace，降回 runner UID/GID；集成上限 120 秒，额外 15 秒清理宽限。控制器只清理自身登记进程组并有界回收，清理失败记 FAIL。

固定 2747 字节合成 Nginx fixture 仅连接自有 loopback 端口，TLS、目录、账户和数据均为临时合成输入，不包含生产 include。ContractRunner 可供独立源码 HTTP 诊断导入；这种诊断须如实标注本地解释器和未执行的 Nginx 项，不改变正式 CLI 守卫。

## 历史与未验范围

保留失败 run 37623684963（非法 query 被当正例）和 37630588766（把只读 FC analysis 错当禁止）的原始收据，不将失败改写为通过。本修订按冻结实现和统一权限合同整体校正 QA 预期，不修改业务权限。

本修订尚未在目标环境运行。生产 systemd loader、实际 UID/ACL、正式 TLS、真实账户角色、完整现场 Nginx/includes、fresh CAS 和发布锁不在本合成验收范围。production_nginx_verified=false、production_ready=false；通过该 QA 也不自动部署或扩大访问权限。
