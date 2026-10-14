# FC 金币 ALL 镜像：写后回读改为有界只读重试

`coin_all_sync_job.py` 在把已确认的 MMOEXP 金币价镜像到 ALL 站点兜底商品时，
每一步 POST 之后只读一次就下结论。后端在写成功后会短暂继续返回写前那一行，
这一读就会拿到旧值，于是**已经落地的写入被判定为 mismatch**。

## 现象

一次自然周期在镜像 ALL 时以 `coin_all_readback_mismatch` 中断：

- 该步 POST 实际返回 HTTP 200 / `code` 1（明确成功）；
- 紧接着的一次回读仍是写前的单价；
- 判定失败后执行记录落到 `PARTIAL` / `needs_reconcile`，后续平台从未执行；
- 独立监控据此登记 `unknown_operation`，写价门禁转为 containment，
  自动周期被停住（写后失败不自愈）。

同一文件里另两处确认早已使用多轮读：`wait_sources` 要求两轮稳定读（45s 上限），
`confirm_timed_out_write` 对可能的超时落地写同样要求两轮稳定读（30s 上限）。
只有写后这一步是单次读。

## 改动

只动 `drive()` 一处判据来源，并新增一个只读确认助手：

- 新增常量 `READBACK_STEP_SECONDS = 30` / `READBACK_TOTAL_SECONDS = 45` /
  `READBACK_INTERVAL_SECONDS = 3` / `READBACK_STABLE_ROUNDS = 2`。
- 新增 `verify_dispatch_readback()`：对刚派发的 ALL 商品做**有界只读**重读，
  直到连续两轮都匹配已确认的 MMOEXP 源才判定确认；期间只发 GET，
  **绝不重发价格 POST**，并把每轮证据写进账本（`rounds`、`row_sha256`、
  `price_posts_retried: 0`）。
- `drive()` 里 `step['changed']` 的步骤改走该助手；`changed` 为假的步骤
  仍是一次读（没有写入，不存在传播延迟）。
- 预算耗尽只停止等待，不降低最低证明（仍完成两轮稳定读），
  因此共享预算用尽时不会把已落地的写入误判为失败。

判据本身没有放宽：`verify_step()` 的 AST 与线上完全一致，
`unchanged()` / `read_row()` / `api()` / `plan()` / `validate()` /
`wait_sources()` / `confirm_timed_out_write()` / `resume_synchronize()` /
`mirror_confirmed()` 全部 AST 一致（见 evidence）。镜像范围、写入字段、
六商品回读后置条件、对账通道与"POST 绝不重试"的既有约束都没有改动。

预算按写价器的运行时包络取值：整个 ALL 镜像通常远低于 20s，
而写价容器对这一步有 130s 硬超时，因此最坏情况（共享 45s 全部用尽）
仍留有充分余量；单商品不超过 30s。

## 验证（全部真跑）

- `test_readback_retry.py` 9 项，Python 3.9.25，纯标准库、零网络、零子进程：
  - 首次回读为旧值 → 重试后确认，且每个变更商品**只 POST 一次**；
    账本记录 `[False, True, True]` 三轮、`price_posts_retried == 0`；
  - 始终为旧值 → 有界停止（≤12 轮）并失败，**后续商品一次都没 POST**，
    执行记录落 `needs_reconcile`；
  - 行在两值间抖动 → 永不确认，且始终没有 POST；
  - 首读即匹配也要求两轮稳定读；预算被 `READBACK_STEP_SECONDS` 封顶；
  - 预算为 0 仍完成最低两轮证明；
  - `changed` 为假的商品只读一次、无 `dispatch_readback`、不 POST；
  - 规划后源价被改动 → 任何 POST 之前即停；
  - 后端拒绝写入 → 报 `coin_backend_request_rejected`，不重试、不掩盖。
- AST 作用域证明：仅 `drive`、新增助手与 4 个常量变化，其余 18 个定义 AST 一致。
- 差异仅 4 个 hunk（+71/−2 行）。

## 生产恢复（与本次代码改动分开执行）

线上已在**原锁/CAS/备份**约束下完成对账与补齐：对已落地但未确认的商品做只读确认、
对待写商品做一次受控补写并写后回读、账本转 `confirmed`、执行记录转 `CONFIRMED`，
随后调度自行放行重试周期并转为 `confirmed`，独立监控从 containment 经
`recovery_confirmation_pending` / `AWAITING_CYCLE` 回到 `RECOVERED`，
`unknown_operations` 为空，Player 同步同周期完成。

## 未做

- **本包含源码与离线用例，尚未部署**；替换线上
  `/opt/fc27-cloud-browser/coin_all_sync_job.py` 属另一批，需单独的窗口与授权，
  并沿既有受控发布通道（CAS / 备份 / 原子替换）。
- 未改判据、未扩大镜像或写入范围、未改配置/策略/调度/价格公式。
- 未补跑历史失败周期、未清 `unknown`、未重启业务服务。

实际 job、价格、配置与运行输出留本地忽略目录，不入库。
