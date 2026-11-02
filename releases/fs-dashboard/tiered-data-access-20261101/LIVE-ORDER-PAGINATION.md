# 实时订单按需查询：当前调用规则

本规则对应已上线 `nav-20261102T150526Z`，PR757 合并提交 `0ab6b02354b28d8071755581e762b8ab95748f34`。它替代旧版“一天、第一页、最多五条”说明。生产发布不等于全部业务场景验收；当前实际验收范围见下文。

## 入口、权限与范围

在现有 FS 登录会话中使用 `/dashboard/users/live-orders.json`。身份由原登录服务核验，不接受调用者自填用户名代替登录，不建立第二份个人权限名单。普通全局用户分析查看权限保留非私有汇总合同：`data` 为空；原有 private 权限才可返回逐单记录和按邮箱检索。站点、游戏必须属于现役已接入配置，源 worker 当前固定站点 266；不能据资源访问权推定任意站点访问权。

日期参数是 `start` 和排他上界 `end_exclusive`，采用 Asia/Shanghai 自然日。每次请求 1–28 天；开始日不得早于执行当天减 365 天，截止日不得晚于当天次日。执行前再次验证日期和权限，跨午夜排队不延用旧边界。更长业务时间范围分成相邻的最多 28 天窗口。

## 分页与消费

GET 参数为 `site_id`、`game_id`、`start`、`end_exclusive`，以及可选 `cursor`。每页最多 **20 条**；返回 `next_cursor` 时，保持同一站点、游戏、日期和授权身份继续查询。游标与当前权限、字段和页大小绑定，重启服务或改权后可能失效；不要改造游标，也不要把它交给其他人。单个 source 窗口有 100,000 页保护上限；遇 `page_limit_reached` 必须报告限制，不能当取齐。

源单次响应最多 256 KiB、执行硬时限 10 秒，沿用现有 Admin 池和每宿主进程一个在途实时查询名额，忙时立即拒绝，不无限排队。不应并行发起一批分页请求。曾实测 50 条超出字节上限，因此当前采用 20 条；20 条也不保证每个响应永远在上限内。

`source/live_order_consumer.py` 的 `iter_pages(fetch, ..., max_pages=..., resume_cursor=..., customer_email=...)` 可按 28 天分段逐页消费。调用者提供已有授权传输 `fetch(query)`，遇非成功 HTTP 先抛出错误；有 `customer_email` 时必须改用下述 POST，不能把整个 query 序列化为 URL。保存最后已成功返回的游标及其原窗口，可在页预算耗尽后续读；重启/撤权后须重新查询。帮助函数不会替调用者建立身份或给 Hermes 授权。

## 精确客户 POST

同一入口支持 `POST`，`Content-Type: application/json`、请求体最多 4096 字节、浏览器须同源；禁止 URL 查询串和未知字段。正文含 `site_id`、`game_id`、`start`、`end_exclusive`、`customer_email`，以及可选 `cursor`。邮箱只作固定 `email =` 条件，不接受邮箱列表、任意过滤、URL 或 SQL。后台每行邮箱必须与请求值完全一致，否则拒绝整页。

合成示例（在已登录 FS 的同源页面中调用，不复制 Cookie，不输出结果正文）：

```javascript
const response = await fetch('/dashboard/users/live-orders.json', {
  method: 'POST', credentials: 'same-origin',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({site_id: '266', game_id: '1327',
    start: '2026-10-01', end_exclusive: '2026-10-29',
    customer_email: 'fixture@example.test'})
});
const page = await response.json();
// 只把状态、条数和是否有下一页用于操作反馈；不要记录邮箱、订单正文或游标。
console.log(response.status, page.status, page.observed_page_rows,
            Boolean(page.next_cursor));
```

有 private 权限的逐单字段为 `order_id`、`paid_at`、`status`、`pay_status`、`customer_email`；邮箱可能为空，不能把邮箱视为已证明的跨站/跨账号统一身份。付款状态是源原值，仍须遵循既有退款和无效状态口径，不能仅凭存在订单就认定成功购买。

FS 入口通过 POST 请求体传邮箱；上游 Admin 沿用原有固定 GET 协议。本机代理已核代码只记录不含查询参数的路径；上游自有日志策略未核实，不承诺端到端零日志。这不是向新第三方传送数据。

## 完成语义和错误

响应为 HTTP206、`status: partial`、`complete: false`、`semantics: live_non_snapshot`。`next_cursor: null` 只表示观测到分页末尾（同时检查 limitation），不证明稳定快照、全历史完整或客户终生首次购买。源端边翻页边变化时，即使总数不变也可能漏项。空读、缺缓存、源失败必须区分；不能用“这段时间没找到”推断从未购买。

- 401：会话缺失/失效；403：全局/private 权限或同源检查拒绝。不能切换固定管理员身份绕过。
- 409 `source_changed_restart_required`：数量、空续页、短页、超额末页或相邻页重叠等变化被发现，停止本轮并重新查询。
- 422 `invalid_live_query`：日期、范围、字段或游标无效；413/415：请求体大小或类型不合规。
- 429 `source_busy`：按 `retryAfter` 退避，不并发轰炸。
- 503：保留具体 `source_response_too_large`、`source_filter_mismatch`、`source_timeout`、`source_auth`、`source_rate_limited`、`live_source_unavailable` 等错误；报未取得完整结果，不能当零值或完成。

## 上线证据与待验边界

本次只发布 8 个必要目标。发布后 8/8 文件、743/743 保护项匹配；查询服务健康 HTTP200，定时任务恢复，发布锁释放，窗口已回交。TLS 实测无会话和伪造用户名头均401。用户在自己的已登录 Chrome 中报告首次返回20条、`partial`、`complete:false`、有游标；该报告不包含独立核实的 HTTP 状态码。真实第二页、客户 POST 正反例、普通/private 多角色及完整日期/预算边界仍待部署后只读验收；不得声称已全部通过。

Hermes 尚未接可信身份：`hermes-server-unify-20261022/fs_readonly/__init__.py` 固定 `OWNER='wulv'` 且注册处理丢弃 `**context`；会话 HTTP 层已有真实 actor，但下游工具还缺可核验的 run-bound actor/session 传递。接口负责人需提供该绑定并复用 `user_runtime.authorize`，不能把任意本机进程或自填身份头当可信。不要改动正在施工的 T3 技能来伪装已接线。

历史测试记录清理交接见 [TEST-DIRTY-HANDOFF.md](TEST-DIRTY-HANDOFF.md)。本次数据调用文档不代表整个04治理栈上线，也不代表旧备份已清理。
