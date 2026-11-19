# FC27 投放、自然搜索与订单归因

本轮两期为 2026-11-16 至 18 日及 2026-11-09 至 11 日。Google 来源各自保留原时区，GSC 只比较两期已 final 的前两日。收入及广告花费币种为 USD。

- **广告点击增加集中在球员卡系列。** FC27 专属系列花费 $6,087.05 → $4,181.81，点击 3,887 → 5,561，主要转化 118.19 → 108.04，归因价值 $6,783.55 → $4,956.20。每点击主要转化从 3.04% 降到 1.94%，平台 ROAS 从 1.11 升到 1.19。Cards PMAX 点击 776 → 3,038，归因价值 $632.25 → $173.47；其余专属系列点击 3,111 → 2,523、主要转化 100.87 → 99.27。英国实际所在地的价值 $2,092.73 → $857.92，约占专属系列净下降的 68%，其中 UK Buy 和 UK Coins 两条系列应优先检查。跨游戏 FC27-PMAX-Coins-US 花费 $1,128.22 → $1,137.61，ROAS 3.26 → 2.25，经营范围单列。
- **自然搜索从曝光到落地都变弱，法国最值得优先检查。** GA4 的 FC27 自然落地会话 1,229 → 758（-38.3%），购买事件 104 → 36（-65.4%），法国 122 → 34 会话、18 → 0 购买事件，西班牙 61 → 35 会话、10 → 1 购买事件。英国会话 130 → 78，购买事件 11 → 13，不能把所有国家的转化变化归于相同因素。GSC 的 11/09–10 对 11/16–17 点击 388 → 172（-55.7%），展示 12,191 → 6,555（-46.2%），平均位置 7.24 → 12.16。法国 Coins 43 → 3 点击，英国 Coins 32 → 11 点击，英文 Coins 58 → 35 点击。法国先查金币页入口与主要搜索词，英国先查自然曝光和高花费 Search 系列，球员卡集中查低 CPC 流量质量。
- **后台归因不足以判断 PPC 的真实变化。** 共享 ES 的 FC27 付款样本 828 → 699 单、$62,811.57 → $44,857.88。按有效归因，Direct $43,893.30 → $22,211.57，PPC $10,492.05 → $16,633.40。同期 145 单的付款状态修订导致归因无法关联，这期为 5 单。未知归因 141 → 2 单，金额 $8,426.22 → $23.98。仅将同期未知收入全部分给 PPC 的敏感性上界就达 $18,918.27，足以翻转 PPC 增长方向。同期 SEO、Referral 和 Campaign 未返回归因桶，保留为空。按点击假定整单归属或使用 GA4 事件代替付费客户会误导 CAC、渠道收入和预算判断。

## 复跑与口径

1. 使用已授权的 187 封装，把 `releases/fs-dashboard/fc-project-review/traffic.py` 作为 `InputFile` 送入下列只读运行命令，标准输出是一份可供 AI 与页面消费的 JSON。使用 `venv-ssl`，旧 `venv` 的 urllib3 与系统 OpenSSL 不兼容。期间须等长、不重叠且为北京时间已经结束的日期。

   ```text
   /opt/mmoexp-marketing/venv-ssl/bin/python -B - --start 2026-11-16 --end 2026-11-18 --previous-start 2026-11-09 --previous-end 2026-11-11
   ```

2. Ads 来源为 `/var/lib/fs-data-archive/marketing/MMOEXP/<日期>_<日期>/*.json.gz` 中 `value.period.adsAccounts[].calculation_campaigns`、`countries.rows`。选择各自然日闭日后首个自然日内最早的归档，本组六天均在闭日后 19–46 秒内冻结。归因回补可能放大不同年龄快照的差值。确认三账户同为 USD / Asia/Hong_Kong，使用快照 `game_mapping` 的 FC27 专属归属，跨游戏 FC27-PMAX-Coins-US 及有 FC27 名称但未映射的系列各自单列。国家采用 Google Ads 实际所在地，按账户与系列 ID 关联，六天地区花费覆盖专属花费为 100%。平台转化按互动日，CPA 与 ROAS 仅基于 Google 的主要归因转化、价值和花费。 [Google Ads 用户所在地数据说明](https://developers.google.com/google-ads/api/fields/v24/user_location_view)
3. GA4 使用现役 `/opt/mmoexp-marketing/details/collect_details.py` 的 `Reader.request` 访问属性 `541418940:runReport`，按 `hostName`、`landingPage` 和 `sessionDefaultChannelGroup = Organic Search` 过滤，仅统计 MMOEXP 主站的明确 FC27 路径，含已匹配语言目录。事件/会话是事件密度，购买事件与后台订单保持独立。国家取 GA4 原维度，用户数使用源聚合。GSC 同一 Reader 查询 `sc-domain:mmoexp.com`，按主站 FC27 路径过滤，搜索类型 Web 和 final，先通过日汇总核最晚 final，再以两期相同相对日比较，位置采用来源聚合。GSC 明细是 API 可返回的 Top 行。 [GA4 字段](https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema) · [GSC 查询口径](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
4. 订单有效归因在获准的 FS 连接器模块 `channel-effects` 下运行 `channels.facts`，参数 `{start, end, site_id:"all", gid:"1327", status:"all"}`，取 `data_path:"/channels"` 和完整返回范围。原响应 `structuredContent` 传入 `channel_packet(packet["periods"], "all", {"current":..., "previous":...})`，获得去除可识别订单明细的加总。月度及自定义查询按付款日为本期和对照期各自顺序分段。原生每段最多含首尾 28 天，最早为距今 365 天。合并后订单占比与美元销售占比按同一期已取得的合计重算；缺段继续保留已取小计，汇总标记部分覆盖并在 `coverage.<期间>.segments` 保留日期、修订及缺口。两期直接主站参数 `266` 均返回 422，合并结果保留全站请求。对应共享 ES 发布切片只包含 MMOEXP 主站订单。
5. 聚合 `traffic-evidence.json` 保留分来源日期、来源时区、活动记录的来源版本、对照值及缺项。使用 `python -B releases/fs-dashboard/fc-project-review/traffic_test.py` 检查等龄 Ads 挑选、GSC 完成日截齐与缺渠道数值保留空值。

本轮未改投放、价格或生产采集配置。GSC 的 11 月 18 日在本次查询时尚未进入 final。
