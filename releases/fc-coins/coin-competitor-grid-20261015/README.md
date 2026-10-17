# FC27 金币工作台：竞品卡片栅格不再错位 + 恢复成本口径说明

`/dashboard/fc27-coins.html` 的「最近一次完整竞品采集」区，**列 = 一家竞品**
（Lootbar / IGGM / U4GM / U7Buy），**行 = 一个区服**（PS / XBOX / PC），
栅格是 `repeat(4,minmax(0,1fr))`。旧渲染把卡片列表**按实到条目**排，
本轮 IGGM 未采到 → 只有 9 条 → 每个区服只出 3 张 → 第 4 列被下一个区服的首卡顶掉，
整块栅格错位。同时，页面上原先那段**成本口径说明**（P2PAH 发货记录 / 100K 优先 /
到手价公式 / 加赠口径 / 毛利率只计采购单价）在 2026-09-26 夜间的工作台改版中被漏搬，
页面上只剩表格、没有口径。

本批只做两件事，都不改判据、不改价格公式、不写价。

## 改动 1：渲染按「固定槽位」而非「实到条目」

`fc27-quote-cloud.js` 的 `#monitor-competitors` 渲染块（`+11 / −3` 行）：

```js
const gridSites=sites.concat(offers.map(row=>row.source).filter((source,index,list)=>
  sites.indexOf(source)<0&&list.indexOf(source)===index));
const offerOf=(platform,source)=>offers.find(row=>row.platform===platform&&row.source===source);
const slots=[];
PLATFORMS.forEach(platform=>gridSites.forEach(source=>slots.push({platform,source,row:offerOf(platform,source)})));
```

- 槽位 = `PLATFORMS × gridSites`，**与本轮实到条目无关**，恒为 3 × 4 = 12；
- 某槽位没有数据时渲染 `暂未获取` 占位卡（`本轮未采集到该来源` / `未纳入本轮比价`），
  后面的卡片**不再上移**，列序恒定；
- 固定四家之外的来源（将来新增竞品站）按**首次出现顺序追加为第 5、第 6 列**，
  不影响前四列的列位；
- 本轮**零采集**时仍走原来的 `尚无完整采集` 分支 —— 不用缺项或旧报价生成本轮建议价。

配套 CSS（`fc27-coins.html`，`+1` 行）：

```css
.monitor-competitor-card.missing{background:#f6f7f9;border-style:dashed;box-shadow:none}
.monitor-competitor-card.missing .monitor-card-value{font-size:16px;font-weight:700;color:var(--muted)}
```

> 窄屏断点（≤1100px → 3 列、≤760px → 2 列、≤500px → 1 列）是本页历史行为，
> **本批未改动**。这些断点下「列 = 一家竞品」的语义本来就不成立（已在页面上说明为窄屏自适应）。

## 改动 2：恢复成本口径说明（原文回归）

在 `#costs` 表下方补回一段口径说明（HTML `+1` 行，纯文本，无逻辑）：

> 成本口径：P2PAH 发货记录（FC27 / Game Coins），每个平台取交易时间最新的一条，
> 单位 ¥/1K；汇率取中国银行外汇牌价。各站优先取 100K 档，没有 100K 时取该站最低档；
> 每 K 到手价 = 付款额 ÷（购买 K + 赠送 K）。若我方套餐加赠，整单采购成本按实际交付
> K × 本次 ¥采购单价计算。毛利率只计本次采购单价，支付手续费、优惠券、税费和其他
> 履约成本未计，实际毛利可能低于表中数值。

这段原文来自 `共享资源/服务器/统一看板部署_20260915/fc27-coins.html`（2026-09-26
13:45:35 快照页，L51–L58），是与老大确认过的原始定义，逐字迁移、**未改写口径**。
其中「策略：低于可比最低价 1%，采购毛利率不低于 10%」一句是 **2026-09-28 之前的
旧策略**，已被 Lootbar 定锚 + 毛利分档取代，**故意未迁移**；
现行的 `毛利分档 · 目标降幅范围` 四档规则一直在页面上、未受影响。

> 澄清：**真实成本数据从未丢失**，也从未被删除。每轮采集照常从 P2PAH 发货记录
> 按平台取最新一条（本轮 `record_id` PS 4540206 / XBOX 4540176 / PC 4540180，
> ¥0.550000 / ¥0.550000 / ¥0.500000 每 1K），`#costs` 表一直照常渲染。
> 丢的只是**口径说明这一段文字**，本次补回。

