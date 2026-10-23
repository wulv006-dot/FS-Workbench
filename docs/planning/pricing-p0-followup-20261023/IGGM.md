# IGGM：FC 与 RPG 采集差异核查（2026-10-23）

结论：RPG 当前能消费 IGGM 数据，主要证据是外部本机推送被服务器接收及复用；不能据此认定 187 服务器当前能从 IGGM 取得新价格。FC 当前原链路在商品页请求阶段收到 Cloudflare challenge/HTTP 403，尚未进入价格解析。官方 FC27 URL 匹配，没有证据支持通过改 URL、规格或单位来修复本次 403。

本次没有改变来源、代理、账号、报价、利润规则或业务调度。诊断候选仅本地 8 项通过，未部署，外部访问阻断仍未修复。

## 已核实的链路

| 项目 | FC IGGM | RPG IGGM 物品 | RPG IGGM 金币 |
|---|---|---|---|
| 当前路径 | 187 原 Chrome 直开 FC27 商品页 | 原 app 优先接受本机推送，足够新则跳过服务器自抓 | 原 core_gold 优先读取本机金币推送文件 |
| 新鲜度判据 | 本轮真实页面、登录/平台/价格校验；失败不补旧价 | `_iggm_local_recent(max_age_s=4200)`，即 70 分钟 | 推送文件 mtime 距今不超过 10800 秒，即 3 小时 |
| 本次观察 | HTTP 403、`cf-mitigated: challenge`，价格解析未执行 | 新接收 2390 条；原任务明示复用已有推送 | 94 个 server_id 的推送，来源说明为本机住宅 IP 代抓 |
| 这些证据能证明什么 | 该来源当次被阻断 | 服务器收到/使用推送；不能单靠入库时间证明生产者新发 HTTP | 服务器可使用推送；不能单靠文件时间证明生产者新发 HTTP |

物品源码中的旧“20分钟”注释不等于活动判据，代码实际是 4200 秒。金币 3 小时判据也不能套到物品或 FC。RPG 历史逻辑还存在非本轮采集组沿用快照的情况，界面有价格或数据库新时间不等于所有商品本轮新抓。

## 原始运行与少量只读探测

以下均为北京时间，保留原任务和失败记录：

- FC 原自然轮 `d5fe7597-73f2-4912-92aa-d91f19c69a9e`，12:53:15 创建，12:55:58 完成输入。IGGM 的 PS/XBOX/PC 均为 `IGGM:http_blocked`、captured_at 缺失。该轮整体仍 `ready_for_quote`，其他已合格来源使原业务继续；不能把这条来源故障写成该轮全部采集失败或新 FC 写价成功。
- 对应原失败证据 `IGGM-e2LxR4h1.failed.json` 为 `reason=http_blocked`、diagnostic={}。原实现没有保留 HTTP 状态和 challenge 类型，这是诊断缺口。
- 14:06:05，通过原 FC collector 的实际读取入口，只增加响应旁观记录，FC 页面返回 HTTP 403、Cloudflare challenge；无报价或写价。
- 14:09:44，在同一原服务器 Chrome、原 open_page 入口，RPG 商品页 `https://www.iggm.com/diablo-4-items` 同样返回 HTTP 403、Cloudflare challenge。只做了这两次有界站点请求，没有变身份、代理或登录，也未继续补请求。
- RPG 原任务 `f039e43a9a4f` 在 13:15:59 明确记录“本机代抓56分钟前推送2390条，本轮跳过服务器自抓”。它用的是当时已有推送，不能将后来 13:30 的接收归给这轮。
- 物品接收回执 ts=13:30:13、pushed_at=13:30:23、saved=2390、src=local。数据库本批与上批 12:20:18 的 2390 个相同商品比较，价格变化 0、站点更新时间变化 0。这并不证明生产者用了缓存，价格也可能没有变化；但服务器现有回执不足以证明生产者刚发新请求。
- 金币推送 ts=13:17:28，文件接收 mtime=13:17:35，说明为“本机住宅IP代抓 core_gold.IggmGold.fetch”，覆盖 94 个 server_id。未获得生产者本次原 HTTP 请求/响应证据。

