# FC 双节点采集施工记录

范围：Business 在 FS-Workbench 独立分支实现 FC 采集合同、持久协调、有限 worker 和可关闭接线；183 默认隔离 Linux 测试，187 保持原调度、财务与唯一 FC writer。原 RPG 服务、隧道和身份不变。

基线：`8a681c90706a71cbf839b547a971f9c875558a2e`，分支 `codex/fc-dual-collection-20261102`。用户提供的 2026-11-02 v2 施工包为需求依据；旧 RPG 交接包“另建仓库”与当前指令冲突，不执行。

## 施工顺序

- [x] P0：读最新 main、HOTFIX、FC owner、活动 map，核对直接相关线上文件。
- [x] P1：先写失败测试，再实现纯合同与 SQLite 事务协调、租约、fencing、幂等回执。
- [x] P2 离线核心：共享来源预算、有限 HTTP 请求、worker spool 与隔离故障模拟；真实 browser 请求组、认证端点和现场 worker 仍未完成。
- [ ] P3：仅接可关闭的 ItemD2R 来源入口；默认 off，不替换 local_collection，不改价格与 writer。
- [ ] 验证：Windows、183 隔离 Linux、目标 Python 3.9、现行 pr-fast、独立审查。
- [ ] P4—P6：来源许可、预算和 adapter 实测后，提交准确的影子/消费/持续身份/通道变更清单，再按已有授权执行。

## P0 现场事实与缺项

2026-11-02 08:49 UTC 通过两个既有独立入口只读核对。187 八个核心文件的原始 LF 字节与 Git 完全相同：worker、snapshot、ItemD2R reader、ledger、selective_sources、scheduler、sources、financial。Windows 工作树 CRLF 的磁盘 hash 不能用于生产比较。

183：Debian 12，Python 3.11.2，systemd 252，NTP 同步；可用内存约 6.46 GiB，`/var/tmp` 空闲约 176 GiB，负载 0.01/0.10/0.15。d4follow、p2pah-srv-exec、rpg-db-lock-watch 和四个 RPG timers 为 active。未发现 Python 3.9 或已有专用 FC 测试目录。此为一次资源快照，不是浏览器容量验收。

187：Python 3.9.18，systemd 219。`rpg183-link.service` 已有 SSH 转发：187→183 的 8900 看板；183→187 的 8911/8912/8768、Order 会话 Unix socket 与 Order 443。没有 FC claim/renew/reserve/submit 端点。可复用 SSH 传输及维护方式，但不能直接把 RPG 业务端点当 FC 通道；新增受限转发或独立身份仍须具体授权，不重启共享隧道试错。

保护：`/opt/d4follow`、`/opt/g2gfollow`、RPG 三个服务/四个 timers、187 隧道、共享 Order 会话、cutover.active。183 已有监听包括 8900/9223/8911/8912/8913/8768/443；测试不用这些端口。

测试实际采用独立 `/var/tmp/fs-fc-tests-*` 临时目录和一次性 Docker 容器，UID/GID 65534、`--network=none`、只读源码和根目录、cap-drop ALL、no-new-privileges、CPU 0.25 核、内存/内存加交换合计 256MiB、64 pids、32MiB tmpfs、180秒总超时，低 CPU/IO 优先级。无需新主机软件、持续身份/服务或新端口，不挂载业务目录。一次性容器和展开目录退出后清理，官方基础镜像保留供以后复用。

缺项：生产 worker 专用身份/通道；来源许可和包含其他消费者的总预算；真实浏览器子请求白名单；最长请求/取消/时钟测量；183 目标 Python 3.9；RPG 源码归属 SHA 与已验证恢复器（后者由原负责人维护，不阻塞 FC 离线实现）。未定参数只用于显式合成测试，不能进入真实影子。

## 检查与裁决

- Windows 原基线 515 tests：5 failures、1 error、10 skips。六个失败均涉及字节锁定的 simulation source；先核 LF/CRLF 环境原因，保留原日志，不改 hash 常量或放宽断言。
- Ruling：新增协调状态使用独立 SQLite 文件和同样的 WAL/BEGIN IMMEDIATE/短事务方式；纯 worker 不导入业务 Ledger，183 不拿到生产表或业务运行时。
- Ruling：先提供受限传输接口与合成 adapter；未登记真实来源请求组前不开放任意浏览器或 URL。来源消费开关默认 off，原自动化保持。

完整现场输出与测试日志保存在本机任务目录，不将原始现场回执、连接配置或密钥入 Git。

## 已验证结果

