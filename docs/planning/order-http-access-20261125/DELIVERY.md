# Order 后台访问去浏览器化：交付记录

2026-11-25，Asia/Shanghai。方案见 [PLAN.md](PLAN.md)，消费者与退役盘点见 [CONSUMERS.md](CONSUMERS.md)、[RETIREMENT.md](RETIREMENT.md)，协议见 [ORDER-PROTOCOL.md](ORDER-PROTOCOL.md)。

## 结果

187 上 Order 的会话、P0 成本采集和看板消费者已全部改走 HTTP，不再经浏览器访问 Order。

| 范围 | 发布 ID | 真实入口验收 |
|---|---|---|
| fs-order-session（HTTP 会话、gzip、外部顶号识别） | `order-http-20261125T062350Z` | ready；探活 2.7–22.7 秒；登录 1 次；sessions_lost_externally=0；宿主与成本容器 socket、销售 order_alive 通过 |
| P0 成本采集（order_http + 连接复用） | `nav-20261125T062730Z` | 14:28 手动采集 127.8 秒三平台 valid；15:15 自然轮 147.7 秒，报价 READY、轮次 confirmed、PS 执行 CONFIRMED |
| 阶段 3B：全局/RS 发货统计、渠道成本、销售采集 | `nav-20261125T071858Z`–`071901Z` | 11-24 范围 API 200/available 与切换前一致；渠道成本、销售同窗口明细哈希一致；实际利润 200、costError=false |

逐文件前后 SHA-256 与备份路径见各发布回执（`/var/backups/order-http-20261125T062350Z`、`/var/backups/fs-navigation-20261006/<发布 ID>`）。

## 相关 PR

#1357 方案 · #1358 盘点 · #1359 会话 HTTP · #1360 order_http · #1361 成本采集切 HTTP · #1363 python39 与现场基线 · #1364 阶段 3B · #1365/#1367/#1368 登录预热、跳转、时限与消费者不排队 · #1366 order-http-cost 发布范围 · #1369 改用 wulv 账号 · #1370 真实页面解析与 gzip · #1371 单会话门禁 · #1372 详情连接复用。

## 事故与规则

- 12:00 前后用 MLB 账号试登录，Order 回复「未设置谷歌验证器」，同时顶掉了原浏览器会话，P0 约 12:00–13:15 无写价（无错价）。根因：Order 只对 wulv、chenchao 免谷歌验证器，同账号任何新登录都会顶掉已有会话。
- 处理：会话服务改用 wulv（凭据 `/etc/fs-order-session/order-account.json`，root 0600）；MLB 的 `_cred_order.json` 按用户要求删除，`mlb-online` 的 `coins_rate.cred` 指向同一文件（MLB 本就经共享会话取 cookie）。
- 规则（用户要求程序约束）：AGENTS.md「Order 后台单会话」；pr-fast `order-single-session` 拦截新增的 Order 登录代码；会话服务记录 `session_lost_externally`。
- 14:15 自然轮旧浏览器采集器自身达 180 秒上限未取得成本（无写价），与会话无关。

## 未完成

- 15:15 自然轮采集 147.7 秒，距包装脚本 180 秒上限余量小。用户已提出列表页正常记录免详情复核、仅异常单进详情（定价规则变更，待用户确认放行条件后按 fc-pricing-change-review 处理）。
- 阶段 5B 退役：`fs-order-browser` 容器与 `raw_node_helper.js` 已无会话用途；旧标量 DOM 写价、`range_primary_reader`、`fc_order_reader` 按 RETIREMENT.md 待核项处理后再移除。
- 用户在对话中提供过 wulv 密码，建议轮换后更新 187 配置文件。
