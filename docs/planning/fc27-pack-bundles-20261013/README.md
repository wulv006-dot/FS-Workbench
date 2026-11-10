# FC27 捆绑包定价工具 · 一期交付（2026-10-13）

> 本篇保留10月交付及历史核算事实；当前执行口径、三平台独立美元报价与100K无赠基准见[现行维护入口](../../../fc27_pack_bundles_20261013/README.md)。下文旧共价/赠送示例不作为新执行规则。

> ★ 二期（同日追加）见文末「二期」节。

## 一句话
FS 工作台球类专区新增「FC27 捆绑包定价」工具：按 Futbin ID 匹配球员金币价 × 后台金币单价，
按腾讯文档《捆绑包》prices 表公式自动算出 PS/Xbox 与 PC 的**页面显示原价**与**折扣售价**，
采集间隔可配（小时），捆绑包标题/球员/ID 可在线编辑，手动+定时刷新。
**一期只读定价，不写后台**；二期（Admin 后台改价）待另批授权。

## 线上落点（47.85.224.112）
| 项 | 值 |
|---|---|
| 服务 | `fc27-pack-bundles.service`（enabled/active），`/opt/python39/bin/python3 /opt/fc27-pack-bundles/pack_bundles_server.py --port 8904` |
| 数据目录 | `/opt/fc27-pack-bundles/data/`（config.json / futbin_players.json.gz / last_refresh.json / history.json） |
| API 入口 | `https://47.85.224.112/dashboard/fc27-bundles-api/`（nginx auth_request 门禁，未登录 302） |
| 页面 | `https://47.85.224.112/dashboard/modules/sports/bundles/`（fs-home 壳，球类工作区卡片「FC27 捆绑包定价」） |
| 导航注册 | `/var/www/dashboard/fs-home/navigation.json`（sports.ids + tools 追加 `fc27-bundles`，备份 `.bak-bundles-20261013`） |
| nginx | `iggm-web.conf` 注入 `fc27-bundles-api` 块（备份 `.bak-bundles-20261013`，注入锚点 `# <<< unified-dashboard (auto) <<<`） |
| 回滚 | 还原两个 `.bak-bundles-20261013` + `systemctl disable --now fc27-pack-bundles` |

## 数据链路（全部实测）
1. **Futbin 库**（老大自建 `http://139.28.18.234:8001`）：`GET /api/export/players.json`
   gzip 全量（下载 2.2MB / 23086 球员 / 线上实测 2.1s）。按 `futbin_id` 建映射；
   字段 `ps_price / pc_price / xbox_price`（金币原值）。
   ⚠️ 库内 xbox_price 大多为 null → **PS/Xbox 共用 ps_price**（与腾讯文档口径一致，已实测腾讯文档 22 个 ID 全覆盖）。
   采集节奏：库自身每 60 分钟刷新。
2. **金币单价**：`/var/lib/fc27-cloud/monitor/storefront.json` →
   **⚠️ 口径纠正（2026-10-13 17:41 老大指出）**：单价 = `package_usd ÷ base_k`
   （页面标价 ÷ 标称金币量），**赠送 bonus 金币绝不能摊入**。
   storefront 自带 `usd_per_k` 字段是 `package_usd ÷ (base_k+bonus_k)`（如 12.57÷105=0.1197），
   会把单价压低——**不要直接用**；工具改为自算 `package/base_k`（12.57÷100=**0.1257** ✓），
   字段缺失才回退自带值并标注 `includes_bonus`。
   （实测当时 PS/XBOX 0.1257 / PC 0.0994=9.94÷100 $/K；PC 老大前台看到 0.094，
   与采集值 9.94 存在时间差或档位差，待核对。）
3. **计价公式**（腾讯文档 prices 表逆向，单元测试逐分对齐 ManCity11 行）：
   - 球员页实际售价 = 金币K × 单价 × **1.1**
   - 球员页划线价 = 实际 ÷ **0.9**
   - 捆绑包页面售价（商品页红价）= Σ球员划线价 × **0.8**
   - 捆绑包页面原价（灰划线）= 页面售价 ÷ **0.7**（角标 30% OFF）
   - 对比实际让利 = (售价 − Σ实际) ÷ Σ实际（恒 ≈ −11.11%）
   - 中间链路 Decimal 不舍入，仅展示 2 位小数；系数可在 settings 调整。