- Windows：原 515 项在还原 Git LF 字节后通过（原有 10 项平台 skip）；新增 39 项通过，其中 37 项协议/故障/安全测试、2 项导出测试。全 V3 共 554 项通过，原 10 skip 保持并显式记录，不称 Linux 或生产验收。
- 183：37 项核心测试全部通过、零 skip，实际 Python `3.9.18 (GCC 12.2.0)`，Linux；镜像 `python:3.9.18-slim@sha256:aa7b73608abcfb021247bbb4c111435234a0459298a6da610681097a54ca2c2a`，本机 image ID `sha256:ef0f72a55bd28f9c7c439e127804e36a00fa47d0f84c90819788083a0efe86fa`。最终核心测试 ZIP SHA256 `403119dbc06b3ca58ae2a030e88cc019226237547529e09e0bf8febe964b23da`；容器运行约1.94秒。2项 Git/Node 导出检查在主PC执行，不混入上述37项。
- 独立审查确认的6项边界均已补失败复现并修复：DNS及响应阶段总截止、pending spool 崩溃恢复、primary 未领取前失联的接替、时钟偏差不得放长 permit、暂时失败保留有限重试、旧报价不得重新贴本次 run 标签。新增导出单元独立补审无 P0/P1/P2 问题。
- 183 测试后 d4follow、p2pah-srv-exec、rpg-db-lock-watch 仍 active，四个 RPG timers 继续原计划。没有改动或重启其服务、会话、隧道、配置或数据库。

## Lootbar 实现核查与复用

2026-11-02 09:12 UTC 只读核查实际容器及已有证据，无手工重采。187 现役源精确匹配 `releases/ops/pricing-recovery-20261023/fc_residency/source/`：

| 文件 | 现役/Git 原始字节 SHA256 |
| --- | --- |
| `lootbar_server_collector.py` | `4d19dcf18bf6705bbf6aa6590ca660a974f8e1d006b7b9bbd4bb0673f4f52103` |
| `background.js` | `4f36ad8a9723039912727f64bb6a3f20da0c657dc2a57105c4fb4d8faa6cf67b` |

根目录旧 collector SHA 不同，不能作为复刻基准。183 在本次限定的 `/opt` 目录、FC/Lootbar services 和运行容器核查中未发现 FC/Lootbar 实现；现有 qd-render 属 RPG，不借用其 profile。

现役逻辑复用已登录 Chrome，只提取自包含 `readVisibleOffer()`，逐平台三次稳定校验 USD/EN、100K、真实赠送和排除券后的价格，保留 PS 恢复及受控页面释放。最近8份已有回执均完成，耗时6.187—7.490秒；这是已有自然采集证据，不是183可用性或新请求组预算证明。保留65秒总读取上限及90秒外层进程上限，不据典型7秒随意缩租约或省略三次校验。

`deploy/build_collection_worker.py` 从上述精确 Git 活动源导出白名单代码：4个纯worker模块、Lootbar reader 和纯parser。完整 extension 含预览/storage handler，故仅提取原parser，未复制该业务代码。导出reader要求显式自有loopback CDP，取消默认9223并拒绝已知共享9223/9225；不带登录态、后台身份或配置。manifest 区分上游hash和实际导出hash，并明确 `production_ready=false`。没有改动187现役collector。

## 入口、验收和回退

主PC继续使用已有两个独立 `server_183/access/Invoke-Server183.ps1` 与 `server_187/access/Invoke-Server187.ps1`；真实参数见本机原README，严格host key保持，凭据不进入本包。

183默认测试入口为本目录 `deploy/test_collection_183.py`：用原183 Upload传入受限ZIP及脚本，然后 `python3 -B SCRIPT ZIP SHA256`。入口核白名单、大小、SHA、余量、固定本地镜像，零生产挂载；实际解释器不符、空测试、失败或skip均失败。新的ZIP需重新算SHA再执行。它只允许现有FC核心测试白名单，不是任意root脚本执行器。主PC打包检查继续在Windows进行。

现阶段没有生产接线、服务部署或消费开关变更，所以不需要回滚生产文件。隔离测试只清理本次随机命名且带专属label的容器及其临时展开目录。日后接线后的来源回退须先off并增generation，旧首次结果拒绝、已commit结果仅补历史ACK；原DB/租约/permit/预算/计划/UNKNOWN保留。这些状态机行为已有离线回归，真实入口回退和自然周期尚未执行。

## 剩余工作

P2真实browser请求组/总预算、187认证API与183独立身份/浏览器、P3原入口接线、P4影子、P5消费及P6真实接替/回退均未执行。初次现场服务、持续身份及现有隧道新增转发应按具体清单核授权；不因测试通过自动安装或接实盘。优先保持现役Lootbar逻辑，为183建立独立Lootbar登录态；不复制187全浏览器profile、不借RPG或Order凭据。尚无来源实测预算/最长请求取消/新浏览器资源证据，测试policy中的时间与请求数不得提升为生产参数。
