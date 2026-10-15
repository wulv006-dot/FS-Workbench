# 工具合同最小修复候选

状态：仅本地候选；未创建Git提交/PR、未部署、未重跑模型或改写报告。2026-10-15从活动 `/opt/fs-hermes-fc/` 只读下载 `proxy_gateway.py`、`research.py`，baseline/test_gateway.py由母任务从最终main取回。精确映射和SHA见 `source-map.json`。

## 两类400分别判定

本次唯一任务f8a98aa822c7a66216dfbefd2647d5b5、原生会话fc_e02d4b6e8de9539ddaa96fe377a44ced6ab3711ed2347e8319df0e53310f0777，只读过滤其messages中所需工具请求/响应。未读取私人reasoning或凭据。

### calculator：本任务参数错误，合法计算器可用

原生messages 903的4次、908的2次 `mcp__fcro__fc_calculate` 全部 `values` 非空且 `assumptions` 为空或长度不匹配；`research.py:234` 原有合同要求values/value_paths/assumptions等长。证据绑定值需要对应空字符串标签，例如两个值配 `["", ""]`，不是整个空数组 `[]`。单值difference/ratio探针本来也不满足运算基数，其中一次路径还缺前导 `/`；平台差值sum请求也将差值绑定到原始总值，不能通过绑定校验。

采用活动代码、冻结成品证据、`persist=None`、禁写pyc的纯内存复验：

- 原AOV请求 assumptions=[] → `ValueError calculation_bindings`。
- 仅改为 `['','']`，两路径 `/data/total/revenue_usd` 与 `/data/total/orders` → `ratio=65.93`、`basis=evidence_bound_calculation`。
- 合法difference以 `[previous,target]` 输入 → `delta=-854.81/relative_change_pct=-3.07`。原计算器的difference方向是第二值减第一值。

因此不修改计算实现、不放宽证据绑定或假设保护。当前schema description已要求非假设值空标签，本轮不为补说明额外增加research发布目标；可将上述真实错误纳入下一次方法评测。

### bucket：发布schema与活动执行器不一致

原生message861/872/889分别发schema合法的 `dimension=bucket`（target/previous/target），对应400。`proxy_gateway.py:50` 宣告platform/product/bucket，但 `research.py:180` 将dimension直接映射至group_by；`DIMENSIONS` 不包含bucket，`:260` 抛 `group_fields`。纯内存复验相同合法请求确定复现该错误。

最小修复仅将候选 `proxy_gateway.py` 的枚举改为 `['platform','product']`。未增加未知分桶行为，未放宽research白名单。对外工具名、window、snapshot及全部权限/模型/账本合同保持。

## 同类调用者盘点

- 当前业务入口 `fs_evidence.py:11/217` 创建ResearchBook，因此以上为活动故障路径。
- `proxy_gateway.schemas()` 为实际模型工具schema来源；本轮修复唯一错误承诺。
- `pilot.py:241/293`、`source_projection.py:37` 中bucket支持属于旧冻结窗口/ToolBook对象，保留历史兼容与原证据，不机械删除。
- 活动操作SKILL.md和knowledge-derived.md未发现其他bucket承诺。项目FC明细模块有自身合法金额桶合同，与此自主调查group_by合同不同，不扩改其他模块。

## 用例与交付

`candidate/test_gateway.py` 在原 `if __name__=='__main__': unittest.main()` 前追加两例，原测试字节和main保持：

1. 每个发布breakdown枚举在target/previous窗口真实走ResearchBook，断言其group_by合法；bucket继续被原护栏拒绝。
2. 合法证据路径、同长空假设标签得到Decimal计算；空assumptions、值与证据不符、无证据路径且无明确假设均拒绝。

Windows本地新2例通过，整份test_gateway共39/39通过。依赖复用 `_ci_probe_grid20261015/r2/releases/fs-dashboard/hermes-fc-pilot-20261013`；candidate proxy/test优先，research使用本轮下载活动基线。正式Linux CI由母任务按现有test_gateway入口运行，不新增CI入口。

本地复跑：把candidate、baseline、既有Hermes依赖目录按此顺序加入PYTHONPATH，设置PYTHONDONTWRITEBYTECODE=1，运行 `python -m unittest test_gateway -q`。

规范库路径为 `releases/fs-dashboard/hermes-fc-pilot-20261013/{proxy_gateway.py,test_gateway.py}`。发布仍沿既有HERMES_UPDATE_SCOPE五目标，只改变proxy文件字节；生产目标 `/opt/fs-hermes-fc/proxy_gateway.py`，活动调用链为现有range/FS Hermes集成。父任务负责正式PR/CI、现场CAS、既有发布器与服务重载证据；本候选不自发发布或启动新模型验收。

collector_busy/not_sent保留原正常并发语义，不将它列为本修复故障或强行重试。