## 接口（应用层，前置 nginx 门禁）
- `GET /health` / `GET /api/state`（整状态+实时算价）/ `GET /api/search?q=`（球员搜索选人）
- `POST /api/config`（`{expected_revision, settings?, bundles?}`，revision 乐观锁）
- `POST /api/refresh`（后台线程刷新，进行中返回 409）
- ⚠️ 应用层对 POST 额外要求 `X-Forwarded-Proto: https`（与 MLB 同款约定）

## 刷新机制
- 服务内置调度线程：每分钟检查距上次刷新是否 ≥ `interval_hours`（默认 1 小时，可 0.1~168）；
  服务启动 60 秒内自动跑首轮。
- Futbin 拉取失败不致命：沿用旧缓存继续算价，errors 记入 last_refresh。

## 本地任务目录 `fc27_pack_bundles_20261013/`
- `src/pack_bundles_server.py`（28,492 B / sha256 前 16 位 `69c5102171285b1e`）
- `web/index.html`（16,413 B / `a5b04bd369f3335d`）
- `tests/test_pack_bundles_offline.py` —— **14/14 通过**（公式对齐腾讯文档 ManCity11：
  PS 20.77/29.67、PC 13.74/19.62；校验器/revision/缺价兜底）
- `deploy/inject_nginx.py`、`deploy/update_nav.py`（部署注入脚本，幂等）
- `evidence/`（fb_players_sample.json.gz 样本、上传计划、冒烟日志）

## 已验证
| 项 | 结果 |
|---|---|
| 离线单测 | 14/14 OK（公式与腾讯文档数字逐分一致） |
| 本地端到端 | 真实 Futbin 数据 + 模拟单价：ManCity PS 20.16/28.80，让利 −11.11% |
| 线上首轮采集 | auto 触发，2.1s，23086 球员，0 errors |
| 线上算价 | ManCity PS 20.16/28.80、PC 13.07/18.68；Paris PS 259.37/370.53，11/11 匹配 |
| 门禁 | 未登录访问 API/页面均 302 → 登录页；服务只绑 127.0.0.1 |
| nginx | `nginx -t` 退出码通过后 reload；备份留存 |

## 待办 / 边界
- ⏳ **老大登录浏览器验收**（页面 UI、编辑器、改间隔、立即刷新）——本次无法替登录验证。
- 二期（**需单独授权**）：自动采集后进 Admin 后台 FC27-Packs 列表改「站点-ALL」产品价。
  参考：admin_api_client.py（`admin-api.p2pah.cn`，Bearer token + ddddocr 过码），
  截图中的两条产品 ID：185327265(PS)/185327726(Xbox)/185327193(PC)。
- Futbin 库 xbox_price 覆盖率低（多为 null）→ 已按「PS/Xbox 共用 ps_price」处理；
  若未来库内 Xbox 价齐了，可在 settings 加开关分开取价。
- `shared server_187/manifest.json` 不含本工具与 navigation.json（已核实，无需 refresh_local）。

---

# 二期（2026-10-13 当日追加）：订单后台取价 + Admin 自动改价

## 数据源升级：订单后台 b2c（老大 17:53 提供 Order 后台截图）
- `order.p2pah.cn` → 金币价格管理 → 所属游戏 **1322（FC 27）**（⚠️ ≠商品后台 1327）→ **b2c = USD/1K**
- 行：21942 PS / 21944 XBOX / 21946 PC；实测 b2c 0.1257 / 0.1257 / **0.0994**
- 实现：vendor/p2pah_price.py（自 MLB §11.3 已验证字节复制），`fetch_rows(gid=1322)`，
  登录过验证码（ddddocr）→ **只在 refresh 时拉取**（/api/state 读缓存，防锁号）；
  失败自动回退 storefront 自算并记 errors。
- 单价口径铁律不变：**赠送 bonus 不摊入**（b2c 本身就是标价口径，与自算 package/base_k 一致）。

## Admin 写价（goods.Goods，站点-ALL）
- 侦察结论（只读，/tmp/pb_probe*.py，零写入）：
  - 捆绑包产品 gid=1327 / cid=10255(Packs) / site_id=0(ALL) / mid：ManCity 44656527、Paris 44656303
  - **aid：21587=PS / 21585=Xbox / 21589=PC**
  - 产品 ID：ManCity PS 185327193 / Xbox 185327229 / PC 185327265；
    Paris PS 185327085 / Xbox 185327121 / PC 185327157
  - 后台价格结构：**unit_price=页面原价（划线），price=unit_price×discount/100（售价，3 位小数），discount=70（=30% OFF）**
  - 老大给的截图 ID 185327726 不存在（Record not found）；Paris PC 当前还是旧手填价 271.474