## 验证（全部真跑，离线）

`tests/test_competitor_grid.cjs`（Node，零依赖、零网络、零子进程）
把候选 JS 里的渲染块用**精确锚点**原样抽出，在最小沙箱里执行，跑 5 个场景 22 项断言：

| 场景 | 输入 | 断言 |
|---|---|---|
| 真实 9 条（IGGM 未采到） | `fixtures/competitors-9.json` | 12 卡 / 3 占位 / 每区服 4 / 列序固定 |
| 四家全到 | `fixtures/competitors-12.json` | 12 卡 / 0 占位 / 每区服 4 / 列序固定 |
| 仅 1 家到（3 条） | 内联 | 12 卡 / 9 占位 / 每区服 4 / 列序固定 |
| 零采集 | 内联 | 0 卡 / 显示「尚无完整采集」 |
| 新增第 5 家来源 | 内联 | 15 卡 / 占位 2 / 前四列不动 |

抽取用精确锚点（`const offers=collection?.competitors||[];` … `尚无完整采集` … `</div>';`），
**源码一改测试立刻报错**，不会静默变松。原始运行输出见 `evidence/grid-*.log`。

其余静态校验：
- `node --check fc27-quote-cloud.js` 通过；
- HTML 结构校验（`frontend` 组）通过；
- 线上替换后逐字节回验：`fc27-coins.html` = `a34e06c8…`（26268 B）、
  `fc27-quote-cloud.js` = `acb59722…`（80029 B），与 `source/` 下两份**字节一致**。

差异合计：HTML `+2 / −1`、JS `+11 / −3`，见 `evidence/*.diff`。

## 已部署状态

**本批已部署到线上（与源码包同一批）**，与 `coin-all-readback-retry-20261014`
（`notDeployedByThisPackage: true`）不同。

| 文件 | 线上路径 | before | after |
|---|---|---|---|
| `fc27-coins.html` | `/var/www/dashboard/fc27-coins.html` | `a93423ca…`（25447 B，mtime 2026-10-07 22:01:45） | `a34e06c8…`（26268 B） |
| `fc27-quote-cloud.js` | `/var/www/dashboard/fc27-quote-cloud.js` | `fd66de70…`（79139 B，mtime 2026-10-09 10:01:30） | `acb59722…`（80029 B） |

- 主机：`47.85.224.112`（`play187`，CentOS 7），`/var/www/dashboard/` 由 nginx alias 直出；
- 原子替换 `install -m 644 -o root -g root`，替换前后各算一次 sha256；
- 备份：`/var/lib/fc27-cloud/rollback/fc-coin-competitor-grid-20261014T164008Z/`
  （改动前）与 `…T165549Z/`（文案前）；
- 回滚 = 把对应备份目录里的同名文件按 `install -m 644 -o root -g root` 覆盖回去，
  **无需重启任何服务**（静态资源，`?v=` 版本戳已同步更新为 `20261015-competitor-grid`）。

## 未做

- 未改判据、价格公式、毛利分档、成本取数逻辑、写入范围、调度、配置与凭据；
- 未碰 `fc27_quote_engine.py` / `automation_policy.py` / `snapshot_layer.py` / API / Worker；
- 未处理窄屏断点下「列 = 一家竞品」的语义问题（历史行为，待产品决定）。

## 溯源（为什么会「少了成本说明」）

- 那段说明**只存在于** 2026-09-26 13:45:35 那份**静态快照报告页**
  （`共享资源/服务器/统一看板部署_20260915/fc27-coins.html`），不是工作台产品线的组成部分；
- 门户 nginx 访问日志：**2026-09-26 13:47:08** 该页仍在线（200）；**2026-09-27 00:12:00**
  已是带 `fc27-quote-browser.js` 的新工作台 —— 换版窗口 = **09-26 13:50 → 09-27 00:12**；
- 此后三层历史副本（门户 2 份 + 187 `rollback/` 85 目录/110 份 + 本仓库 10-05 导入版）
  **没有任何一份**再包含该段 ⇒ 属于改版时的**口径漏搬**，不是删除动作，
  也不存在「成本数据被删」这回事。
