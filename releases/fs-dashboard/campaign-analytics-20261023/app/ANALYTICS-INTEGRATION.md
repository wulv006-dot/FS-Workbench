# FS 服务器接入更新 · 2026-10-23

活动看板已部署在 `/dashboard/analytics/campaigns/analytics/`。管理员可持久保存只读密钥、活动配置和商品草稿；正式入口的内部预览不发送追踪事件。网站结账与支付仍待开发接入。服务器运行说明见模块 README.md；下方早期本地说明仅适用于本机预览，不再代表 FS 当前部署状态。

# PostHog + FS 活动页接入 · v3 · 2026-10-23

## 交付状态

三页共用埋点已写入模板和生成片段；普通本地预览仅保存在本机；明确带 analytics_test=1 的联调入口将匿名行为发送到 PostHog，并标记 environment=test。FS 风格看板可切换演示、本机、PostHog 联调和正式数据模式，登记/编辑/导出/导入活动配置。随包提供只读 PostHog 查询适配器，PostHog US项目682816已由用户创建，公开Project Token已核对并写入配置；没有生产接入、没有网站真实结账/支付验收，也未发布到 FS。

- 体验：`http://127.0.0.1:8522/analytics/`，同源活动页：`http://127.0.0.1:8522/`。
- 启动：在本目录运行 `node analytics/server.mjs`。仅监听本机 127.0.0.1；不要将此开发静态服务暴露公网。
- 看板沿用私库本地核对副本 `ui-system/tokens/fs-tokens.css` 与 `components/fs-ui.css`；正式 FS 集成引用当时活动版本，不覆盖共享样式、不直接重放旧发布版本。
- 原本 8520 的站点仍可使用。不同端口属于不同源，本机记录不能跨端口读取。

## 账户进度与待配置项

1. 已创建 PostHog US 项目682816；只读 Query Read 密钥由用户在本机连接页录入，联网查询已成功。真实事件验收以 evidence/posthog-live-acceptance.json 为准，套餐未升级。
2. 项目 ID、US区域、公开 Project Token 已写入 analytics-config.js。Project Token 允许用于浏览器，不是 Personal API Key。
3. 仅 FS 服务端保存具有项目只读查询权限的密钥；通过现有秘密配置方式录入，不能填到 HTML、活动登记表、Git 或聊天文档里。
4. 目前不启用回放、热图或自动捕获所有点击。后续如要启用，单独处理敏感区域遮罩与费用；已实现的明确事件不会因此减少。

截至本次核对，Product Analytics 每月前 100 万事件免费，之后首档 $0.00005/事件；回放独立计费。账单限额与数据保留期按实际选择的套餐配置，超过额度不自动升级。
官方价格：https://posthog.com/product-analytics/pricing

## 配置和文件

| 文件 | 用途 |
| --- | --- |
| `catalog.js` | 商品、SEO、价格体验的唯一配置；capturedAt 同时作为埋点 catalog_version |
| `analytics-config.js` | 公开埋点开关、区域、允许域名、活动 ID 与页面映射；默认 enabled=false |
| `activity-analytics.js` | 三页共享事件桥、前台时长、商品曝光、本机调试与 PostHog SDK 连接 |
| `analytics/funnel-core.cjs` | 浏览器演示与服务端共用的有序漏斗计算，不各算一套 |
| `analytics/server.mjs` | 本机服务 + 可供 FS 包装的只读查询函数；凭据取进程环境变量，可由本机连接页录入内存 |
| `analytics/index.html` | FS 看板预览；不包含 FS 认证替代品 |

`node build-seo.mjs` 会同步三页、片段、SEO和注册表镜像 `analytics/activity-registry.json`。固定活动 ID 不随球员更换；配置内容变更应更新 catalog.capturedAt 为真实资料采集时间，并维护发布版本。旧事件保留原版本，不能回写成新卡。

新活动：在看板登记→导出 JSON→开发审核并写入 analytics-config.js 的 registry→新页提供对应 `view`→挂载同一事件桥（本 FC 模板仍限定 weekly/sbc/trio，新设计需发同一协议事件）→构建并部署浏览器配置与 FS 服务端白名单→验证真实事件。登记本身不创建新落地页、不自动发布、不自动开采集。看板只认已登记的活动；历史活动 ID 永不复用。

