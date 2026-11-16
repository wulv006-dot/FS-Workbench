# 新增或改接一个活动页：要改的位置

路径都相对模块根 `releases/fs-dashboard/campaign-analytics-20261023/`。页面的"视图名"（`weekly`/`trio`/`sbc`）和 `page_id`（`fc27-weekly`…）一一对应，活动 ID 目前是 `fc27-season2`（三页合计）。**下面是 2026-11-16 用 `grep` 在源码里找到的全部枚举点**；新页上线前用 `grep -rn "fc27-trio" app backend` 再扫一遍，防止后来新增的位置漏掉。

## 页面与配置

| 位置 | 要做什么 |
|---|---|
| 页面 HTML（`app/<Name>.html`）及生成它的 `app/build-seo.mjs`（`{weekly:'Weekly-Scout.html',…}[view]`）、`app/page-template.html`、`app/activity-content.js` | 新页 HTML 和 SEO 输出；`build-seo.mjs` 里按视图取路由和文件名。线上的 `activity-fragment-*.html`、`page-template.html` 与仓库本来就有差异，不随普通发布覆盖 |
| `app/catalog.js` / `catalog.json` | 商品、平台、`weekly/trio/sbc` 分区配置；整组页的商品 ID 列表（`config.trio.ids` 等） |
| `app/activity.js` | 用 `'fc27-'+view` 取发布配置里的页面；整组页的 `groupExpected/groupReady/groupPicked/groupBar`（Trio 三张、SBC 两搭档 + 可选服务）；新页如果也要整组加购，复用这套函数 |
| `app/activity-core.js`（约 118 行） | 原生优惠绑定里允许的 `page_id` 列表 |
| `app/native-code-handoff.js` | `COUPON_SLOTS`（`page_id → slot`）；`projectConfiguration` 里允许的 `page_id` 列表（约 48 行）；`checkoutPublished` 结账交接 |
| `app/runtime/snapshot.mjs` | `pageRoleOptions`、`rolePageByPath`（路径 → `page_id`）、`COPY_PAGES` |
| `app/analytics/center-store.mjs`、`center-seed.mjs` | 配置中心里页面登记（`[page_id, activity_id, 文件名, 显示名]`） |
| `app/analytics/launch-compiler.mjs`（约 34 行） | 上线编译对 `page_id`、折扣、游戏的范围校验（目前要求 90 折、游戏 1327） |
| `app/analytics/production-server.mjs` | `publicNames`（对外可取的静态文件名）、预览页列表（约 107 行）、页面角色条目校验（约 122 行） |
| `app/analytics/native-catalog.mjs`、`weekly-*.mjs`、`weekly-commerce*.{mjs,py}` | 周更工作流里的页面列表；只有新页进周更流程时才需要 |

## 追踪与看板

| 位置 | 要做什么 |
|---|---|
| `app/seasonal/activity-analytics.js` | 第 6 行 `fcRoutes`：路径 → 视图名（含 `/events/…` 和 `/Fc-27/…` 两套）；`formalFc` 只在 `https://www.mmoexp.com` 且路径在表内才算正式；第 144 行按 `fc27-<视图>` 找发布配置 |
| `app/analytics-config.js` 与 `app/analytics/activity-registry.json` | 活动注册：`id`、`view`、`name`、`path`、`type`、`windowHours`；`enabled`、`allowedHosts`（仅 `www.mmoexp.com`）决定能否上报 |
| `app/analytics/funnel-core.cjs`（第 3 行 `fcActivities`） | 活动 ID 规范化列表，新页要加进去才会并入 `fc27-season2` |
| `app/analytics/report-context.mjs`、`statistics-refresh.mjs` | 看板的页面查找与计划汇总里的页面列表 |
| `app/analytics/discount-revenue.mjs`、`coupon-usage.mjs` | 允许的活动名单（`fc27-weekly`/`trio`/`sbc`/`season2`）；新页要加 |
| `backend/campaign_backend/discount_revenue.py` | 优惠码：`FC_BINDINGS`（原生 ID、码、游戏、折扣）；优惠券：`FC_COUPON`（单个常量） |

## 发布器

`publish.py` 的 `BACKEND_FILES` 是后端 Python 文件白名单。**新增 Python 文件不在白名单里会被拒绝**——优先把代码放进已部署的文件（例如券归因放在 `discount_revenue.py`），确实要新文件就同时改 `publish.py` 的白名单，并在 PR 里单独说明。静态文件（`app/` 下 `.js/.mjs/.cjs/.html/.css/.json/图片/字体`）不用改白名单。

## 做之前的判断

- **沿用统一券**：改 `COUPON_SLOTS`、Admin 的 `carnival_slot_coupons`、上面各处 `page_id` 列表，不用动 `FC_COUPON`。
- **新券（不同模板 ID）**：`FC_COUPON` 要从单个常量改成"活动 → 券"的映射，`coupon_record` 的身份校验、`coupon-usage.mjs` 的 `coupon_id` 校验和看板文案里的 ID 都要跟着改；读取仍是只读。
- **新页要分页归因**：三页共用一张券，券记录里没有页面信息；要按页拆分只能靠页面事件和会员券的关联，这会把会员券 ID 引入事件，需要先和用户确认隐私口径，默认不做。
- **新活动不是 FC27**：站点、游戏、折扣档、原生商品行都不同，`projectConfiguration` 的白名单要重新审，不能直接复用 FC 的范围校验。