同服务器两条商品路径都被挑战，支持“不是 FC 单一 DOM 解析错误”的判断；这仍不足以证明只有出口 IP 一个因素，或两条路径采用完全相同 WAF 策略。请求路径、会话及站点策略的影响尚未分离，不能作确定归因。

## URL、平台、币种和单位

FC 活动 URL 为 [IGGM 官方 FC27 Coins 页面](https://www.iggm.com/ea-sports-fc/fc-27-coins)，与官方页面匹配。原 FC 代码平台 ID 为 PS=8、XBOX=10、PC=1，读取 100K 加赠送 K 的套餐，校验可见 USD 与页面字段一致后，以 `套餐美元价格 / (100 + 赠送K)` 换算 USD/K。此次 403 发生在这些步骤之前，没有产生可用于验证解析的新价格。

RPG 另有 `/goods/goods_ajax` 的物品/金币接口及自己的 game/server/category 参数、匿名 CookieJar 与限速。金币模块存在按百万单位返回，其他旧入口有各自默认数量；不能把 RPG 的 server_id、折扣因子、接口参数或单位直接搬到 FC。RPG 原 HTTP 实现存在，不等于本轮走了服务器直采并成功。

## 活动源码映射

| 对象 | 已核实 SHA-256 |
|---|---|
| FC `/opt/fc27-cloud-browser/collector/collect_competitor_browser.py` | `790c5adc0abae4bb46c9975c60517e8457517af4700c6b21bd481d95027ebcc6` |
| FC `/opt/fc27-cloud-browser/collect_competitor.sh` | `6d024dd2270a53c45e302a826b3a24b5df897cd2568d5305c3f94f8123bacbc2` |
| RPG `/opt/d4follow/app.py` | `69e4b48f029e0c4d5b0a8abc05abb14b55304820694ea132bd2828bde9f6ac5a` |
| RPG `/opt/d4follow/core_iggm.py` | `0fe0fe2a3f8223d74c7e4c65de25eefb17ad33a6893b029955d7c2c3742d2510` |
| RPG `/opt/d4follow/core_gold.py` | `6f0967c5b479ca710ec1f8cc36f9104dc7508eaff985d4cde67d4a9a28e9a6e3` |

14:38 独立只读重核 FC collector 仍为上述原 SHA；Lootbar collector 仍为 `4d19dcf18bf6705bbf6aa6590ca660a974f8e1d006b7b9bbd4bb0673f4f52103`，没有拿旧副本替换活动源。

## 建议与交付边界

1. 恢复访问应走 IGGM 认可的入口、API 或出口白名单，再用原 FC 三平台/套餐/币种/时效规则验收。当前证据不支持靠重试、解析改动或借用 RPG 推送冒充恢复。
2. RPG 补齐生产者每次成功获取的证据：实际请求时点、HTTP 结果、商品身份与数量/币种、源数据时间及接收时间；区分“新抓取”“未变化”“缓存沿用”“本轮缺失”。本次未改原 70 分钟或 3 小时规则，也未把新证据要求变成停止自动化的门槛。
3. FC 诊断候选仅为 `http_blocked` 增加安全的 api_method、http_status、cf_challenge 字段，不输出 header/cookie/私密 URL；保留缺失处理与原不重试 403 的行为，不放宽平台、规格、稳定读取或价格保护。

候选位于 `fc_iggm_recovery_20261023/source/collect_competitor_browser.py`，SHA `809bcc0e72ccf52d9b98749a32ad012acbd505d1b5f1ac7aca214a99176fc0f8`，8 项本地测试通过；精确映射见该目录 SOURCE-MAP.json。未执行 Linux/正式 CI/生产发布，未证明外部 403 已解除。原始观察与必要中间证据仅留受忽略的 `.agent_runtime/fc-iggm-recovery-20261023/`，不导出会话、凭据或业务原库。