- 写入：`POST /admin/goods.Goods/edit` **最小字段** `{id, unit_price, price}`
  （球员工具 edit_product 生产验证过的模式）；discount 不动。
- **四道闸门**（settings，页面开关）：`write_enabled`（总闸，默认 false）→
  `write_dry_run`（默认 true，只出 planned 不写）→ `write_auto`（采集后自动写，默认 false）→
  **delta 幂等**（变化 <0.005 跳过）。
- 红线（沿 MLB §10.4）：POST 不自动重试（异常→needs_review 留痕）；
  写前完整 row 快照 `data/before/<pid>.json`（**首次基线绝不覆盖**）；
  写后 sleep 2s 回读验证（mismatch 留痕）；审计 `data/write_log.json`（cap 200）。

## 部署（在 v1 基础上）
| 文件 | sha256 前 16（**2026-10-13 22:xx 最终版**） |
|---|---|
| /opt/fc27-pack-bundles/pack_bundles_server.py | 见「Codex review 修复」节末（每轮迭代留 .bak-vN） |
| /opt/fc27-pack-bundles/vendor/p2pah_price.py | 39fb0becb9713521 |
| /opt/fc27-pack-bundles/vendor/admin_api_client.py | 14b7ed16dd0bd5b8 |
| /var/www/dashboard/modules/sports/bundles/index.html | 见「Codex review 修复」节末 |
- 备份链：`pack_bundles_server.py.bak-v1/v2/v3/v4`、`index.html.bak-v1/v2/v3`（同目录）。
- ⚠️ **回滚必须外科式**（Codex review #13）：`navigation.json` 与 `iggm-web.conf` 在本工具之后
  可能已被其它任务继续改动，**整体还原日期备份会顶掉别人的新改动**。正确做法：
  ① nginx：只删 `# >>> fc27-bundles-api (auto) >>>` … `# <<< fc27-bundles-api (auto) <<<` 之间的块；
  ② 导航：只从 `sections[sports].ids` 移除 `fc27-bundles`、从 `tools` 里删 id 为 `fc27-bundles` 的条目；
  ③ 服务：`systemctl disable --now fc27-pack-bundles`；
  ④ 文件：还原 `pack_bundles_server.py` / `index.html` 的 `.bak-vN`。
- config 轻迁移：**仅键缺失**的 bundle 补默认 products（显式 `{}` 是有效状态，不重填，Codex #9）。

## 已验证
- 离线：23/23（一期 16 + 二期 7：闸门/dry_run/Xbox 共用 PS 目标/needs_review/日志上限/校验器）
- 线上 refresh：status ok / 0 errors / 23090 球员 / **order_b2c 实时取价成功**（PS/XBOX 0.1257、PC 0.0994）
- 线上 dry_run 演练（18:33，**零写入**）：6 产品全部 planned，目标价与前台结构一致，
  如 ManCity PS 29.67→30.18（金币价微涨）、Paris PC 271.474→275.499（旧手填价被修正）。
- 途中修了两个部署 bug：手动 refresh 端点 `self.refresh_lock` 属性错误（一期就带病，无人触发过）、
  vendor 路径 parent.parent 错层。

## 待办
- ⏳ **老大批准后**：关 dry_run 实际写一次（6 产品）→ 前台回读验收 → 再评估开 write_auto。
- 当前线上开关状态：write_enabled=true / write_dry_run=true / write_auto=false（安全：只出计划）。

---

# Codex review 修复（2026-10-13 深夜，16 条批注逐条处置）

PR #95 上 Codex 自动 review 提了 16 条（评了 4 个中间提交）。逐条核验后：**13 条真问题全部修复**，
2 条属"评的旧提交、已自行修复"，1 条为误报（详见下）。

