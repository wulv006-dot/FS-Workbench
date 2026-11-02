# Admin 用户订单按需查询：隔离候选

本补丁复用既有 query planner 和 range job 引擎，增加受限的 Admin 单页转换器；默认无网络、无 host 注册、无生产启用，不重采/写用户分析库。它只返回订单 ID、付款时间、状态中的明确选择字段，不返回 email 等客户字段；它不能计算完整用户生命周期、替代周批或保证任意历史重建。source cursor 是签名内部状态，外部用户分页仍使用引擎原有权限复验的 cursor。

## 输入及宿主合同

引擎计划提供唯一范围 `source=Admin`、站点、游戏、半开日期窗（最多 28 天）、白名单字段、`paid_at`、水位和内部 cursor；不接受 URL、SQL、自由过滤字段。转换器固定查询 `/admin/order.Order/index`，沿既有 `channel_source.search` 约定编码 `site_id`、`gid`、`paytime RANGE`，将右开日期转换为前一日 23:59:59；源必须实际支持这些条件并校验返回站点、游戏、日期、ID 顺序和总数。任一不匹配显式失败，不悄悄扩大范围。

宿主必须注入：(1) 来自现役身份的 `authorize(request)`，在请求前后复验并返回同一 `scope_hash/permission_epoch/policy_version`；(2) 真实可审计的 `source_proof(request)`，证明同范围的强稳定水位，在每页前后都返回相同 watermark；(3) `fetch(fixed_path,params,timeout_seconds,max_response_bytes)`，使用既有获授权会话，**在读取/解析前**强制超时和字节上限；(4) 服务器私有 cursor HMAC key。每项必须来自实际宿主，不得用固定 True、硬编码 epoch 或从模型取得的值代替。原 Admin 接口是否能提供满足此条件的稳定快照目前未知；不能证明时适配器返回 `source_unstable`，不承诺完整结果。

每页大小 1–1000、页数 1–100、单响应最多 10 MB、超时最多 30 秒；具体值必须由现役能力策略和更小 budget 设置，引擎另执行总请求、总行、总字节以及权限/取消检查。发生 401/403、429、timeout、结构变化、scope 不匹配、权限或水位变化时失败；只有总数为 0 的可信完整页才标 confirmed_empty。没有稳定水位的实时大结果若业务接受 partial，需要单独设计标记与预算，不能伪装完整缓存。

## 接线边界与验证

原 A 管理 `range_api.py`、真实身份与 route，Hermes 注册文件由对应 owner 协作；此分支未改共享 owner 文件，也未建立真实 grant、source proof 或 HTTP bounded transport。可审最小接线：现有身份取真实 scope/epoch → date policy 和 planner → 现有 Engine → 用现有 session 实现上述固定源 transport/proof → 状态/分页每次复验授权；未满足任一前提保持 disabled。不得把此候选或 fixture 成功称为生产能力。

测试使用伪造分页响应，不连接 source，也不保存客户数据；覆盖范围下推、字段投影、授权撤回、分页/游标绑定、预算、源错误、源水位以及与现有 planner/Engine 的合成串接。生产侧仍需在授权的最小时间/站点范围验证源字段、过滤语义、水位、网络时限和实际权限。删除旧备份是独立已授权事项，不以本适配器上线为门槛。
