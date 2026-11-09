# 未入当前源码树的现役读取面

2026-11-09，经原187 SSH通道，只读核对监听进程、工作目录、对应源文件AST与GET函数；未执行采集或业务写入。这里登记现场版本与合同，不用相近日期的仓库快照替代。

| 模块 | 现役源 | SHA256 | 读合同 |
|---|---|---|---|
| ops | `/opt/fc27-ops/ops_api.py` | `8b2ca1b97274dbc480da5afe8e2d2c15dd4cd6c16205e2935b1986d2630f8ebf` | 8899；GET `/health`需原网关`X-Fc27-User`，返回status和已存worker.json；GET `/jobs/<32位小写hex>`只读取对应job JSON，缺失404；POST `/collect`不接入只读工具 |
| gallery | `/opt/fc27-gallery/api.py` | `7be950e3016e5324429381bdb5cf64119ab5ea47b5f074636742e4edd048b031` | 8902；原网关`X-Authenticated-User`；GET `/api/state`返回config/latest、按created_at降序30个jobs（去settings）、blocked/writer/server_time/schedule；须继续核config/latest字段再注册 |
| sales | `/opt/sales-dashboard/api.py` | `b88c961e1f40921acf698825554d5123963c9e943c77a2aa26ba3baba5a04039` | 8905；GET `/status`返回running/phase/detail/elapsed/generated_at/orders/log_tail；原网关保留权限。log_tail和自由文本detail需核敏感边界，静态dashboard.json是另一数据面 |
| evolutions | `/opt/fc27-evolutions/source/evolutions.py` | `02931d6dbd00a7ce7c6dcf349f77999d6257111f444a8075a8433ae6ee0d14cd` | 8914；GET `BASE + /api/state`要求原`X-Evo-User`；state深拷贝已存data，基于snapshot本地调用plan产生rows，标stale/version/writable，不调用采集或apply。BASE及plan/config字段待核后注册 |

连接器仍经原HTTPS网关发真实FS Cookie，以上用户头由网关生成，模型和连接器均不能自填这些头。当前公开路径以 `.agent_runtime/connector/host_routes_current.json` 的本轮脱敏网关清单交叉确认。发布前须将必要原源码按项目来源规则纳入维护，本文不冒充四个服务已完成源码同步或连接器真实取数。

进化商品补核：`BASE='/dashboard/fc27-evolutions'`。`plan(models, products, rates, config)`只遍历模型/商品并调用number/target计算，不取网络或写入。每条rows字段为model_id/product_id/cid/title/platform/coins/model_coins/premium/rate/current/enabled/error/fixed/target。可先固定投影`rows/version/stale/writable`接入状态读取；原state其余config/snapshot/job/history/blocked仍列部分覆盖，不据此输出未核日志或任务对象。sales状态先固定投影running/elapsed/generated_at/orders，phase/detail/log_tail待自由文本边界核实。

部门手册补核：现役`location /docs/`使用`alias /var/www/docs/`、`index index.html`和原`auth_request /__auth_verify`。该目录本轮清单仅1个`index.html`，没有其他类型文件或JSON manifest。连接器可直接沿原HTTPS网关读取固定`/docs/`，将HTML正文按块提取并复用原文档导出的脱敏器；无需新建任意文件目录API或发布快照。

知识补核：`/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json`存在，SHA256 `678444f63de1d508eef3ea87a21b5f714a60493b2303a7e469f5b8c25c2f668c`；原task_routes启用，FS/data路由1条，绑定`knowledge-releases/fc-reporting-knowledge-20261105-fc888038/index.json`。未输出或改变路由owner。连接器只按当前真实subject匹配原路由；无匹配不能冒用已有owner。此检查不代表所有成员已有同样知识授权。

## 补充核验与候选接线（2026-11-09）

- Gallery：继续核对storage和计算字段后，固定投影config业务设置、latest报价/目标/计划、最近30条任务及schedule；helper为`fs_mcp_connector/gallery.py`。原storage SHA256 `b9a4d916d9c2a5ab7da6bd5bf586c9eadc93ecb3ee475960c44b082a76b6dec5`。GET不启动采集或调度。
- Odds：原受保护静态`/s/wulv/fc-odds/`映射`/var/www/sites/wulv/fc-odds/index.html`，6573字节，SHA256 `e0cbd89b359e69431192aabb7d9adcf3512b7688a6722b95252c8f5163175f1d`；无脚本/XHR，仅历史FC26参考。正文表格读取不能标为当前FC27数据。
- Accounts：真实路由是`/__auth/access/api/overview`及`audit`，原IAM `/opt/fs-access-policy/iam_console.py` SHA256 `3e06442f11f59b88653ef033bfa2ad1ac3c22e752165dc87cb505aaa15bd4689`。旧`/__auth/iam`地址会重定向，不用作数据路由。保留原admin/manage检查，固定投影成员、角色规则、目录及审计；本人bootstrap创建会话并携带CSRF，未直接注册。
- Sales：实际文件`/var/www/sales/data/dashboard.json`，通过受原auth_request保护的`/sales/data/dashboard.json`读取。现场文件4278040字节，字段仅核结构，不导出业务值。顶层meta、promoters、owners、codes、orders；新增`sales.snapshot`按数据集和最多100条本地分页，续页要求同一文件SHA256，变化返回409要求重新查询。上游响应限16MiB对应当前4.08MiB载荷，超限明确失败。金额不重算，保留USD/CNY原字段及原元数据；状态接口与快照更新时间独立。

这些是部署源/路由/结构核对和候选实现，未代表连接器已发布或真实成员查询已通过。