## 已修复（附回归用例）
| # | 问题 | 修法 |
|---|---|---|
| 1 | 改价前不校验产品身份（错填 ID 会改到别的商品） | `write_price` 校验 `gid=1327/cid=10255/site_id=0/aid=平台/title=包名`，不符 → `rejected_identity`（零写入） |
| 2 | 球员缺价时仍按剩余球员总价写价（11 人包按 10 人价） | `compute_bundle` 输出 `players_counted/players_expected`；不齐 → `skipped_incomplete` |
| 4 | 请求体 `{"dry_run": false}` 可放宽配置的试运行闸门 | `eff_dry = 配置 or 请求`（**只能收紧**） |
| 5 | `WRITE_LOCK` 起线程后立即释放 → 并发写价 | 锁移至 worker `finally` 释放；起线程失败即回滚释放 |
| 6 | `/api/state` 不回传 `products` → 前端保存清空绑定 | `compute_state` 回填配置的 products |
| 7 | 订单页面返回未过滤行 → 别的游戏 b2c 被采用 | `_overlay_order_b2c` 校验行 `gid == order_gid`，不符 → `gid_mismatch` 拒绝并回退 |
| 9 | 重启把"故意清空的 products:{}"重填回默认 ID | 轻迁移只补**键缺失**，`{}` 视为有效状态 |
| 10 | `running` 卡死 → 调度永久停摆 | 启动清扫（`interrupted`）+ 运行中 `running` 超 2h 视为 abandoned 重跑 |
| 11 | 自动写价不与手动写价互斥 | 自动路径同样取 `WRITE_LOCK`（拿不到即跳过本轮） |
| 13 | README 回滚整文件还原会顶掉后续部署 | 改为外科式（只删本工具的 nav 条目 / nginx 块 / service） |
| 14 | README 记录 sha 与实际部署不符 | 改为按 `sha256sum` 实测填写 + 备份链 `.bak-vN` |
| 16 | `bool("false")` 恒 True → 关闸变开闸 | 四个闸门只接受真 JSON bool，否则 400 |
| 17 | 前端把 409 当成功（"已启动"但没启动） | `api()` 对非 2xx 统一抛错；错误文案区分"进行中" |
| 7b | `dryrun_write.sh` 失败不中止（可能真写） | `set -e` + `curl -fsS` + 写价前**再读持久闸门**校验 |
| 8 | 0.1~1 小时间隔被静默抬成 1 小时 | `interval_seconds` 下限对齐校验器 0.1h |

## 已自行修复 / 误报
- **#3 refresh 锁泄漏**（评 `bad88417`）：19:36 已修（`self.refresh_lock` → `self.store.refresh_lock`），
  Codex 后续 review 未再提。
- **#12 `pr_fast.py` 顶掉 `fc-deep-advisor`**（评 `418a98d3`）：**已在 `13ac6566` 自修**——
  该中间提交的补丁基线落后（`aa2827bd`），我在发现 main 推进到 `ac176f31` 后重拉字节重打三件套。
  核验结论：main 最终版（`31708cf8`）同时含 `fc-deep-advisor` 与 `fc27-pack-bundles`，**无顶掉**。
  教训登记：**每次打补丁前必须重拉远端最新字节**（本批已执行 3 次，正是此流程抓出了这次回退风险）。

## 回归
- 离线 **31/31**（新增 9 条 Codex 防护用例：bool 严格 / 0.5h 间隔 / 空 products 保留 / state 回传绑定 /
  dry_run 只能收紧 / 不完整平台拒写 / 身份校验 fail-closed / 外来 gid b2c 拒绝）
- 本地 CI 彩排 + 真实 CI（PR #96）双绿

---

# 自动发现绑定（2026-10-16，老大反馈"新增包后没法绑产品 ID / 没有保存按钮"）

## 两个问题
1. **新建包后没有保存绑定的入口**：卡片上的产品 ID 输入框只在「编辑」保存流程里被读取，
   直接填了没地方存 ⇒ **真 bug**。
2. **手动去后台查产品 ID 太麻烦**：希望自动对应。

## 修法
- 后端新增 `POST /api/discover-products`（**只读**）：按标题在 FC27-Packs
  （`gid=1327 / cid=10255 / site_id=0`）里扫描，`aid` 归位三平台；标题**归一化匹配**
  （去空格/连字符/下划线 + 小写）——实测 `ManCity11-PlayerBundle` 与
  `Paris11-Player Bundle` 两种写法都能命中；返回 `matched / matched_title / unmatched /
  candidates`（候选 = 该分类下全部标题，供人工挑）。串行化（`DISCOVER_LOCK`）防登录频控。
- 前端：每个包卡片的产品行加 **「自动发现」+「保存绑定」** 两个按钮；
  **新建包保存后自动跑一次发现**并提示结果；未命中时列出后台现有标题供核对。
- 回归：离线 33/33（新增 2 条：归一化匹配 + `_norm_title`）。

