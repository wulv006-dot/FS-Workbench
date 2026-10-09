# FC27-20261009-public-readback-retry

已部署一份 worker 源码，修复改价后"公开页回读"被 CDN 边缘缓存时间差误判为发布失败的问题。北京时间 2026-10-09 18:45:37 以单文件受控发布器上线，12 份保护文件保持，服务健康与队列空闲均在发布时复核。

本文是证据入口，实际收据见 evidence/，不以文档代替上线验收。

## 目标与范围

修复自动改价周期中"后台写价已确认、公开页回读却记为未确认"的竞态。仅在既有严格判据外增加**有界刷新重试**，不放松任何判定、不伪造通过、不改业务参数、不新增依赖或 workflow。

仅修改 `fc27_cloud_browser/fc27_cloud_worker.py` 一个文件。

## 基线与来源

先核对真实工作源与宿主目标。工作源为原工程 `fc27_cloud_browser/fc27_cloud_worker.py`，宿主目标 `/opt/fc27-cloud-browser/fc27_cloud_worker.py`，运行根 `/var/lib/fc27-cloud`（由 `snapshot_layer.ROOT` 解析，非环境变量）。

GitHub 根 FC 仍 legacy-unreconciled；本 PR 回补专用 release 与精确 source→runtime 映射，不用本地旧副本覆盖根目录。

| 文件 | 发布前 SHA-256 | 发布后 SHA-256 |
| --- | --- | --- |
| fc27_cloud_worker.py | 6b5ba249e2d78ae06edf04085ced8bb057d4f6d3c308aecda9c78b8c0159a13d | 06c89b902726f1266bc9b97d236b7ae5b6299b9e1447fb03542151fa0f362b29 |

## 根因

当日 09:00 自动周期的证据链：

1. `09:00:47` 后台写价完成，ALL-coin-sync 确认 PS/Xbox = `$13.92`
2. `09:00:48` 请求清缓存
3. 写后回读**仅隔 1.1 秒**启动，此时 CDN 边缘仍返回写前的 `$13.71`
4. 严格比对失败 → `public_page_readback=unconfirmed` → 巡检门禁 `ESCALATED`（`published_price_unverified`）

独立复现：10:32:51 匿名只读公开价查询 PS/Xbox = **`$13.92`**，与后台一致 —— 证明写价**已经生效**，问题是**取数时机**而非发布失败。

对照同期任务：`ff748646`（PS+XBOX）与 `19727248`（PC）均 `verified`；只有紧接写价的那次 `5968cbe9` 落在缓存窗口内 —— 机制本身有效，仅时机不成立。

## 实现

原实现为单次读取 + 严格比对，失败即记 `unconfirmed`。改为有界刷新重试：

- 新增 `PUBLIC_READBACK_ATTEMPTS = 5`、`PUBLIC_READBACK_INTERVAL = 20`
- 严格比对逻辑原样提取为 `_public_page_match(job)`（**不放松任何判定**）：
  运行号须属本次、状态须 `ok`、每个选中平台的 `package_usd` 须与 `target_page_usd` **Decimal 精确相等**
- `verify_public_page(job)` 在有界预算内重试：未命中则 `refresh_storefront(job)` 后等待 20 秒再比对，最多 5 次
- 读取异常（`OSError/ValueError/KeyError/TypeError`）仍立即返回 `unconfirmed`，**不做重试**
- 成功时新增 `attempts` 字段记录命中轮次；耗尽预算仍返回原有 `unconfirmed` 判定

不改判定强度，只改"读一次就下结论"为"有界地多读几次再下结论"。

## 影响

现有 EN/USD、平台、100K 规格、赠送/折扣、成本/毛利与定价合同**全部保持**。未扩大任何自动重试白名单；未触碰写价路径、队列、锁、门禁或机器人。唯一新增副作用是：失败路径下每轮最多多 5 次公开页只读采集、最长约 100 秒，仅在需要时发生。

## 验证

隔离测试 `test_public_readback_retry.py` 共 10 项，全部通过，覆盖：

