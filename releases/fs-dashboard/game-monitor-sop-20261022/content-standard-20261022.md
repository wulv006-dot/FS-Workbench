# 游戏监控台 · 二级栏目内容与维护标准（2026-10-22 版）

适用范围：FS 游戏监控台 `/dashboard/game-monitor/` 的游戏详情页十栏目内容（ov / biz / dept / tool / cls / play / terms / eco / ops / intel）。
适用对象：Hermes（内容调查、候选生成、校验）与 Codex（宿主 publisher、发布与真实页面验收）。
本文件依据 SOP（PDF 10 页，PDF 原件 SHA256 `acd993fe9d2afde81d5f6deeed5a501225642444ab923c552ba1dcc9952a2bbf`；提取件原字节 SHA256 `45b1a562…f9f`）按**现行 FS 结构**适配后的长期标准；PDF 的旧路径、旧域名、旧现状判断与示例不作执行依据。
首个落地样本：`maplestory`（见 `/profile/game-monitor-sop-20261022/`：AUDIT.md、SOURCES.json、VALIDATION.json、CHANGELOG.md、candidate/）。

---

## 1. 数据模型（现行，唯一落点）

页面为单文件 `index.html`，5 份内联配置按 `key` 精确匹配：

| 配置 | 变量 | 决定栏目 | 缺失后果 |
|---|---|---|---|
| 主档 + 时间轴 | `window.GAME_TIMELINE_DATA.games[]` | 头部、平台、商业化、events（ov 的一部分） | 游戏不在库 |
| 经营打法 | `const PLAYBOOK[key]` | ov / biz / dept（+ tips / gallery） | 回退 `PLAYBOOK_DEFAULT` 通用模板 |
| 工具库 | `const GAME_TOOLS_MAP[key]` | tool 的 tools / wikis | 工具区为空 |
| 攻略库 | `window.GAME_GUIDE[key]` | cls / play / terms / eco / ops | 五个 tab 不渲染 |
| 7 维简报 | `GAMEBRIEFS[key]`（如 `MAPLESTORYBRIEF`） | intel | 回退分组框架或空 |

铁律：**“有 key”不等于“有内容”**。每次维护先判断每份配置是否真的存在该 key，再判断字段是否有实质内容。

## 2. 版本边界（本游戏的核心风险）

MapleStory 同时存在多条产品线：正式服（GMS）、Classic World、MapleStory Worlds、MapleStory M、各地区服（KMS/MSEA/CMS/TMS/JMS）。**禁止混写**。

- 一个 FS `key` 默认只承载一条主线；当前 `maplestory` 采用**单 key + 内容内显式版本分区**：凡涉及等级、职业、Boss、货币、交易、付费的表述，必须能回答“这是哪条线”。
- 版本分区的写法：在同一段落直接标 `Classic` 或 `正式服（GMS）`；术语卡的标签（`k`）写版本适用性（如“正式服专属”“Classic 现金货币”）。
- 只有官方公告明确列出的机制才能写成该版本事实；官方未列的，写“当前版本未见 / 待核”，不因为“系列传统”而默认存在。
- 拆分独立 key（如 `maplestory-classic`）的门槛：①需要独立核算或独立筛选；②radar 与 News 能按 URL 稳定区分两条线；③已评估历史事件迁移、报表口径与外部引用。三条不同时满足，保持单 key。拆分时保留旧 key 为正式服，历史事件不删。

## 3. 十栏目标准