## 原站前端接入

原片段新增脚本顺序为 catalog、content、core、host-adapter、analytics-config、activity-analytics、activity。保留 defer 顺序。正式 SDK 由原站构建系统安装并锁定 `posthog-js` 版本，或使用官方安装片段；本包不偷偷拉取 CDN SDK。

```js
import posthog from 'posthog-js';
// 在活动脚本和原站同意管理模块就绪后执行。独立实例不改动其他项目实例。
const bridge = window.FCActivityAnalytics;
const config = window.FC_ANALYTICS_CONFIG;
if (config.enabled && window.FC_ACTIVITY_CONFIG.mode === 'live') posthog.init(config.projectToken, {
  ...bridge.sdkOptions,
  loaded(instance) {
    bridge.connect(instance);
    bridge.setConsent(existingConsentManager.analyticsAllowed());
  }
}, 'fc_activity');
// existingConsentManager 是原站模块占位名，需要开发映射到真实模块。
existingConsentManager.onAnalyticsChange(value => bridge.setConsent(value));
```

仅在生产模式、enabled=true、域名白名单匹配、SDK就绪、已允许统计时发送。不要把 `consentRequired` 设为 false 绕过接入；当前桥始终等待原站明确 setConsent(true)。撤回同意后停止；不补发此前未授权的行为。页面失败、禁存储、SDK失败不能中断购物。

SDK 禁用自动页面浏览、autocapture、回放与个人画像；before_send 只允许本协议事件和白名单属性，避免 SDK 自动携带完整 URL/查询串、邮箱、登录账户、订单表单。埋点 URL 只记录固定配置路径/活动ID；UTM只接受有限格式，运营不要在 UTM 中放客户信息。新活动设计不得将自由文本、邮件、支付凭据放入事件。

## 事件协议 v1

公共属性：schema_version=1、activity_id、catalog_version、view、platform(ps/xbox/pc)、language、environment(production/preview)、device(mobile/desktop)、activity_visit_id、activity_session_id、source、campaign、event_id。设备按当前视口断点划分，不声称硬件识别。来源为简化入口分类，不替代 GA4 的归因模型。

| 事件 | 触发与附加属性 | 谁负责 |
| --- | --- | --- |
| activity_view | 首次进入或切换活动，生成新 activity_visit_id | 已实现 |
| activity_product_view | 商品卡至少50%面积进入可见视口；每访问批次每商品去重，非停留1秒定义 | 已实现 |
| activity_click | 固定按钮/链接 target；不记录自由文本 | 已实现 |
| activity_selection | product_ids、core_id、include_sbc、action | 已实现；列表是当时选择快照 |
| activity_review | 成功打开核对清单；product_ids、include_sbc | 已实现 |
| activity_cart_result | confirmed_ids、complete、failed_count；未知不算成功 | 已实现事件桥；真实购物车回执仍待接 |
| activity_add_to_cart | 仅 live 且原适配器确认为 confirmed 的商品；部分成功仅记录确认项 | 已实现事件桥；现有9折后端未接，不能称真实加购已验 |
| activity_scroll | 25/50/75/100深度，活动切换重置 | 已实现 |
| activity_engaged | active_seconds 增量；前台定时累计，隐藏、离开、换活动时提交 | 已实现；挂起及异常关闭会少计，非精确阅读时长 |
| activity_begin_checkout | 后台创建有效结账会话/订单草稿后，携带同一归因上下文 | 网站开发新增 |
| activity_purchase | 支付后台确认成功，order_key、currency=USD、activity_paid_minor | 网站开发新增，浏览器禁止代发 |
| activity_refund | 原order_key、退款事件ID、活动商品真实退款USD整数分 | 网站开发新增；第一版看板不扣退款，金额标注未扣退款 |

## 网站开发必须配合的地方

### A. 购物车与活动资格

在原站获准的活动加购请求中附加 `FCActivityAnalytics.context()` 的结果（未允许追踪时为 null）。活动优惠资格必须单独按服务器活动配置校验，不能因没有统计同意而取消合法九折资格。

