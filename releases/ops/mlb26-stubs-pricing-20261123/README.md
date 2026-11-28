# MLB26 Stubs 小时报价预览

同一 UTC 小时只保存一份预览回执。PlayStation 和 Xbox 逐平台采集 Eldorado 的首推卖家，Switch 使用 PlayStation 的同一目标。187 读取失败时，仅给该平台请求一次已配置的 183 补采。明确的来源访问拒绝单独记入回执。

取得 IGGM 授权报价后，`--iggm-receipt` 读取当轮 USD 报价。来源、商品及可购买数量必须一致。Eldorado 有有效首推时，从该卖家可售的数量范围内挑选 IGGM 最小可比档。只有 IGGM 时使用当轮最小有效购买档。比较 `min(Eldorado, IGGM × 0.8)`。缺一家用另一家，两家都缺则该平台输出空目标。站内赠送沿已确认口径另计。

## 一次性验收

在对应节点的 Python / Playwright 环境执行：

```sh
python3 -B -m source.cli preview --state-dir /var/tmp/mlb26-preview
python3 -B -m source.cli backup PS
```

已安装 Google Chrome 的环境可追加 `--chrome`。在 187 调用 `--primary-worker` 时，主控只需要 Python。仓内 `bin/collect187.sh` 调用现场已核的本地浏览器镜像，由 `MLB_BROWSER_IMAGE` 指定其镜像 ID。在独立的临时容器中执行，代码挂载只读。

`--backup-worker` 接受部署方配置的绝对可执行路径。固定调用参数为 `PS` 或 `XBOX`，通过获准的隔离传输在 183 执行 `source.cli backup` 并返回单条 JSON 回执。主控核对节点、平台、币种、时间及可购库存。183 的运行身份与传输由实际授权配置。

`--iggm-receipt` 使用以下字段。每行包含当轮 `observed_at`（带时区）、正数 `purchase_k`、美元字符串 `total_usd` 和可追溯的 `reference`。由获准的供应方接入写入该文件。

```json
{"source":"IGGM","product":"MLB26_STUBS","currency":"USD","offers":{"PS":[],"XBOX":[]}}
```

`--order-snapshot` 接受现有 MLB `mlb.coins_rate` 的实际只读结果。预览核对游戏、USD/1K 及三条区服行，并单独列出旧值、目标及按目标售价 75% 折算的供货结算单价。Order 快照比对有自己的读取时间。真实写入和 Admin、MMOEXP 主站读回单独验收。

## 小时运行候选

`fs-mlb26-stubs-preview.timer` 和相邻 service 定义只读预览。源码安装位置为 `/opt/fs-mlb26-stubs-pricing`，本机环境文件为 `/etc/fs-mlb26-stubs-preview.env`。代码目录对独立浏览器用户可读，访问资料和运行回执放在代码目录外。

环境变量包括 `MLB_PRIMARY_WORKER`、`MLB_BROWSER_IMAGE`、`MLB_BACKUP_WORKER`、`MLB_PREVIEW_DIR`、`MLB_IGGM_RECEIPT` 和 `MLB_ORDER_SNAPSHOT`。主采执行文件需要执行权限。定时上线与真实写入按各自验收结果推进。
