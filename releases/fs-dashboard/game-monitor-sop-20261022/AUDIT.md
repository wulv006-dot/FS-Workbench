# AUDIT · MapleStory 十栏目现状与缺口（2026-10-22）

审计对象：FS 游戏监控台现行活动页 `/dashboard/game-monitor/index.html`（冻结副本 `source/index.html`，SHA256 `368a40026ca065f40a4133f9157f1d22d1d5325dd524d27de0fd13bce8c8d483`，与线上 `/var/lib/fs-navigation-formal-static/workspace-native-20261006-abc565540ced/game-monitor/index.html` 一致，见 `baseline.json`）。
审计游戏：`key = maplestory`（唯一，未新增、未改名）。
标准来源：`SOP-EXTRACTED.md`（PDF 10 页；raw SHA256 `45b1a562…f9f`，INPUT.json 声明的 `extracted_sha256` = LF 归一化后 `4b74395…a14`，两者为同一文件的不同换行计算，非篡改）。

## 一、对 SOP 的理解（按现行 FS 适配）

1. 详情页由 5 份配置驱动，全部内联在 `index.html`：
   - `window.GAME_TIMELINE_DATA.games[]`：游戏主档 + 时间轴；
   - `const PLAYBOOK[key]`：ov / biz / dept + gallery / tips；
   - `const GAME_TOOLS_MAP[key]`：tool 的工具与 Wiki 两组卡；
   - `window.GAME_GUIDE[key]`：cls（classes + clsDocs）/ play / terms / eco / ops；
   - `const MAPLESTORYBRIEF` 等 7 维简报：intel 区（`GAMEBRIEFS` 精确匹配 key）。
2. 前端按 key 精确匹配，缺 key 时静默回退：PLAYBOOK 回退 `PLAYBOOK_DEFAULT`（通用空模板），GAME_TOOLS_MAP 缺失则工具区为空，GAME_GUIDE 缺失则 cls/play/terms/eco/ops 五个 tab 不渲染。因此“有 key”不等于“有内容”。
3. 十栏目锚点与数量标准（本任务采用）：ov（80–150 字概览 / 100–200 字核心 / 3–5 动作 / 4 图）、biz（七大品类按适用性 4–7 项，star 4–5 必写 why/how/eff）、dept（9 行固定：产品/设计/引流/投放/私域/邮件/广告/技术/生产）、tool（4 工具 + 2 Wiki）、cls（当前版本职业全覆盖 + 热门 4–6 深卡）、play（4–5 块）、terms（≥10）、eco（3–5 块）、ops（SEO/投放/运营/客服 4 块）、intel（version/market/seo/kol/content/esports/exploit 七维）。
4. 现行 FS 与 PDF 的差异：PDF 的路径（`release-radar-migration/frontend/`）、域名（coze.site）、`maplestory-classic` 新 key、“全部为空”的现状判断均已过期；现行以 `index.html` 内联数据 + `daily.json` / `seo-news.json` 周采为准，PDF 只作内容标准。

## 二、审计发现（改动前）

| # | 栏目 | 数据源 | 改动前现状 | 问题 |
|---|---|---|---|---|
| 1 | ov 运营概览 | `PLAYBOOK.maplestory` | **不存在** → 走 `PLAYBOOK_DEFAULT` 通用模板 | 概览/core 为通用话术，无版本与节点；主档 `intro` 混写正式服与 Classic，且含未核实版本 |
| 2 | biz 经营打法 | 同上 | **不存在** → 通用模板 | 无七大品类矩阵、无 star/how/eff、无竞品对标 |
| 3 | dept 部门覆盖 | 同上 | **不存在** → 通用模板 | 部门动作为通用句，无本游戏专有名词 |
| 4 | tool 工具 WIKI | `GAME_TOOLS_MAP.maplestory` | **key 不存在** | 工具/Wiki 区为空（渲染为“暂无工具资源，待补充”） |
| 5 | cls 职业介绍 | `GAME_GUIDE.maplestory` | 仅 `clsDocs` 5 张：Warrior/Bowman/Magician/Thief/Pirate（按正式服职业群），**无 `classes`** | 与 Classic 版本不符：官方 Classic 只有 4 个一转职业、无 Pirate，二转 10 条分支未覆盖；play 页的快速职业卡也因此为空 |
| 6 | play 玩法攻略 | 同上 | 5 块，但把 Star Force / Arcane Power / Arcane River / Grandis / Legion 与 Classic 混写 | 版本边界不清；正式服机制被写成通用机制 |
| 7 | terms 术语速记 | 同上 | 13 条（Meso/Star Force/Potential/Legion/Link/…/Reboot） | 缺 NX / Leaf Points / Maple Points / HEXA / Heroic 等关键货币与分区术语；`Reboot` 命名已被官方 `Heroic / Interactive` 取代 |
| 8 | eco 经济体系 | 同上 | 3 块 | 含“冬季大版本 OVERDRIVE 11/11、12/16”未核实节点；`Reboot 区不可交易` 表述过期；无 Classic 交易解锁规则 |
| 9 | ops 运营落地 | 同上 | 4 块 | 排期围绕 11/11、12/16 的未核实版本；SEO/投放/客服口径未区分两服 |
| 10 | intel 实时情报 | `MAPLESTORYBRIEF`（`GAMEBRIEFS`） | 存在，`updated 2026-10-05 16:30`，7 维齐全，esports 已说明无联赛 | 内容为 10-05 时点：含“OVERDRIVE 冬季两章”“MSEA 10/14 Malicia”“KMS 11/19 蔚蓝档案联动”等未核项；无 10/21 开服事实、无处罚互通与新交易锁 |

