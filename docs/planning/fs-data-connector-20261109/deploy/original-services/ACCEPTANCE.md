# 原服务增量独立验收

2026-11-09。范围为conversation文件/材料元数据纯读、tracking存储态纯读及用户撤销身份禁令后的原消费链；不是FS全量数据已全部覆盖的声明。

## 实际发布

- 来源提交：`cb87b4901a81ffd313e06e4882a3b33918519ea2`。
- Stage：`/opt/fs-release-stage/fs-connector-original-readonly-v2-20261109T051410Z`。
- Manifest SHA256：`8a957f45238030e2d0f997f79d6e13733147880a55186b5684500390ca5d45fc`。
- Source-proof SHA256：`50691a9d2aee5b62eb144bd377a44f0d395f71aaa9065987eb6476755cf3b0ed`。
- 发布ID：`nav-20261109T051930Z`；备份`/var/backups/fs-navigation-20261006/nav-20261109T051930Z`。ID为原发布器编号，不据编号推定执行时间。
- root实际apply成功，独立读回journal为`applied-awaiting-actual-http-role-acceptance`、written_files=9；9目标SHA全部匹配manifest，48保护项全部无漂移。

root实际执行命令：

```sh
cd /opt/fs-release-stage/fs-connector-original-readonly-v2-20261109T051410Z
python3 -B release.py apply --manifest ./approved-manifest.json --approved-manifest-sha 8a957f45238030e2d0f997f79d6e13733147880a55186b5684500390ca5d45fc --release-id nav-20261109T051930Z
```

若需回退，使用原同一manifest和backup，沿原空闲保护执行；**本轮未执行回退**：

```sh
python3 -B release.py rollback --backup /var/backups/fs-navigation-20261006/nav-20261109T051930Z --approved-manifest-sha 8a957f45238030e2d0f997f79d6e13733147880a55186b5684500390ca5d45fc
```

不恢复业务数据库，不删除新增会话/任务，不恢复旧单人自动报告；超时先核原journal和实际SHA，不换发布编号重放。

## 实际消费者与重载

仅更新文件SHA不足以让常驻工具描述生效。现役`hermes_worker.py`的`make_adapter`在启动时调用`proxy_gateway.schemas()`并逐项`registry.register`；该函数内部导入`research.tool_schemas`，所以本轮在原admission/空闲/readiness保护内重载同镜像worker，再重载range。

| 服务 | 发布后PID | 实际启动时间（UTC） | 读回 |
|---|---|---|---|
| fs-hermes-fc | systemd 14591；容器14629 | 2026-11-09 05:19:04.809421 | active；镜像仍`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544` |
| fs-business-range | 14714 | 2026-11-09 05:19:08 | active |
| fc-pricing-v3 | 31326 | 2026-11-09 03:30:21 | active；早于本次发布，未重启 |
| fc27-cloud-api | 31312 | 2026-11-09 03:30:20 | active；早于本次发布，未重启 |
| fc27-cloud-worker | 31318 | 2026-11-09 03:30:20 | active；早于本次发布，未重启 |

在实际worker容器的原`/opt/hermes/.venv/bin/python`、`/opt/pilot`只读挂载环境中调用原`proxy_gateway.schemas()`，得到38个schema；客户追踪描述允许email、UID、original order numbers和stored business detail。实际加载research SHA为`a49e5c8f881ce9a94d3064cfba9487be54dc0c5ba4deefaffe8ba3076624ee2e`；该描述SHA为`45c58e52aa260b41ec22de6ae0ed80b20dedda6deed9c5079fc6f061428e3a75`。内部原Bearer授权的capabilities HTTP200，但该接口不暴露schema描述；常驻registry消费依据是新进程、已核启动注册链与实际容器schema加载结果，不伪称能力HTTP返回了描述，也没有为此发新模型请求。

FC发布后只读monitoring显示enabled=true、计划ACTIVE、waiting、pending=0、issues=[]，最近完成轮仍2026-11-09 04:39:54.759423Z、COMPLETED，下次05:36:56.589500Z（北京时间13:36:56）。原调度/API/worker启动时间保持；没有启动新轮、改价或重放对账。

## 原响应对照与实际权限验收边界

独立维护核对仅使用原Store方法及SQLite mode=ro/query_only，不构造会轮询的controller，不造用户身份头：