| 用例 | 断言 |
| --- | --- |
| 生产实况复现 | 首次读到过期缓存、后续读到正确值 → 最终 verified |
| 预算有界 | 重试次数不超过 `PUBLIC_READBACK_ATTEMPTS` |
| 分厘级不一致仍拒绝 | Decimal 精确比对未被放松 |
| 持续不一致仍 unconfirmed | 不因重试而放过真实失败 |
| 空选平台不通过 | `selected` 为空不判 verified |
| 平台键缺失仍拒绝 | KeyError 路径 |
| 非 ok 状态不可通过 | 状态判据保持 |
| 未选中平台不一致忽略 | PC 未选中时其陈旧值不得阻塞 PS/XBOX |
| 运行号不符不可通过 | `collection_run_id` 判据保持 |
| 读取异常不重试 | 立即 unconfirmed，避免掩盖真实故障 |

发布侧：`publish_worker.py` 在服务器端以 root 运行，`idle()` 核对队列/任务/执行均为空闲，对 13 个基线哈希逐一复核后，经 `flock` 排他锁 + 备份 + `os.replace` 原子替换 + 服务重启 + 健康等待 + 安装哈希与保护哈希复验完成上线。

## 发布与运行

2026-10-09 10:45:37 UTC / 18:45:37 北京，以单文件受控发布器上线。

- 收据：`{"status": "deployed", "installed_sha256": {".../fc27_cloud_worker.py": "06c89b90..."}, "protected_sha256": {...12 项...}}`
- 备份：`/var/lib/fc27-cloud/rollback/public-readback-retry-20261009T104536Z`（含原文件与 receipt.json）
- 发布时健康：api/worker/browser/p2pah_session 均 `ok`，六源 `ok`，`queue_depth: 0`
- 12 份保护文件哈希与基线**逐项一致**

## 交接与遗留

- 服务 `fc27-cloud-worker` 于 `18:45:36 CST` 重启，PID 24622 心跳正常
- 自动任务间隔 120 分钟，下一自然周期约 **20:00 CST**；需在该周期观察 `public_page_readback` 是否由 `unconfirmed` 转为 `verified` 方可认定修复在自然运行下生效。**发布成功不等于自然周期已验收。**
- 回退：停 `fc27-cloud-api`/`fc27-cloud-worker` → `swap()` 还原备份原文件 → 重启 → 复核哈希与健康；不回退数据、账本、队列。
- 本地 `fc27_cloud_browser/fc27_cloud_worker.py` 与线上字节原不一致（历史遗留），本次未用本地副本覆盖；GitHub release 目录以**线上真实字节**为准回补。

## CI 载荷基线（2026-10-09 19:2x CST 复述）

本 PR 的 `tools/pr_fast.py` 与 `.github/workflows/pr-fast.yml` **不基于本机旧副本**，而是以远端 `main`（`abd6f09a`）的真实字节为基线重新移植三处改动：

| 改动点 | 位置 | 内容 |
| --- | --- | --- |
| 1 | `select()` | 新增 `releases/fc-coins/public-readback-retry-20261009/` 前缀 → 分组 `fc-public-readback` |
| 2 | `selfcheck()` | 新增断言 `fc_public_readback_scope_missing`（紧随 `fc-noncore` 断言） |
| 3 | `main()` | 新增 `elif group=="fc-public-readback":` 执行器（`unittest.defaultTestLoader.discover` + `pr_fast.require_success`） |

原因：准备期间远端 `pr_fast.py` 被其他模块改动（新增 `fs-traffic-member` / `fs-period-ui` / `fs-metrics-fix` / `fs-admin-view` / `admin-entry` 五组，`units()` 增加 `root_owned` 参数）。若以旧副本提交会**回滚他人改动**，故重新移植。

移植后本地复验：`select()` 映射、既有分组不受影响、未映射格式仍拒绝、10 项 release 测试 —— 全部通过。

`pr_fast.py` 移植后 SHA-256：`457ac6bc9cc59799…`（远端基线 `90e069ce72f6089f…`）。

