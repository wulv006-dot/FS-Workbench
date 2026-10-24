# D · 独立运营配置补缺 04

任务：FS-V3-G1-COMPLETE-GAPS-04；base `63ecbeb`；工作树 `campaign-gaps-d` / 分支 `codex/fs-campaign-v3-gaps-ops-ui`。仅本地实现与测试，未修改旧 campaign-d、PR434、stage，未 SSH、合并或部署。

## 已复用、补齐与不适用

| 项目 | 原有实际覆盖 | 本次结果 |
|---|---|---|
| 商品选择/编排 | products UI；FC Weekly/SBC/Trio 已发布 product_keys 投影；Seasonal 原 18 套快照与原玩法 | 复用；不复制商品编辑器、不改商品图或购买映射 |
| 原素材 | FC 各页一组既有桌面/移动 hero；Seasonal 四主题与对应 hero、creative-kit | 固定主视觉保留。新增的社交图选择仅本页既有 hero 白名单；不跨页换 FC hero、不上传、不接受任意 URL。Seasonal 已有发布 theme→runtime-bridge→event.js 的消费闭环已核实并复用 |
| 语言 | FC 原 zh/en 内容与用户切换；Seasonal 原稿仅英文 | FS 每页新增 default_language：original/en/zh，Seasonal 只 original/en；未新翻译。原文英文/中文内容不变 |
| SEO | title/description 已保存、发布并由 presentation 实际消费；原 canonical/URL 与 noindex 边界 | 新增 social_image 白名单选择→发布→绝对 OG/Twitter image；显式默认语言同步 HTML lang、OG locale 与 CollectionPage inLanguage。不开放 arbitrary canonical、域名或 URL 编辑 |
| 有效期/发布读回 | 原 starts_at/ends_at/preview_enabled、CAS、原操作恢复、不可变发布版本 | 复用；补已发布 source_revision/hash/time/pages/theme 摘要、固定页面预览入口和公开 runtime config 的 release/config_hash/rule_hash 回读比对。明确持久发布记录不等于部署成功 |
| 原玩法 | Weekly 原页签/选择；SBC owned/service、搭档、平台；Trio 与固定组合；Seasonal 抽取/揭示/保留/刷新/DEMO 邀请 | 不改原玩法。语言改动实际回归 SBC 与既有 FC 发布保护；Seasonal 未改源码，验证其既有 theme/query 覆盖、手切主题和八卡抽取仍在 |
| 原生优惠/经营规则 | 后台原生 benefit_refs 与未完成主站接入边界 | 不在本次呈现补缺中重做；未开购买、未改抽奖概率/优惠叠加/邀请资格/售价成本 |

## 合同与消费路径

- `center-store.validateDraft` 为四个固定页面校验 `default_language`、`social_image`。旧草稿字段缺省统一为 `original`，不默默替换已接受素材。
- `runtime/snapshot.mjs` 的 `presentationOptions` 是服务端单一白名单；投影拒绝外链、路径穿越、跨页 FC hero、未知语言、Seasonal 中文。原稿只有英文时不制造翻译选项。
- `center-store.publish` 把安全字段纳入配置哈希与公开 snapshot，并在管理发布记录保存页面/主题摘要；原生 benefit 引用依旧不进入公开快照。
- `presentation.presentPage` 实际消费语言与 OG/Twitter 图，保留原 hero 和 canonical。显式图片必须提供可信 `publicBase`；无有效 base 或含凭据/查询/非法协议时 fail closed。
- 主控集成一行：`runtime/server.mjs` 调用 `presentPage` 时增加 `publicBase:new URL(prefix,origin).href`。origin/prefix 来自已有受校验的服务配置，不读请求 Host；D 未修改 server 文件。
- 语言优先级：显式 FS 默认用于首次打开；`original` 保留原 HTML 默认；用户在当前页面的手动语言选择优先，晚到的发布读取与后续报价/页签读取不重置手选。新页面/刷新重新采用该页面 FS 默认，保持原来不持久化用户语言的行为。
- 分享图 `original` 保留原 SEO 素材/缺省，其他值只允许 FC 本页桌面或移动 hero；Seasonal 仅四套既有 theme hero。分享图选择不替换页面 hero，也不伪造新的产品图。
- FS 公开回读默认 `/events/`；如部署使用自定义 prefix，需由可信 HTML `data-campaign-public-prefix` 提供，仅接受 slash-delimited 内部路径，不开放输入框或 query flag。

## 可复验依据

在 `releases/fs-dashboard/campaign-analytics-20261023` 执行：

```powershell
node --test app/analytics/tests/center.test.mjs app/runtime/tests/*.test.mjs app/tests/ops-presentation.test.mjs app/tests/activity-core.test.cjs app/tests/activity-pricing.test.cjs app/tests/host-adapter.test.cjs app/tests/seo.test.mjs
$env:NODE_PATH='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
node app/tests/center-browser.cjs
node app/tests/fc-published-browser.cjs
node app/tests/ops-presentation-browser.mjs
```

结果：53 项 Node 测试通过，三组浏览器测试通过，`git diff --check` 通过。

新增 `ops-presentation.test.mjs`：旧配置兼容、白名单文件实际存在、非法/跨页图片与语言拒绝、真实 store save/publish、发布快照与记录吻合、实际 HTML lang/OG/Twitter/JSON-LD 消费、无 publicBase 或非法 base 拒绝、原 hero/canonical 保留。

新增 `ops-presentation-browser.mjs` 使用本地 HTTP、实际 center store、snapshot、presentation 与 FC/Seasonal 原页面（管理员会话/CSRF 为本地 fixture），验证 FS 保存→重载→发布→公开快照回读→真实浏览器呈现；延迟发布读取期间用户手切语言仍优先；SBC 2→3→2；Seasonal 发布 Christmas 覆盖 query Halloween，仍能手切 Thanksgiving，八卡原玩法不丢失。没有把 fixture 当作生产会话或真实交易验收。

## 状态与剩余项

- 本地源码/持久化/发布投影/实际浏览器消费已验证；需要主控集成上述 publicBase 一行并在同候选执行相同相关测试。
- 公开运行时实际生产版本、187 读回、权限会话、部署后素材与 HTML 回读未执行，待用户明确审批；首次 merge 自动拒绝且已知未执行的边界未绕过。
- 主站真实报价/购物车/支付/优惠核销未开放，本次不宣称 G2 完成。
- 使用 Modern Web Guidance `select-menu-interaction` 与 `accessible-error-announcement`：保留 required 原生 select 和交互后校验，延续 capture-phase ARIA 同步（“blur and focus do not bubble”），不在初次加载给合法默认选项报错。
