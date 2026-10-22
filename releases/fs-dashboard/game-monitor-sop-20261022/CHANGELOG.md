# CHANGELOG · 游戏监控台 MapleStory 十栏目补全（2026-10-22）

候选版本：`candidate/index.html`（SHA256 `35d15d02076ce627548ca9424138e9c9b2f0685df1652585ddb1697ca65b8e2a`）
基线版本：`source/index.html`（SHA256 `368a40026ca065f40a4133f9157f1d22d1d5325dd524d27de0fd13bce8c8d483`，与线上一致）
范围：仅 `key = maplestory` 相关数据；未改其他 29 个游戏、共享 UI、CSS、运行脚本与任何调度。

## 1. 改动清单（按栏目）

| # | 栏目 | 改动 |
|---|---|---|
| 1 | ov | 新增 `PLAYBOOK.maplestory`：overview 143 字、core 179 字、tips 5 条（每条带草稿标记）、gallery 4 张；重写主档 `intro`；`events` 由 3 条（含 2 条未核实 OVERDRIVE 章节）替换为 4 条官方可溯节点（10/06 创始人通道、10/21 全球开服、10/29 v272 PTS、11/30 创始人包领取截止） |
| 2 | biz | 新增 6 个品类（金币 Meso 5★ / 账号 5★ / 代练 4★ / 装备道具 4★ / NX 代充 3★ / 账号租赁 1★）。每项 desc 标“Hermes经营草稿·待运营确认”；4★ 以上含 why/how/eff/opt 与竞品对标；eff 无订单证据处标“判断/待验证”；删除固定面额与单笔阈值 |
| 3 | dept | 新增 9 行部门动作（产品/设计/引流/投放/私域/邮件/广告/技术/生产），每行带本游戏专有名词并标注草稿 |
| 4 | tool | 新增 `GAME_TOOLS_MAP.maplestory`：4 工具 + 2 Wiki，均为可访问真实站点；`visits` 留空、截图留空（不编数字/不造空文件） |
| 5 | cls | 重写 `GAME_GUIDE.maplestory`：新增 `classes` 5 张快速卡；`clsDocs` 由 5 张正式服职业群卡改为 **14 张 Classic 全职业树**（4 个一转 + 10 个二转分支），10 张含装备/技能/属性/短板/适合人群/运营落点 |
| 6 | play | 重写 5 块，区分 Classic（Lv1-100、二转、六 Boss、PQ、Crafting、Windows/macOS 客户端）与正式服（HEXA、Star Force、Legion、Link、Arcane/Sacred、周 Boss）；Star Force 不再写固定星数 |
| 7 | terms | 由 13 条扩到 **17 条**，补齐 NX/Leaf Points/Maple Points/HEXA/Heroic-Interactive/Kerning PQ/Crafting 等；修正 `Reboot` 过期命名；Free Market 标“正式服已移除、Classic 待核”；Star Force 条目改为“上限以当前版本为准” |
| 8 | eco | 重写 4 块：货币与官方 RMT 态度、交易机制与市场成熟度、MMOEXP 落点（草稿）、价格公式（草稿）；删除未核实的 OVERDRIVE 经济窗口与固定面额 |
| 9 | ops | 重写 4 块：双词簇 SEO、素材/受众/负词与 Ad Promoting 红线、上架节奏/组合包/补货、客服口径；每块标题标草稿 |
| 10 | intel | `MAPLESTORYBRIEF` 更新到构建时的真实 UTC：7 维 24 条全部带日期；esports 明确“不适用”并给替代观察；删除未核实的 OVERDRIVE/MSEA Malicia/KMS 联动条目 |

## 2. 结构域改动（最小化）

- `GAME_TIMELINE_DATA.games[maplestory]`：仅 `intro` / `services` / `key_services` / `events` / `platform_pricing` 五个字段变化；key 与其余字段原样保留，未改全局 `updated`。
- `PLAYBOOK`：新增 `maplestory` 一个条目，其他 4 个条目逐字段一致。
- `GAME_TOOLS_MAP`：新增 `maplestory` 一个 key，其他 15 个 key 一致。
- `GAME_GUIDE`：仅替换 `maplestory` 值，其他 29 个 key 一致。
- `MAPLESTORYBRIEF`：整体替换（intel 专用）。
- 校验方式：把候选的五个数据块换回原块后，与 `source/index.html` **逐字节相同（540,730 字符）**。