| # | 栏目 | 数量 | 必含 | 判定 |
|---|---|---|---|---|
| 1 | ov | overview 80–150 字；core 100–200 字；tips 3–5；gallery 4 | 上线时间/节点、商业化、当前经营重点；核心玩法循环与付费结构；每条 tip 是一个可执行动作 | 数字类事实必须有官方来源；gallery 图必须有出处 |
| 2 | biz | 4–7 项，对齐七大品类 | name/star/type/focus/desc/why/how/eff/opt/cmp/refs；star 4–5 必写 why/how/eff | 每项 desc 带草稿标记；不写无依据的 GMV 占比/毛利；eff 无证据标“判断/待验证” |
| 3 | dept | **9 行固定**：产品/设计/引流/投放/私域/邮件/广告/技术/生产 | 每条 1–2 句、可执行、带本游戏专有名词 | 每行带草稿标记；不写“加强关注”类空话 |
| 4 | tool | 工具 ≥4 + Wiki 2 | name/url/host/tag/title(≤16 字)/sub/points | 站点必须真实可访问、对版；旧帮助页的机制上限不当作当前版本事实；`visits` 无回执则留空，不编数字、不按流量假排序；无合法截图不填 img |
| 5 | cls | 覆盖当前版本全部职业；热门 4–6 深卡 | classes（简版）+ clsDocs（深版：intro/str/weak/stat/gear/skills/loop/build/aud/tip） | 职业名用官方英文；强度标注写“本版本”并给复核条件；无法全覆盖时在 play/说明中写明范围 |
| 6 | play | 4–5 块 | 是什么 / 怎么玩 / 成长与终局 / 适合谁·社交 / 付费点 | 面向没玩过的同事，30 秒读懂；版本分区 |
| 7 | terms | ≥10 | [术语, 短译, {k,intro,pts,seo,ads,faq}] | 货币与交易类必须核官方；过期命名（如 Reboot）必须更新 |
| 8 | eco | 3–5 块 | 货币体系与官方 RMT 态度、市场热度与交易机制、MMOEXP 落点、价格规律 | 必须写清官方是否允许现金交易；无有效成本与竞品价时只给公式与待补项 |
| 9 | ops | 4 块 | SEO / 投放 / 运营 / 客服 | 每块标题带草稿标记；关键词不臆造量级；客服口径合规、不承诺防封 |
| 10 | intel | 7 维固定：version/market/seo/kol/content/esports/exploit | 每条带日期；只收与经营直接相关 | 无电竞的游戏明确“不适用”并给替代观察，不硬凑 |

## 4. 事实、判断、估算、待核

每段内容必须可归入以下五类之一，且不互相冒充：

- **事实**：有官方或头部社区来源 + 抓取日期 + 适用版本。写入 `SOURCES.json`。
- **判断**：允许有理由的推断（如“Classic 无 Star Force”），必须写出依据（官方公告只列二转与 Lv100），并在同一处给复核方式。
- **估算**：只给量级与算法，不给精确数字；标记“估算”和待补项。
- **待核**：官方未公布、样本不足或无法访问的项，写“待核”并说明缺什么，不用旧数据冒充。
- **经营草稿**：星级、SKU 分层、面额、阈值、组合包、上架与补货节奏、投放与客服口径等经营决策，统一视为 **Hermes 经营草稿·待运营确认**。它必须显示在读者会看到的栏目里（biz 的 `desc`、dept 的每条、ops 的每块标题、ov 的每条 tip），不能只写在审计文件；不得据此执行调价、上架、投放或改规则。没有订单/供给证据的客单、毛利、流水排序一律标“判断/待验证”，不写成已定参数。

禁止项：编造访问量/排名、编造截图或空文件、编造价格与 GMV、把建议写成已执行、把 A 版本的机制写成 B 版本、用“持续关注/优化”替代分析。

## 5. 合规与措辞

- 官方 ToS 将服务限定为个人、非商业、娱乐用途；Banning Guidelines 把账号买卖、NX 买卖、账号共享、Ad Promoting 列为可处罚行为。对客内容只能做合规引导，**不宣称官方授权**。
- 明确写出处罚规则（如 GMS 与 Classic 同一账号一封两服）、交易限制（如新账号 Lv15 后 24 小时）、不承诺解封或防封。
- 本站准入门槛（含成人内容政策）由既有站点策略决定；**本规范不新增、不修改全站准入、账号或权限**。
- 不写外挂、黑卡、复制漏洞的具体操作；不提供规避封禁的方法。

## 6. 发布与验收（职责边界）

1. Hermes 产出：`candidate/index.html`（与基线最小差异）+ `candidate/assets/<key>/` + `SOURCES.json` + `VALIDATION.json` + `CHANGELOG.md`。
2. Hermes 自检（必须实际执行，不是口头）：
   - `tools/verify.py`：范围隔离（把候选数据块换回原块后与基线逐字节相同）、唯一 key、十栏数量、图片存在且非空、外链 HTTPS、script/style 数量、JS 语法编译。
   - `tools/render_check.py`：用页面自身脚本 + DOM 桩执行 `gvRender(key)`，确认十栏非空且无 `undefined`/`[object Object]`。
3. Codex：用宿主既有 publisher 发布（不可变资产目录 + 路由），并做**真实页面**逐 tab 验收（含图片加载、切换、窄屏、浅暗）。
4. 静态检查与 DOM 渲染不等于视觉验收；没有真实浏览器截图时，报告必须写“未做视觉验收”。

## 7. 持续维护（真实入口与接入方案）

