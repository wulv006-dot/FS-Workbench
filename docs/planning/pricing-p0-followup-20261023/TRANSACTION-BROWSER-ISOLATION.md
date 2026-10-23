# 事务采集浏览器故障域隔离（2026-10-23）

状态：主 Agent 于 19:16:52 沿原锁/CAS/publisher 发布 collector891990/runner4f694。此前原 19:14 事务轮先取得锁，发布检查仅拒绝且未写意图，该轮仍旧共享 FC 浏览器，并于19:15:21失败137；原失败保留，不手动重跑。下一原21:14事务自然轮待验。本地/Linux 各15项及无Chrome/cookie环境烟测通过，不能称为完整自然采集验收。版本见 [`SOURCE-MAP.json`](../../../transaction_browser_isolation_20261023/SOURCE-MAP.json)。

## 已证实的关联及边界

原 `fs-transaction-collect.service` 于 17:14:04 启动，执行 primary_reader。17:14:38 原 FC 实际 CDP 检查失败；17:15:43 原恢复重启 FC 容器的同时，事务 reader 返回 container_reader_failed_137。137 是被恢复连带终止的证据，不能倒过来认作 17:14 失联原因。17:14 无新的内核 OOM 证明；订单页面/客户端和 FC 连接失联在时间上重叠，具体阻塞或分配函数仍未唯一定位。

collector 将 primary_reader、fc_category_reader、profit_daily_reader 放在 fc27-cloud-browser 内执行，并连接该容器 localhost:9226。线上启动脚本证明 9226 只是 socat 转发到同容器 FC Chrome 的 9225，不能把端口号误当作独立 Order 浏览器。独立 fs-order-browser 自身端口同为 9225。原 Cookie 入口虽已统一 8768，页面和采集客户端执行故障域仍留在 FC 容器。

19:14再次复现已取得带阶段真回执：原 event624b76be-b9fb-4fee-8bf4-e8113f70573e 的 transport_failure.reason 为 browser_connection_timeout:connect_over_cdp；不是 DOM 判据失败。19:14:55用量778,977,280/RSS465,575,936，OOMKilled=false；19:15:16以849MB和连接失败决定恢复，19:15:21重启连带旧reader137。首次空闲释放未验记UNKNOWN，19:16:17.648879同event实际释放验收，19:16/17原分钟监控恢复。仍无证据把这次说成3GiB OOM。

## 最小候选

仅替换 collector.call 的三种 Order reader 适配及三个直接调用方。Admin supplement_reader/fc_product_reader、原字段映射、原参数/结果/错误合同、原 900/600/可选利润预算、原 120 分钟 timer 与 collector.lock 保持。

每次 Order reader 使用原已存在镜像运行短生命周期进程，复用独立 Order 浏览器网络空间；不运行新 Chrome、不挂载 profile、不创建登录。只读挂载原 fs_order_client.py 和原 Unix socket，维持 UID11027/SO_PEERCRED 合同，cookie 仅由原共享客户端按原机制取得。三个 reader 的唯一 CDP 端点在内存中从旧别名 9226 精确改为独立 9225；其余源码与业务保护保持。

临时 Python/Node 与 FC Chrome、Order Chrome 分属不同 cgroup；单独 1GiB 客户端容量对照本次实测约 146MB 的 Python/Node 开销，完整批次容量仍待自然轮验收。原两个 Chrome 上限不提高。内部 timeout 和外部超时清理仅终止本次生成唯一名称的临时 runner，不删除任何浏览器容器。删除返回非零必须再 inspect 明确本 runner 已不存在；daemon 故障或其他删除未确认抛 cleanup_unverified，保留原超时上下文。失败继续原错误通道，不缩减来源或以旧数据替代。

活动 collector 含 247 个 CRLF，不能用全 LF 审核副本直接覆盖。prepare_candidate 对原 raw SHA 做 CAS，仅按四处锚点生成，保留未改行字节；生成后归一化全文必须精确等于冻结审核源。原 raw 08b4ca60…，实际生成 891990d1…，新 runner 4f6942ca…；全文 SHA 见 SOURCE-MAP。

## 检查及发布验收

15 项覆盖全部调用方、Admin 不变、参数/预算/错误保护、只读挂载、原身份 UID、无 profile/cookie 载荷、超时清理仅本 runner、缺资源拒绝、混合换行及基线漂移拒绝。真实临时环境仅 import 验证原 helper/Playwright/Unix socket 与 UID，未连接 Chrome、未请求 cookie、未运行业务采集。

首烟测发现缺少 docker -i 导致 stdin 没有执行，已修复并加回归；其次烟测未采用原 reader 的 sys.path 启动段导致 import 失败，按真实启动合同修正检查后通过。原失败保留，不把空 stdout/返回 0 当作成功。

发布仅两文件，原 collector.lock 空闲及原 publisher/CAS/备份串行执行，不重启或移动原 timer。新原自然轮须核全部必需 primary、原 snapshot/阶段结果、实际使用独立 runner、原 FC CDP/Worker 健康、Order 健康、退出后无临时容器残留。失败按原 ID/原错误定位，不强制重复采集。