服务器校验活动ID、有效期、商品ID/平台、数量、金额和优惠叠加合同；将归因上下文与本次成功加购的每条购物车商品绑定。浏览器给的价钱、收入、权限都不可信。购物车合并/同SKU再次加入时保留明确的归属数量；不把非活动行归给活动。不要只依赖 HTTP Referer、优惠码或最后打开的标签页。

context 返回 activity_visit_id、activity_session_id、activity_id、catalog_version、source/campaign、device/platform/language 和 PostHog distinct_id。独立访客无需强制注册，不能把 UID=0 排除。不同域名或支付跳转由服务器保存上下文，不在 URL 暴露客户身份。未来支持跨设备时另行设计合规身份映射，不使用原始邮箱 identify。

### B. 进入结账

“点击前往购物车”不是进入结账。结账会话真正创建后，网站服务端按活动归属发送 activity_begin_checkout。每个 checkout_id + activity_visit_id 唯一，刷新不重复；混合活动订单按各活动的商品归属拆出事件。后端携带上游 distinct_id 以保持 PostHog 身份，不另造新访客。

### C. 支付、金额与退款

支付网关可信回调/后台支付状态确定成功后，用事务 outbox 保存唯一事件（order_key + activity_visit_id + purchase）。order_key 建议为服务端不含客户信息的稳定匿名订单引用；同一订单一个活动有多批次时先按明确的订单行归因策略归并，不能重复分配金额。优惠券/码/积分按原订单真实分摊后的活动行USD实付汇总为 activity_paid_minor；不拿前端展示价当成交、不把GBP金额写成USD、不把整单收入归给活动。Admin为经营事实主源，Order仅补缺；可用0与未知分开。

重试始终使用同一事件 UUID/幂等键和原支付时间，未知结果先查原回执。服务器发送 `$process_person_profile=false`，不采集个人信息。浏览器不得发送 purchase。退款保存退款实际金额和唯一退款ID，保留原支付事件；第一版金额是未扣退款的归因实付，不能叫净收入/利润。

服务端协议示例（数值均为虚构，不是实际价格）：

```json
{"event":"activity_purchase","timestamp":"2026-10-23T10:00:00Z","uuid":"稳定的事件UUID",
 "properties":{"distinct_id":"此前获准的PostHog匿名ID","$process_person_profile":false,
 "schema_version":1,"activity_id":"fc27-sbc","activity_visit_id":"原活动批次UUID",
 "activity_session_id":"原会话UUID","catalog_version":"原配置版本","environment":"production",
 "device":"mobile","platform":"ps","source":"organic","order_key":"匿名订单引用",
 "currency":"USD","activity_paid_minor":3600}}
```

## FS 接口与运维接入

本机适配器使用 `POSTHOG_PROJECT_ID`、`POSTHOG_QUERY_KEY`、`POSTHOG_QUERY_HOST`（https://us.posthog.com 或 https://eu.posthog.com）。密钥不通过浏览器配置、不进入ZIP。本地可用环境变量后启动 server.mjs；服务器秘密使用既有凭据系统。

正式 FS 在现有认证/授权路由内挂载只读 `GET /analytics/api/report`（按实际模块挂载前缀适配），复用现有权限、请求审计和统一主题。请求字段 activity/from/to/device/platform/source；from/to 使用UTC自然日；成功返回 `{status:'available',generatedAt,coverage,report}`。缺配置503、参数无效400、上游错误502；不能回退演示数据。前端有加载、失败、无数据状态。

适配器每查询最多31天，从起始日读到结束日后24小时以覆盖转化窗口；只查production及活动白名单；只取白名单字段，不输出原始事件给浏览器。单次上限50,000事件，超过直接拒绝完整报告并要求缩小日期范围。5分钟缓存、同进程单查询、15秒超时；未来流量超过上限应改为PostHog端聚合/异步分页，不能悄悄截断。当前没有后台定时任务，看板点击更新触发只读查询；自动更新频率接入FS后另按原调度合同配置。

## 统计定义与限制

