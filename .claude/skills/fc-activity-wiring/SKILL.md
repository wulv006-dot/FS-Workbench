---
name: fc-activity-wiring
description: FC27/MMOEXP 活动页（www.mmoexp.com/events/*.html）的接线与交付：发券（统一优惠券）、主站登录态、结账交接、页面数据追踪、FS 消费归因（优惠码与优惠券）、发布到 187 和线上验收。新活动页上线要接券/登录/追踪，已有活动页改接，或核对优惠券使用与转化时使用；只改活动页文案、视觉、选品而不涉及这些接线时不触发。
---

# 活动页接线：发券 · 登录态 · 追踪 · 归因

本技能把 2026-11-16 在 Weekly Scout / SBC Companions / Player Trio 三页上做通、并上线验证过的接线方法整理成流程，供新活动页复用。**不新增、不改变任何规则**：权限、授权、发布和交付以仓库根 `AGENTS.md`、`docs/ops/HOTFIX.md` 和对应活动合同为准，冲突时以它们为准。改仓库前先用 `fs-task` 开工。

活动页的内容和结构按 `docs/standards/fc27/DESIGN-TEMPLATE.md` 与活动合同（如 `docs/planning/activity-center-v3/`）；视觉评审用 `design:*` 技能。本技能只管接线，不管设计。

## 先拿到的输入（缺哪项就先问，不要猜）

1. **活动需求**：折扣档（例 10%）、券有效期、活动起止、哪几页参与、是否沿用统一券还是新券、是否保留优惠码路径、购买方式（逐张加购 / 整组加购）。
2. **工程包**：页面 HTML 和资源（图片、样式）、商品配置（`catalog.js` / 发布配置里的 `page_id`、`product_key`、原生 `Cart/add` 行）、页面路径（`/events/<Name>.html`）。
3. **Admin 侧事实**：券模板 ID 和 `param_code`、入口券所属槽位（slot）、TempActivity 的开关和起止。**这些是生产 Admin 数据，创建或修改属写操作，需用户明确授权**；只读核对随时可做。
4. **验收账号**：由用户提供或明确授权；技能里不保存任何账号、密码或令牌。

## 总体结构

- 活动页和主站同源（`www.mmoexp.com/events/…`），直接共用主站登录 Cookie；页面源码在模块 `releases/fs-dashboard/campaign-analytics-20261023/app/`，经 187 的发布器部署。
- **发券**：页面调主站 `/ajax/carnival/*` 三个接口，登录后领一张统一券，把券的会员券 ID 交给购物车自动选中；**有券就不再走优惠码**，只有券服务整体关闭时才静默回退到优惠码。
- **登录态**：未登录在活动页内弹自有登录框（邮箱 + Google + Facebook），顶栏仿主站显示登录态；不搬主站登录组件。
- **追踪**：线上活动页用的是 `app/seasonal/activity-analytics.js`（不是顶层的 `app/activity-analytics.js`），事件进 PostHog，需访客同意。
- **归因**：优惠码销售保留；优惠券另读 Admin 的券记录和 `user/memberCouponLog`，在 FS 看板单独成面板，并给出码+券合计。

细节分别在 `references/` 下，开工前按需读：

| 文件 | 内容 |
|---|---|
| `references/apis-and-fields.md` | 主站 carnival 与登录接口、Admin 配置和只读接口、`memberCouponLog` 字段语义 |
| `references/touch-points.md` | 新增一个活动页要改的全部位置（按文件） |
| `references/tracking-and-attribution.md` | 事件、隐私边界、漏斗到看板的链路、券归因口径 |
| `references/release-and-verify.md` | 测试工具、发布步骤、发布后价格窗口、真实入口验收、交付记录 |
| `references/pitfalls.md` | 已踩过的坑（先读这个能省很多时间） |
| `scripts/make_stage.mjs` | 生成 187 发布包和 inspect 脚本（自动补发布器要求的依赖文件） |
| `scripts/drift_check.mjs` | 发布前核对线上文件与上一版仓库内容有无漂移 |
| `scripts/playwright-shim.index.js.template` | 本机没有 npm 时用本机 Chrome 跑浏览器测试 |

## 流程

0. **开工**：`fs-task`；确认任务归属、worktree、基线；CodeGraph 显式传本任务 worktree 的绝对路径。读 `references/pitfalls.md`。
1. **对齐需求与差异**：把输入逐项对照 `references/touch-points.md`，列出"沿用 / 新增 / 修改"三类，发现需要写 Admin（建券、改 TempActivity）时先停下来向用户列清单并等授权。
2. **券与槽位**：沿用统一券则只需把新页的 `page_id` 映射到一个 slot，并确认 Admin 的 `carnival_slot_coupons` 已含该 slot；新券则同时要扩 `FC_COUPON`（目前是单个常量，见归因文档）。先用只读接口核对券的 `param_code`、`fetch_scene`、站点和游戏。
3. **页面接线**：按 `touch-points.md` 逐项改；结账交接、整组加购、登录框直接复用现有函数，不复制。
4. **追踪与归因**：新页加进追踪器的路由表、活动注册和漏斗里的活动列表；事件字段只增不带账号标识；券归因按页面合计，如需分页要先和用户确认口径。
5. **测试**：先写或改测试再改实现；本地用 shim 跑相关浏览器用例；改动前就红的用例先在基线上确认再排除。
6. **PR**：CI（`pr-fast`）通过即可合并（用户已长期授权）；落后于 main 先 `gh pr update-branch`；偶发失败先看是否为已知时序问题，再重跑，不要硬改测试。
7. **发布**：用 `scripts/make_stage.mjs` 生成发布包，先 `inspect`，核对线上文件与上一版仓库内容无漂移，再 `apply`；备份点写进交付记录。
8. **统一验收一次**：按下面清单在正式站读回；不替访客点统计同意，不输入密码。
9. **记录**：`DELIVERY.md` 追加一节（来源 PR、发布文件、读回结果、未验证项、回退点）；只追加。

## 硬性边界

- 登录密码、验证码、统计同意：**绝不替用户输入或点击**（包括 Chrome 自动填充的密码）；邮箱登录由用户本人提交，Google 登录用用户已授权的 Chrome 登录态。不退出用户账号，需要时请用户自己退出。
- Admin 写操作（建券、改 TempActivity、改优惠码）、真实订单和付款：需要用户明确授权；验收只做只读和到购物车为止。
- 不在页面、事件、日志或文档里放邮箱、UID、会员券 ID、令牌。
- 不清空访客购物车来"修复"加购问题；根因在操作记录，见 `pitfalls.md`。
- 不覆盖线上不在静态清单里的文件（例如 `page-template.html`、`activity-fragment-*.html` 线上与仓库本来就有差异），只发本次改动文件及发布器要求的依赖。
- 券的 24 小时限领目前只在浏览器本地账本里执行，服务端冷却需要主站开发实现；不要对外宣称已有服务端限制。

## 验收清单（正式站，一次做完）

1. 三页（或新页）HTTP 200，页面脚本带新版本号。
2. 未登录：顶栏是 Log In；点结账弹出登录框，此时没有任何购物车请求。
3. 登录后（用户操作）：领到会员券 ID，购物车自动选中，折扣金额正确；不再写优惠码。
4. 整组页（Trio/SBC）：卡片上没有单张按钮，一个按钮整组加入。
5. 同一标签页连续选两套不同阵容，第二套正常进购物车。
6. 发布后约 1 分钟内价格可能显示 `Price unavailable`（价格同步），等同步完成再读回，不要据此判断失败。
7. 后端读回：已部署的 `coupon_usage` 对该券返回累计发放/使用；FS 看板 FC27 面板出现券面板，且优惠码面板仍在。
8. 未做的项（统计事件的真实触发、真实用券订单、手机宽度实机）在交付记录里写明，不写成已验证。
