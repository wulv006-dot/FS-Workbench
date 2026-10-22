# CHANGELOG · 游戏监控台 MapleStory 十栏目补全（2026-10-22）

当前候选：`candidate/index.html`（SHA256 `7b74f7bf06ac5f0228bd58c1d0e3a55cc943bc30967682ef53f1544f9a43b0ae`，第 8 节技能事实复核后的版本）
上一候选：`35d15d02076ce627548ca9424138e9c9b2f0685df1652585ddb1697ca65b8e2a`（第 1—7 节描述的版本，已被本轮取代）
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

## 8. Classic 职业技能事实复核（2026-10-22，PR337 自动复审后修正）

触发：PR337 自动复审指出 Spearman 卡把 Spear Crusher 当二转核心并放进 Boss 循环，Fighter/Page 的 Power Guard 归属存疑。
复审评论本身不作事实，本轮按当前 Classic 上线版逐条核对；核对结果与复审方向一致，但归属细节不同（Power Guard 根本不属二转，Power Guard 与 Hyper Body 都属三转）。

### 8.1 具体纠正（8 条）

| # | 职业 | 旧稿 | 核对结论 | 现状 |
|---|---|---|---|---|
| 1 | Spearman | Spear Crusher 为二转主力输出、进 Boss 循环 | 三个数据源均无此技能名；枪系三转（Dragon Knight，仅 CoT2 测试）为 Piercing Crusher | 已删除，循环改为 Iron Will → Rush → 普攻/Slash Blast + Final Attack |
| 2 | Spearman | Hyper Body 为二转队伍 HP/MP 增益、核心卖点 | Hyper Body 属三转 Dragon Knight（NiaMeowDB 明写；MapleStory Quest 的 Dragon Knight 页为 +30% 最大 HP 队伍增益） | 已删除，改以 Iron Will（武器防御 +50、35% 忽略击退）与最长普攻距离定位 |
| 3 | Fighter | Power Guard 受击减伤反弹 | Fighter 二转 8 技能为 Sword/Axe Mastery、Final Attack×2、Booster×2、Rage、Rush；Power Guard 属三转 White Knight | 已删除；补入 Rage / Rush 与真实 build 顺序 |
| 4 | Fighter | Weapon Mastery | Classic 按武器分为 Sword Mastery / Axe Mastery | 已替换 |
| 5 | Page | Shield Mastery、Power Guard | Page 8 技能为两套 Mastery/Booster/Final Attack + Threaten + Rush；盾是装备不占技能位 | 已删除；定位改为 Threaten 减益 + 生存 |
| 6 | Wizard (Fire/Poison) | Poison Brace | Classic 毒系技能为 Poison Breath | 已改名并补定位 |
| 7 | Beginner | Basic Attack 为唯一输出 | Beginner 仅 Three Snails / Recovery / Nimble Feet（各上限 Lv3） | 已替换 |
| 8 | Bandit | “匕首熟练与涂毒类辅助” | Bandit 6 技能无任何毒系技能 | 已删除，改为 Savage Blow / Steal / Nimble Recovery 循环 |

同时修正的定位/机制描述：Spearman“多段刺击补输出”删除；Fighter“终结技打单体”删除；Assassin“贴脸打背身”删除（Classic 二转无背击机制）；
I/L Wizard“冻结控制”改为“减速 + 感电”（Cold Beam 为减速 3 秒，非硬控）；Cleric 的 Bless 改为“队伍增益”，Haste/Soul Arrow/Iron Will 等按上线版数据重写。
“Classic 无三转”的表述统一改为“当前上线版没有三转（三转仅存在于早期 CoT2 测试数据）”，并写入 play 块与 Job Advancement 术语条。

### 8.2 证据与新增产物

- `CLASS-SKILLS-REVIEW.json`（109 KB）：15 个职业 × 93 条已核技能 + 8 条旧稿纠正条目，每条含 职业 / 技能 / 适用版本 / 来源 URL / 证据摘要 / 已核或未核 / 是否进入卡片与循环。
- 单一事实来源 `tools/class_skills.py`：职业卡技能、被动、循环与证据映射同源生成，避免卡片与证据表脱节。
- 证据等级：官方公告（S02 / 10-21 上线说明）只确认 4 个一转 + 10 条二转 + Lv100；**官方职业页对无 JS 客户端只返回空壳（3766 bytes，无职业/技能文本）**，本轮未从官方页取得技能级数据；
  技能级证据来自三份独立 Classic 数据源：MapleStory Quest（客户端数据，S26）、MapleClassic Wiki（S27/S28）、NiaMeowDB（S29）。两源以上一致才写入卡片，未把社区数据标成官方数值。
- 两处站点描述冲突未硬写：Spear Mastery 附加效果（忽略敌防概率 vs 回避加成）、Bless 具体效果（命中/回避/回血 vs 受伤 -15% 与 Heal 回血 +10%），卡片只写通用定位，冲突记入证据表 note。

### 8.3 结构与验证

- 改动范围：`GAME_GUIDE.maplestory`（classes / clsDocs 的 role / intro / core / str / weak / stat / gear / skills / passive / loop / loop_skills / build / tip）、`play` 一块追加三转边界、`terms` 的 Job Advancement、`MAPLESTORYBRIEF` 一条 content 缺口；其他栏目与其他 29 个游戏未改。把候选五个数据块换回原件后与 `source/index.html` 逐字节一致（540,730 字符）。
- 静态校验 **73 项全部通过**（原 63 项全部保留、未放宽，新增 10 项）：
  技能表/循环无三转或未核技能、三转提及必须带纠正说明、三转边界已写明、职业卡技能名与被动均在证据映射（含一转继承）、
  建议循环只用已核技能、每条循环绑定已核技能、证据映射覆盖 15 个职业且字段完整、旧稿错误技能未回流、强度判断已标注。
- 渲染校验通过：cls 栏 14 张卡、技能行 105、循环步骤 55；4 个新探针（技能证据说明可见、无 Spear Crusher / Hyper Body / Power Guard 旧断言）全绿。
- 统计：候选 582,107 字符（源 540,730），新增 265 行 / 删除 73 行；候选 SHA `7b74f7bf…`。
- **未做**：真实浏览器截图、响应式与浅暗主题验收、线上发布验收。官方站本轮在容器内无法渲染（浏览器与无头均只得到空壳），已如实记录。

### 8.4 未核与边界

- 技能数值（倍率/概率/持续时间）为社区客户端数据整理，非官方数值；卡片只保留定位级描述。
- 三转技能、正式服 50+ 职业未做技能级覆盖（当前上线版没有三转）。
- 星级难度、优势/短板、build 与循环顺序为 Hermes 判断，卡片内已逐条标注“判断”。
- 本轮不创建 PR、不合并、不发布、不新建 cron、不发对外消息；长期标准第 10 节（服务器候选维护计划 6534331b5100）未改动。
- `content-candidate.zip` 仍是上一轮的打包产物；`bundle_candidate.py` 属宿主侧复现合同（私库路径 + `conversation.json` phase 校验），本轮未重打包，交由 Codex 统一处理。