- 配置profile FC27、version 2、enabled=true。
- 已追踪5个，均active；订单行12；检查前后tracks/orders/scan_jobs/pool_reports计数保持。
- 候选2026-11-08为`available`且items=0，区别于缺数据或查询失败；存储态字段为stored_only=true/refreshed=false。
- 一条已有追踪详情为active、1笔订单、history_complete=true，邮箱/UID字段存在；未输出其私人值或订单正文。
- 候选和该详情的规范化原数据SHA分别为`b18e49adde248d8acaaa5264677bd286b6d5d1024cf720346ea9aefb5eef7b00`、`11206eb40dfd6a18a89257aec9862ddead17affd70f5f3d2912f869ba3fc52ed`；实际不透明对象ID及原对照证据只留忽略目录。

这属于源结果对照，不替代真实OAuth、管理员/private/owner和拒绝角色验收。真实授权查询由主代理/授权适配代理继续沿原HTTPS Cookie/网关执行，禁止填固定wulv身份头；完整结果以主LIVE-ACCEPTANCE整合为准。

## 用户授权清理的唯一旧评审

原预检被一个两天前pricing review的dispatch_unknown残留挡住。用户随后明确要求删除该唯一旧记录，停止恢复旧输出；root依照已审固定CAS脚本先备份，再仅删除原conversations 1、turns 1、events 74、native_conversation_runs 1，共77行。其他unknown、schema/index/sequence及价格账本保持。

- 原选中记录SHA：`5caddf5eeeeb327d7621cf849be97ab7e3807e6f4e265f0605b5c682ee4e671c`。
- 实际删除回执：2026-11-09 05:17:42.083843Z，`deleted_single_old_review`。
- 私有备份：`/var/backups/fs-pricing-review-delete-20261109-25e40b0a9864443f8ecf72fa65f66753/pricing-reviews.sqlite3`，SHA`ad1555156ef0622ebc40a08055d7c1fcb2b2b0e4b287806c8303b1bce11975e4`。
- 实际清理脚本SHA：`bb90a6802ef10242730e70fd33603631ffb74dfb7069967b2d97168ed0540b25`。
- 发布后旧cid/turn/events及pricing review全部dispatch_unknown计数均0；restored_output=false、model_requests=0、price_writes=0。

首次删除预检错误假设DB必须0600，被实际0644挡住，发生在备份/删除之前。补核后固定绑定现役0:0/0644单链接常规DB、两层0:0/0700私有祖先和0:9876/0750上级目录；未chmod现役数据库或降低原保护。新增测试覆盖真实边界及漂移拒绝。

## 检查范围

- 精确overlay21项本地通过：实际候选模块导入、现场Store.detail/observe等未变、原匿名计算不变、只读与admin边界、身份/完整订单保留、1000条正常23字符原单号仍保持报告聚合和原12000字符容量、原fence内worker→range重载；同时执行两份原readonly用例。
- 删除脚本5项本地通过：固定集合、CAS拒绝、其他unknown/索引/sequence保留、异常依赖/trigger拒绝、实际权限边界。SQLite持有reserved事务时由独立只读连接备份的直接检查通过。
- 187实际Python3.9先preview清理边界/CAS，再observe/prepare ready/inspect；9目标sourceCAS、48保护CAS和候选组合导入通过。其后root实际apply及独立文件/进程/状态读回通过。
- 这些现场overlay/维护脚本依赖私有原文或preview，未作为CI覆盖；没有重写或复制完整现场before进Git。本目录保留确切脚本和差异供审阅，正式业务CI记录仍见主验收。

原发布依赖helper SHA：release.py `68be4036544c412a585e5cb494fa39b92c686e65eee4827fac09e6fc6d637379`；runtime_release.py `e0b63210f255b318fc087f98328d1af8b5710c53ce8ba891a5314a815a90fb9e`；runtime_prepare.py `dd6197d806e18e2e91a53917f15a03797d0183fc801587e9b22c0e8fea2a065e`；release_navigation_base.py `1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de`；release_readiness.py `82793ff05badf6102f5cfd668fb732bc2f30c82e49ea08153d96eb903c962942`。

忽略的只读证据位于`.agent_runtime/connector/original-service-release/`：installed-readback.jsonl、worker-schemas-readback.jsonl、original-tracking-oracle.jsonl、protected-receipt-readback.jsonl、fc-current-readonly.jsonl，以及server stage的preflight日志。活跃技能旧句的原publisher新版更改由主代理另记，不据本代码包声称技能文本已发布。