## 3. 新增文件

```
candidate/index.html                     候选页面
candidate/daily.js / fs-integration.js / fs-integration.css   与 source 完全相同
candidate/assets/maplestory/mscw-keyart.webp   15,568 B  Nexon CDN hero art
candidate/assets/maplestory/mscw-warrior.png   57,681 B  official illust_warrior
candidate/assets/maplestory/mscw-bowman.png    68,773 B  official illust_bowman
candidate/assets/maplestory/mscw-thief.png     58,765 B  official illust_thief
AUDIT.md  SOURCES.json  VALIDATION.json  CHANGELOG.md
tools/jsparse.py  tools/build_candidate.py  tools/verify.py  tools/render_check.py
tools/content_part1.py  tools/content_part2.py  tools/make_reports.py  tools/probe_sources.py
tools/url_probe.json（25 条外链的真实探测时刻与 HTTP 状态）
```

## 4. 验证结果

- 静态校验 **63 项全部通过**：范围隔离、唯一 key、十栏数量、图片路径、外链 HTTPS、script/style 数量、undefined 计数、JS 语法（7 个内联脚本 + 2 个外部脚本，V8 编译）、草稿标记可见性（biz/dept/ops/tips）、禁用固定断言（“最高 25 星”“1 亿/5 亿”“5 亿以内”等）、eff 判断标注、macOS 说明。
- 渲染校验：用页面自身脚本 + 最小 DOM 桩在 V8 中执行 `gvRender(maplestory)`，十栏全部产出内容（biz 6 / tools 6 / cls 14 / terms 17 / dept 9 / intel 7 / gallery 4），草稿标记在渲染结果中出现 **26 次**，无 `[object Object]`／`undefined`。
- **未做**：真实浏览器截图、响应式与浅暗主题验收、线上发布验收。容器浏览器不可用，已如实记录，不冒充视觉验收通过。

## 5. 回退

候选未发布，回退只需丢弃 `candidate/`。若已由 Codex 发布，按宿主既有 publisher 回退到上一版本目录；`source/index.html` 保留为发布基线。

## 6. 未完成 / 需后续

1. 工具站访问量与截图（无回执/无合法截图）。
2. Classic 自由市场机制、三转时间表（官方未公布）。
3. 竞品成交价、有效成本、关键词量级（未取）。
4. 正式服 50+ 职业的逐职业覆盖（本轮只覆盖 Classic 职业树，页面已注明）。
5. 长期维护接入：见 `content-standard-20261022.md` 第 7 节（需 Codex 统一接入，不在容器内自建调度）。

## 7. Codex 首轮复审修正（2026-10-22）

| 复审条 | 处理 |
|---|---|
| 1 经营草稿须在页面可见 | biz 每项 desc、dept 每行、ops 每块标题、ov 每条 tip 加“Hermes经营草稿·待运营确认”；eff 改“判断/待验证”；MMOEXP 在售范围改“待以当前货架核实”；未执行任何后台动作 |
| 2 固定面额/阈值无供给证据 | 删除 1 亿/5 亿/10 亿、单笔 5 亿阈值、“Meso 5 亿”组合；改为“面额与单笔上限待实际供给与成交核定”，保留分层与计算法；未给新售价 |
| 3 Star Force 旧帮助页口径 | 删除“最高 25 星/失败掉星”断言，改为“上限与失败规则以当前版本官方说明为准”；Classic 无该系统边界保留 |
| 4 时点不可预填 | `MAPLESTORYBRIEF.updated` 由构建时真实 UTC 写入；SOURCES/VALIDATION 的 `generated_at` 与每条 `retrieved_at_utc` 来自真实探测 |
| 5 保留已核事实并补 macOS | 四条上线事实保留；play 块补“客户端支持 Windows/macOS” |
| 6 重建并加检查 | 重建候选，52 → 63 项检查，渲染加 `draft_marker >= 19`；未放宽原断言 |
| 7 长期标准与读回 | 标准第 4 节新增“经营草稿”类别与标注规则；已写入并读回 |