## 线上实测（2026-10-16）
- `{"title":"ManCity11-PlayerBundle"}` → `matched={ps:185327193, xbox:185327229, pc:185327265}`，`unmatched=[]`
- `{"title":"paris11-playerbundle"}`（故意错写）→ 命中原标题 `Paris11-Player Bundle`，三平台全齐
- 候选列表返回后台 16 个产品标题（含 `Barcelona Player Bundle`、`Lyon Women Player Bundle` 等未建包的）
- 线上 sha：`d031d336…`（server，备份 .bak-v6）/ `ca4f5cff…`（web，备份 .bak-v5）

---

# 编辑保存体验修复 + 删除包按钮（2026-10-16 第二批，同一 PR #193）

## 反馈
老大："编辑已建好的捆绑包添加球员时又不能保存了" + "后台过期下架后工具里没有删除按钮"。

## 排查（本地用线上配置副本复现，不动线上）
- 服务端对两种 payload（未编辑包沿用展示结构 / 全用配置结构）**都返回 200** ⇒ 后端无问题。
- 复现出三个真实失败点：
  1. `revision_conflict` —— 页面停留期间配置被其它操作更新（另开页面 / 点了别的保存）。
     原实现返回 **400** + 英文码，前端只显示"保存失败：revision_conflict"，用户无从下手。
  2. **新加的球员行只填了位置没填 Futbin ID** → 原提示"有行的 Futbin ID 无效"（不指行号）。
  3. **删到 0 个包被拒**（`bundles_required`）——后台下架清空场景直接被卡。

## 修法
- **删除包按钮**（卡片右侧，红色 danger，二次确认）：说明"仅从工具移除、不删后台产品、可重建"。
- **保存体验**：全空行自动忽略（加了行没填不卡保存）；半填/非数字 → **报出第几行**；
  重复 Futbin ID → 报出重复行号；**revision 冲突自动同步**最新版本并提示"再点一次保存"。
- 服务端：`revision_conflict` 改返 **409**（语义化）；**允许空 bundles**（0 个包是合法状态）。

## 验证
- 离线 **35/35**（新增 3 条：删到空 + 冲突语义 + 非列表拒绝）
- 本地端到端：删单包 200 → 删到空 200 → 空仓库 state 200 → 旧 revision **409**
- 线上 sha：`0891ef52…`（server，.bak-v7）/ `9d50ab7f…`（web，.bak-v6）

---

# 人数规则纠正：最少 2 人即可（2026-10-16 第三批，同一 PR #193）

## 老大纠正
> 捆绑包不需要非要 11 人，只要最低有 2 人就行。

此前我在汇报里说"要凑齐 11 人才能写价"——**是错误信息**（把 Codex #2 的"完整性闸门"误解成人数要求）。

## 正确规则（已落地）
| 规则 | 含义 |
|---|---|
| **下限 2 人** | 最少 2 人成包（单人包无打包意义）；上限仍 50（防误填）→ `players_min2` |
| **全员有价** | 配置的球员**都有价**才写价（防按缺价人数算出偏低总价 → 少收钱）；**与人数多少无关** |
| ~~11 人~~ | **不存在这个要求**，任意 ≥2 人皆可 |

## 改动
- `validate_bundles`：新增下限校验（<2 人 → `players_min2`）
- `execute_write` 的 `skipped_incomplete` 提示改为指明**几名球员无价**（不再暗示人数不够）
- 前端：保存时校验 ≥2 人；包卡片新增**写价就绪状态行**：
  `✅ 写价就绪：PS/XBOX/PC` 或 `⚠️ X(N人无价) → 暂不写价（删掉无价球员行即可恢复；人数不限，2 人起即可成包）`
  未绑定时提示去点「自动发现」
- 测试夹具改为 2 人包（原 1 人夹具已被新规则拒绝），目标价断言随之更新

## 线上实测（2026-10-16 16:39）
6 个包**全部就绪**（每包球员全员有价）：
| 包 | 球员 | 绑定 | PS/PC 有价 |
|---|---|---|---|
| mancity11 | 11 | 3 平台 | 11/11 |
| paris11 | 11 | 3 平台 | 11/11 |
| premier-league | 7 | 3 平台 | 7/7 |
| barcelona | 7 | 3 平台 | 7/7 |
| lyon-women | **2** | 3 平台 | 2/2 |
| laliga | 5 | 3 平台 | 5/5 |

自动轮 **18/18 written**（6 包 × 3 平台）——4 个新建包**首次完成自动定价**。
离线 36/36；线上 sha `67ac2b90…`（server，.bak-v8）/ `50f292ce…`（web，.bak-v7）。
