# 订单用户邮箱导出｜现行调用与范围

版本 `order-email-all-games-20261118`。订单邮箱筛选已于 2026-11-12 在 FS 页面及其 API 恢复，逐游戏区服修正发布为 `nav-20261112T092200Z`。「全部游戏」由 PR #1229 修复，页面及 API 发布为 `nav-20261118T075009Z`。历史记录见[订单用户邮箱筛选导出](../docs/planning/order-email-export-20261111.md)。

## 业务口径

- FS数据分析工具按真实站点、多个游戏、日期及其余可用字段查询用户订单邮箱；游戏框支持名称/ID搜索并多选，不是固定FC目录。
- 「全部游戏」是 Admin 原生 `gid=0`，必须单独选择。每个日期窗口使用同一个 `gid=0` 分页读取，保留选中的站点及其他条件。选择某个具体游戏会退出「全部游戏」，其区服可单独选择。全部游戏查询省略 `aid`。
- 订单进度 `progress`、状态 `status`、产品类型 `cid`、区服 `aid` 使用 Admin 原生选项。状态随进度加载，产品类型在选择游戏后加载。每个游戏独立选择区服并使用该游戏的原生 ID，同名区服不共用 ID。未选条件不发送，Admin 默认行为的支付和完成状态范围未另行指定。操作人筛选保持移除。
- 仅提取user_email，不替换为支付邮箱；trim/casefold去重保留首次拼写，浏览器内暂存，完成全部计划后下载真XLSX文本单元格。未完成/失败不能下载部分名单。
- 日期使用 Admin 原生 `paytime`。FS 页面按每个游戏串行遍历七日窗口，API 每窗最多 28 日、每页最多 20 条，受滚动 365 日边界约束。实时分页非快照。「今年」指可访问的年初至所选截止日。
- 不发送邮件、不证明营销订阅同意、不修改订单/定价/权限/凭据。

## 调用链与工具边界

已登录FS `/dashboard/data-tools/` → page.js/data-workspace.js → order-email-panel.js → order-email-run.js → 鉴权POST `/dashboard/users/live-orders.json` → range_api.py真实actor与run_scoped → admin_order_email_export.py/admin_email_export_source.py → 专用admin_email_export_worker.py → 现有共享Admin HMAC通道 → `/admin/order.Order/index`；导出order-email-xlsx.js。

- 页面以 `kind=order_email_export_options` 读取实际站点、游戏、国家及进度。联动请求带当前 `progress` 和 `game_ids`，逐游戏区服从 `options.servers_by_game` 读取。`All Server` 按该游戏的具体 `aid` 提交，选择「不限」才省略 `aid`。目录缺项保留不可用状态，权限撤销或覆盖异常必须报错。
- 分页请求使用 `kind=order_email_export_page`、`site_id`、`game_id`、`start`、`end_exclusive` 和已选 `filters`，将 `game_id` 映射到原生 `gid`。除已选 `progress`、`status`、`cid` 和具体游戏的 `aid`，仍可传 `content`、`recommend_uid`、`discount_code`、`promotion_id`、`pid`、`country`。
- 沿用真实登录会话/private RBAC、共享串行admission、游标与完整filter绑定、响应覆盖校验；禁止模型冒用固定wulv、把邮箱放URL/日志或导入别的Cookie。
- 通过 MCP 使用时，先以 `data-analysis-tools` 展开本人可见的目录。`orders.email_options` 读取原生筛选选项，`orders.email_page` 按当前参数定义和返回游标逐页读取订单用户邮箱。`orders.customer` 用已知的精确邮箱查该客户订单，适用于单客核对。连接器接入以其独立发布及客户端验收为准。XLSX 由 FS 页面在全部窗口遍历完成后生成。

## 真实验收及边界

2026-11-12 从已登录 FS 页面验收 MMOEXP 266、FC26（833）和 FC27（1327）、付款日期 2026-11-11。两游戏的 `All Server` 分别使用 7073 和 7645，共遍历 2 页、2 个窗口，XLSX 独立读回仅有 `email` 表头。两个区服均选择不限时，共遍历 16 页、2 个窗口，XLSX 独立读回 280 个唯一非空邮箱。两个文件均无公式。默认全年全量、营销 APP 实际导入、183 完整环境及多角色实测未在该轮验收。

2026-11-18 从已登录 FS 页面验证「全部游戏」两页均返回 HTTP 206，每页 20 笔。另用 2026-11-17 付款日和 Singapore 国家条件跑完一页 3 笔订单，页面启用 Excel 下载。该轮点击了下载，未取得 XLSX 文件独立读回。

## 发布与知识使用

FS 页面发布及回滚沿[原受限发布入口](../releases/fs-dashboard/order-email-export-20261111/README.md)，按实际清单核对目标哈希、保护文件、服务和真实查询结果。知识发布沿[统一知识收尾入口](../docs/planning/knowledge-layering-20261023/CLOSEOUT.md)。
