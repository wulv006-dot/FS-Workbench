# 订单用户邮箱导出｜现行调用与范围

版本：order-email-defaults-20261111；用户2026-11-11 19:31决定，19:51授权同步知识。运行源码158ddab93103695ef13917bbd5368bbbe5c7b179（PR999），生产nav-20261111T113950Z；真实验收记录见docs/planning/order-email-export-20261111.md。未来使用先核实际版本，不重放旧清单。

## 业务口径

- FS数据分析工具按真实站点、多个游戏、日期及其余可用字段查询用户订单邮箱；游戏框支持名称/ID搜索并多选，不是固定FC目录。
- 订单进度progress、订单状态status、产品类型cid、区服aid固定置灰、空值；本面板不请求四目录、不提交四条件，使用Admin接口默认行为，绝不称为固定已支付/已完成或已证明的全部状态。操作人筛选已移除。不再推进补权。
- 仅提取user_email，不替换为支付邮箱；trim/casefold去重保留首次拼写，浏览器内暂存，完成全部计划后下载真XLSX文本单元格。未完成/失败不能下载部分名单。
- 日期标签沿Admin原生paytime，不猜create_time；最多28日窗口、每页20条、滚动近365日来源边界。按每个游戏串行遍历窗口与游标，实时非快照；“今年”是可访问年初至所选截止日，不含未来或终生名单。
- 不发送邮件、不证明营销订阅同意、不修改订单/定价/权限/凭据。

## 调用链与工具边界

已登录FS `/dashboard/data-tools/` → page.js/data-workspace.js → order-email-panel.js → order-email-run.js → 鉴权POST `/dashboard/users/live-orders.json` → range_api.py真实actor与run_scoped → admin_order_email_export.py/admin_email_export_source.py → 专用admin_email_export_worker.py → 现有共享Admin HMAC通道 → `/admin/order.Order/index`；导出order-email-xlsx.js。

- 目录请求body仅kind=order_email_export_options，读取真实sites/games/countries；options中progress/status/cid/aid为空并标记不可用，不补造枚举。站点/游戏/国家缺失、权限撤销、覆盖异常必须报错。
- 页面请求kind=order_email_export_page，site_id、game_id、start、end_exclusive及可用filters。前端game_ids只是编排；逐游戏game_id映射原生gid，不造IN协议。保留content、recommend_uid、discount_code、promotion_id、pid、country实际字段及运算符，省略progress/status/cid/aid与已移除操作人。
- 沿用真实登录会话/private RBAC、共享串行admission、游标与完整filter绑定、响应覆盖校验；禁止模型冒用固定wulv、把邮箱放URL/日志或导入别的Cookie。
- 这是FS页面已部署的专用链路，不自动等于Hermes/MCP连接器已暴露新operation。调用连接器先读取其现行目录/schema与方法；没有注册则明确未提供，不猜operation或用普通live-orders的site266限制替代专用多站点源。

## 真实验收及边界

默认条件MMOEXP266、FC26(833)+FC27(1327)：2026-11-10读16页/2窗口，XLSX282唯一邮箱；2026-10-31至11-01读40页/2窗口，XLSX725唯一邮箱，均独立读回非空文本且0公式。数值仅当次验收，不是今天固定统计。旧版年度399为旧progress1/status11结果，禁止用于当前默认口径。默认全年全量、营销APP实际导入、多角色实际撤权及183完整环境未实测。

## 发布与知识使用

原十一目标publisher、固定原writer、最新现场CAS、manifest SHA、锁/fence/intent/备份/UNKNOWN原操作对账不变；精确main CI和Git字节组装后plan/inspect/apply，读回所有目标及保护哈希/服务后真实入口查询下载。文档同步不重启业务，不重放历史manifest。部署方法详releases/fs-dashboard/order-email-export-20261111/README.md。历史方案仅在Git审计中查询，不恢复为现行上下文。