**现网事实**：宿主 timer `fs-boss-game-monitor.timer` 为 `Sat *-*-* 00:05:00`（Asia/Shanghai），执行 `fs-boss-game-monitor.service`，完成官方情报采集 + AI 抽取 → `daily.json` / `daily.status.json`，以及 MMOEXP News 采集翻译 → `seo-news.json`（依据：仓库 `releases/fs-dashboard/news-weekly-schedule-20261016/README.md`、`release_timer.py`；页面文案同步为“每周六00:05 北京时间”）。容器内无法读取宿主 systemd，单元实际状态由 Codex 核。

**该周采会更新什么**：radar 事件、游戏详情时间轴（`fsApplyGameDaily` 注入 `daily_events`）、News 卡。
**不会更新什么**：`PLAYBOOK`、`GAME_TOOLS_MAP`、`GAME_GUIDE`（cls/play/terms/eco/ops）以及 `MAPLESTORYBRIEF`（intel 静态简报）。因此**静态九栏与第十栏简报目前没有任何自动更新入口**。

**建议接入（本轮只给方案，不新建调度）**：

1. 频率：跟随现有周采，每周六 00:05 采集完成后（约 07:00 前）执行一次“栏目巡检 + 候选生成”，不新增独立 timer。
2. 触发方式（二选一，交 Codex 定）：
   - A. 在现有 service 末尾追加一个只读巡检步骤（同 timer、同锁），产出候选到归档目录；
   - B. 由 Hermes 的 cron 在原频率读取 `daily.json`/`seo-news.json` 快照后生成候选。
3. 是否重复采集：**不重复**。巡检只读现有快照 + 必要的公开官方页面（版本/职业/政策变更），不重跑官方 News 抓取、不重放历史任务、不改采集信源。
4. 产出与门禁：候选 + VALIDATION + 变更摘要 → 运营确认星级/定价/ops 变更 → Codex 发布。甲级事实类（版本、开服、封禁政策）可自动更新候选，但发布仍需 Codex/运营确认。
5. 双周/月度的额外巡检：tool 的 URL 存活与对版、terms 的新机制、cls 的新职业与平衡改动；用同一候选流程。
6. 禁止：在容器内直接改宿主发布目录、扩大权限、创建与现有 timer 重复的采集任务。

## 8. 每次维护的检查清单

- [ ] 基线 SHA 与线上一致（`baseline.json`）。
- [ ] 只改目标 key 的数据块；其他游戏逐字段相同。
- [ ] 版本分区写清（Classic / 正式服），不混写。
- [ ] 所有新增事实有 URL + 抓取日期 + 适用版本，写入 `SOURCES.json`。
- [ ] 十栏数量达标或有明确缺口说明（`VALIDATION.json`）。
- [ ] 经营草稿在 biz/dept/ops/tips 的页面上可见（不是只写在 AUDIT）。
- [ ] 图片真实存在、非空、有出处；无截图则留空并说明。
- [ ] JS 语法编译通过；唯一 key；外链 HTTPS。
- [ ] DOM 渲染检查十栏非空。
- [ ] CHANGELOG 写明改动、哈希、回退方式。
- [ ] 未发布前不宣称已上线；未截图不宣称视觉通过。

## 9. 版本与留痕

- 本文件版本：2026-10-22（首版，基于 maplestory 落地样本）。
- 关联原件：SOP `SOP-EXTRACTED.md`（raw `45b1a562…`，LF 归一化 `4b74395…`）；基线 `source/index.html` `368a4002…`；候选 `candidate/index.html` `35d15d02…`。
- 后续修订：新增版本条目并标注被替代版本，不就地覆盖历史；历史候选与报告保留。


## 10. 2026-10-22 维护接入读回

服务器主 Hermes 已创建原生计划 `6534331b5100`，UTC `20 16 * * 5`，即每周六北京时间00:20，下一次2026-10-24 00:20北京；已启用，continuity开启，输出留服务器本地。工作目录 `/profile/game-monitor-maintenance`，任务正文为该目录 MAINTENANCE-PROMPT.md。

此计划执行栏目巡检、来源核验与更新候选生成，原00:05官方情报/News采集保持。它没有宿主静态页面发布能力；候选必须按现有发布流程处理，不把定时任务或知识保存说成页面已自动更新。尚未观察首个自然周期。

PR337正式CI已通过；本时点合并请求被自动审批拒绝，等待用户明确批准合并和上线，生产尚未发布。后续发布状态以本任务DELIVERY及 `/profile/game-monitor-maintenance/published.json` 读回为准。