- 主漏斗：同一 activity_id + activity_visit_id，在首次 activity_view 后24小时按顺序完成 view→product_view→add_to_cart→begin_checkout→purchase。以首次访问的设备/平台/来源过滤。步骤缺失不能补齐。
- 正式访客UV/点击访客按PostHog distinct_id去重；预览以activity_session_id回退，标为本机会话。匿名浏览器ID不是跨设备真实人数，也不是客户新老客。
- 日期选择的是访问批次开始日期；不是将当天付款除以当天访客。UTC口径固定，FS其他经营页时区不同须显式标注。
- 归因实付是另一个指标：同批次窗口内真实 purchase，按 order_key 去重，即使浏览器中间步骤缺失也可有金额。付款漏斗人数与订单数不强行相等。没有 activity_view 的订单需另做归因缺失对账，本看板不冒充全站营业额。
- 本机事件保留最近1500条，超出会淘汰；仅用于验证触发，不能用于经营分析。演示数据固定且虚构，新增活动默认无数据。
- 未授权、广告拦截、离线、异常关闭、跨设备均可能少计。原站订单对账另行统计覆盖率，不能承诺100%还原每个人。

## 上线验收清单

1. 三页首次进入/切换各一条 view；商品重复渲染不重复曝光；手机/桌面和中英文都可操作。
2. 未同意/撤回/预览不向PostHog发送；SDK与存储失败不影响购买；事件中无邮箱、账户、支付资料或完整URL。
3. 商品/平台/SBC切换的ID和include_sbc正确；已有核心不出现在购买行；改球员配置后事件和SEO同步。
4. 加购失败、部分成功、未知回执分别核验；预览确认不产生 add_to_cart、begin_checkout 或 purchase。
5. 网站测试环境真实走通原站加购→结账→支付；同一distinct_id/activity_visit_id贯穿；支付回调重放不重复金额。
6. 混合活动/非活动订单、合法优惠叠加、游客、退款和跨日转化，与后台订单行逐项对账。
7. FS权限、密钥隔离、真实项目API、金额单位、完整性上限、过期/失败状态和主题在实际环境另验。

官方依据：
- SDK：https://posthog.com/docs/libraries/js
- 查询：https://posthog.com/docs/api/queries
- 漏斗：https://posthog.com/docs/product-analytics/funnels
- 服务端SDK：https://posthog.com/docs/libraries/node

## 本机连接与联调（v4）

打开 /analytics/connect.html，输入仅限项目 682816 的 Personal API Key（Query → Read）。密钥仅保存在该进程内存，重启必须重录，不在聊天、浏览器持久存储、开发包或日志内。连接页的“已保存”不等于查询成功；以看板真实查询和验收记录为准。

测试入口 /?analytics_test=1 仍然是预览商品页，只允许行为事件，通过本机服务上传匿名测试标识，不创建真实购物车、支付或券。未知发送状态保留原 event_id 不自动重试。测试查询缓存 3 秒，正式查询缓存 5 分钟。正式发布仍由原站 SDK 直接发送；本机转发仅为接入验收。

配置新增类型、状态、负责人、版本、域名、周期、窗口、赛事映射。日期均为 UTC。状态仅记录计划，不控制真实业务。活动及赛事 ID 不复用。Matchday 开发接入与验收详见 MATCHDAY-ANALYTICS-PLAN.md。

查询采用 PostHog 官方 refresh=force_blocking，以本地缓存限制频率，避免旧空结果冒充最新数据；JSON 数组、布尔与金额按合同还原类型。此适配器为有界低流量验收，最多50,000条且拒绝截断；正式高流量改为服务端聚合查询/物化视图，不扩大原始事件拉取或另建周期导出。官方依据：https://posthog.com/docs/api/queries

2026-10-23 v4最终验收：PostHog实际查询读回23条行为事件，三活动各1访问和1清单查看；1个匿名测试访客，SBC代做选择1次。40项逻辑、8组响应式/主题、连接失败与成功状态检查通过。连接页仅在真实查询通过后隐藏输入框并显示绿色已连接；更换密钥可显式展开。结账/支付/竞猜后端与生产发布均未执行。