补充结构事实：
- 仓库既有 PLAYBOOK 条目（aion2/poe2/diablo4/ea-sports-fc）的 `dept` 为 12 行（含客服/供给/发货），与本任务明确的 9 行口径不同；本轮按任务口径写 9 行，未改其他游戏。
- 周采只写 `daily.json` / `seo-news.json`，由 `fsApplyGameDaily` 注入时间轴与 News 卡；**不会**改写 PLAYBOOK / GAME_TOOLS_MAP / GAME_GUIDE / MAPLESTORYBRIEF。第十栏 intel 对 maplestory 走的是 `MAPLESTORYBRIEF` 静态简报，不是周采结果。

## 三、事实核查与纠错（关键）

| 待核项 | 核查结果 | 依据 |
|---|---|---|
| Classic World 2026-10-21 开服 | **成立**：10/21 11:00 PDT（18:00 UTC）Grand Launch，Nexon Launcher 与 Steam | 官方 Grand Launch Release Notes、Classic World FAQ |
| 创始人包 10/14 截止 | **成立**：10/14 23:59 PDT 停售；10/06 11:00 PDT 开放创始人通道；道具 11/30 23:59 UTC 前领取 | 官方 FAQ |
| Classic 职业与等级 | **成立且更具体**：Lv10 一转 4 职业（Warrior/Magician/Bowman/Thief），Lv30 二转 10 条分支，上限 Lv100；**无 Pirate** | 官方 Release Notes + 官方 Classes & Jobs（MSCW）页 |
| Star Force / 潜能 / Legion / Link Skill / NX | **分流**：Star Force（消耗 Meso 的装备强化）、潜能、Legion、Link Skill、Arcane/Sacred 均属**正式服**；Classic 官方上线公告未列这些系统（只列二转、六 Boss、Crafting/Citizenship/Housing/PQ）。NX 为两服共享余额；**Leaf Points** 是 Classic 现金货币；**Maple Points 不跨到 Classic** | Star Force 官方支持文档；Classic FAQ；Release Notes |
| “冬季大版本 OVERDRIVE 11/11、12/16（GMS）” | **不成立**：OVERDRIVE 是 2026 夏季更新（KMS 6/18 起，含新职业 Lethe、HEXA 第三技能节点、Boss Bellona）；GMS 当前为 v271（芙莉莲联动），下一个主版本是 **11 月 v272**（PTS 10/29–11/01，正式日期未公布） | Nexon GMS News 更新列表；v272 PTS 公告；MapleStory Wiki（KMS June 2026 Overdrive）；Orange Mushroom |
| Reboot 服不可交易 | **表述过期**：官方现行分区为 **Heroic / Interactive**；Heroic 装备不可交易、无 Auction House 与 Meso Market；Interactive 可交易 | 官方支持文档 What are Heroic, Interactive, and Seasonal Worlds |
| Free Market | 正式服已于 v.193 移除；Classic 是否以自由市场形式回归，官方上线公告未列 → **待核** | 官方支持文档；Classic Release Notes |
| 封禁与 RMT | **成立且关键**：GMS 与 Classic 为同一账号、同一处罚标准，一封两服；账号买卖/NX 买卖/账号共享属可处罚项；Ad Promoting 可永久封禁；新账号交易需 Lv15 后 24 小时 | Maple Memo（Account Sanctions）、Banning Guidelines、Release Notes |
| 第三方市场 | G2G 已单开 `MapleStory Classic World Mesos` 类目；PlayerAuctions / Eldorado / IGGM / U7BUY 均有 MapleStory 相关类目（本轮只核类目存在，**未取价**） | 各站类目页（见 SOURCES.json） |

## 四、Classic World 是否需要独立 key

**证据（支持独立）**：独立客户端（Nexon Launcher/Steam 独立入口）、独立职业页、独立现金商城与 IGN、独立等级与职业体系、独立经济。
**证据（支持共用）**：同一 Nexon 账号、共享 NX 余额、处罚互通、同一 IP 与发行商；FS 现有 radar 条目与 `daily.json` 的 `game_key` 均为 `maplestory`。

**本轮结论：不新增 key**。理由：新增 `maplestory-classic` 需要同时改主档、10 栏、radar 映射与新闻 `game_keys` 归属，并把现有 Classic 事件从 `maplestory` 迁出；这会改变筛选口径、历史对比与既有报告引用，属于结构性变更，不是本次“补内容”的范围。本轮以**单 key + 内容内显式版本分区**处理：ov/core、play、terms、eco 均标 `Classic` 或 `正式服（GMS）` 适用版本。

**若后续要拆分的兼容方案（交 Codex 评估，不在本轮执行）**：
1. 主档新增 `maplestory-classic`（platforms/PC、monetization/NX、official_site 用 MSCW 页面、events 独立）。
2. `PLAYBOOK` / `GAME_TOOLS_MAP` / `GAME_GUIDE` 各自新增同名 key；`GAMEBRIEFS` 增加 `maplestory-classic`。
3. `daily.json` 的 `game_key` 映射与信源 `maple-news` 需要按 URL 区分 Classic 与 GMS 新闻（现为同一 `maplestory.nexon.com/News/Update`）。
4. 旧 key 保留为“正式服”，历史事件不删；需评估筛选器、报表口径与外部引用（避免同一条开服事件在两处重复计数）。

## 五、本轮缺口（未核实，不能写成已达标）

1. 工具站月访问量：无可信第三方流量回执 → `visits` 留空，不排序、不编数字。
2. 工具截图：未取得可合法使用的站点截图 → 卡片不填 `img`，不造空文件。
3. Classic 自由市场/拍卖行机制：官方公告未列 → 标“待核”。
4. Classic 三转与新区域时间表：官方只给 Forgotten Hollow「11 月」，无具体日期 → 不写具体日期。
5. 关键词量级、竞品成交价、有效货源成本：无工具回执/授权数据 → 只给公式与待补项，不给售价与折扣。
6. 视觉与交互验收：本容器无可用浏览器（`document` 不可用），只做了数据→渲染函数的真实执行检查，**未做截图/视觉验收**。


## 六、Codex 首轮复审后的修正（2026-10-22）

复审提出 7 条，逐条处理如下（详见 `VALIDATION.json` 的 `review_response` 与 `CHANGELOG.md` 第 7 节）：

1. **经营草稿必须可见**：biz 每项 `desc`、dept 每行、ops 每块标题、ov 每条 tip 都带“Hermes经营草稿·待运营确认”；4★ 以上的 `eff` 无订单证据时改为“判断/待验证”；MMOEXP 自有在售范围不再写成事实，改为“待以当前货架核实”。
2. **删除未核固定面额/阈值**：1 亿/5 亿/10 亿面额、“单笔 5 亿以内”、“Meso 5 亿”组合包全部删除，改为“面额与单笔上限待实际供给与成交核定”，保留分层与定价方法。
3. **Star Force 上限撤回**：原“最高 25 星、失败掉星”来自长期未变的官方帮助页，不能假定 2026 版本仍适用；已改为“消耗 Meso 的装备强化，上限与失败规则以当前版本官方说明为准”，不再作固定断言。Classic 无该系统（按上线公告范围）仍保留。
4. **时点改为真实值**：`MAPLESTORYBRIEF.updated` 由构建时的实际 UTC 写入；`SOURCES.json` 每条外链的 `retrieved_at_utc` 与 HTTP 状态来自本轮 `tools/probe_sources.py` 的真实无头 GET，不再统一填同一时间。
5. **保留已核事实并补 macOS**：10/21 18:00 UTC、四职业、十条二转、Lv100、Lv15 后 24 小时交易锁均保留；play 块补充“客户端支持 Windows/macOS”。
6. **检查项扩充**：52 → 63 项，新增草稿标记可见性 4 项、禁用固定断言 5 项、`eff` 标注与 macOS 各 1 项；渲染检查新增 `draft_marker >= 19`。未放宽任何原有断言。
7. **长期标准同步**：`content-standard-20261022.md` 第 4 节新增“经营草稿”类别与可见标注规则；维护接入方案不变。


## 发布前交易方式复核（Codex）

摆摊机制尚未实测，不作为Classic已确认交付方式或成交价依据；已同步经营落地、情报判断和来源J1。当前候选SHA 70db24939c495835e837cd36d8af011bfe08f75094728545ae06952a276a6411；新增回归检查，原技能复核不变。此前7b74候选为历史时点。


发布前Codex交易方式复核：Classic摆摊及面交尚待实测，不作为已确认交付承诺；挂单不当成交价。新增1条回归，原73项保持，74/74通过。当前SHA 70db24939c495835e837cd36d8af011bfe08f75094728545ae06952a276a6411。
