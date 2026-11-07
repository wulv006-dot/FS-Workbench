# ArabUT PC 采集角色增量发布候选

状态：仅准备；本轮角色 updater、来源配置及路由切换未执行。主模块25目标另沿原 fc_v3_release_adapter 的 bidirectional scope 发布。

## 固定输入与最小范围

复用原 `E:/WorkBuddy/fc-dualnode-20261102/update-collection-route.py` 的完整包验证、旧目录逐文件CAS、只读preview、原子目录交换、失败回退及角色健康读回；本轮入口为 `releases/fc-coins/fc-pricing-v3-20261026/deploy/update_collection_bidirectional.py`。不采用初装器覆盖现役，不创建新的角色、权限、凭据、端口或服务。

| 角色 | 旧包／SHA256 | 新包／SHA256 | 精确变化 |
|---|---|---|---|
| 183 node | node-3f4aa53f.zip / 55eeff178d37e4747c1fe5b4f3d49b9a258b4d5cf7eeb75a6cbf6493cba5b14d | node-bidirectional-20261107.zip / 2360f21883ae0a823810b44255ca7e31808c7d942bdaff8c22c0ff9f09f9dabd | contracts/public_sources/adapters/worker.py 与 manifest |
| 187 control | control-6d395242.zip / 53e1e8fa7719d57e35a7dc33a200948827ef06e8479e70922379479834f913ec | control-bidirectional-20261107.zip / 1236c157e31415ac60b404e980c03adf631bbdc5bb8fa1e1e4236502c2f0928a | node同四个模块，另 client.py 与 manifest |

旧 node manifest digest：`0665b89d7d6e074f1a06c10672c1f2f4c5d55ea86bea6b214bb1e434a0fc5a7e`。新 node manifest digest：`49ac963bb2744c3f54ed0383d6570781ef709c4eb9374a4e850e3cab77dd5085`。这是代码工件校验值，不是凭据。control 更新器仅在原 access 配置中核旧值并原子替换这一字段，其他内容保留。

两套新包位于本机任务 `.agent_runtime/t1-collection/`。构建器ZIP时间戳可能变化；本清单pin上述已生成工件，不重新构建后沿用旧包hash。

## 串行衔接步骤（尚未执行）

1. 沿原发布锁和 FC 唯一 writer 的空闲检查择定窗口。原业务 cycle 未在执行、原采集 LEASED/未完成 permit 已结束（含 timeout+clock margin），183原 spool 已空，才切；UNKNOWN 沿原ID先核，不清任务或账本。保护原RPG、共享会话和每60分钟节拍。
2. 原187路由仍为consume/gen12、来源ArabUT仍为consume/gen12/v2，window=60、max_requests=6、concurrency=1。只读复核该前提及所有包/CAS。通过原 `atomic` 将原routing暂记off/gen12封住新请求，保留同一文件、同一来源和已有全部记录；这只是本次受控串行切换窗口，不停用计划或修改调度。
3. 两端独立stage为 `/var/tmp/fs-fc-bidirectional-20261107`，放准确旧包、新包及本轮updater。分别运行 updater 的默认preview，无 `--apply` 时不会建candidate、写receipt、改access或重启服务。preview所需完整旧包与现役逐文件一致，精确变化仅上表。
4. 依同一已核输入执行node/control更新；node仅沿原流程重启新增FC采集服务并读回uid999、node manifest digest。control不重启业务，原子更新原access的worker_digest。备份与receipt分别为角色根目录的 `code-before-bidirectional-20261107`、`bidirectional-update-20261107.json`。任何失败按原交换路径回退代码和原access，保留failed目录、原spool、原账本和回执。
5. 原publisher发布主模块后，只读确认两个187目录均能从 `/opt/fs-fc-control/code` 导入v3，并读回183健康为同一v3和新digest。两套路径已在本轮发布前以生产Python3.9实查可导入现役v2；不能据此宣称v3已部署。
6. 在原Coordinator上读取ArabUT当前来源，去掉派生的 `blocked/cooldown_until` 后保留全部其余字段，仅更新 `generation=13`、`adapter_version='arab-public-quote-collection-v3'`、`policy_version='arab-production-pc-v3'`、`max_requests=8`、`mode='consume'`，调用原 `Coordinator.configure_source('ArabUT', policy)`。该方法保留原拒绝和冷却，不删除/重建数据库、jobs、permits、观察回执或run-route pin。双quote请求预算为单节点最多4GET、两attempt最多8GET；原60秒来源窗口、并发1、90秒lease及20秒request timeout保持。
7. 核回同一来源gen13及所有不变字段，确认blocked未被清零、cooldown未缩短，才沿原atomic最后写routing `{schema_version:1,remote_result_mode:'consume',assignment_generation:13}` 并读回。若调用结果未知，先读原状态，不另增代或盲重放。原gen12/v2旧任务保持历史，不用新job重跑原parent。
8. 从原真实入口确认PS/XBOX Normal与独立PC standard报价、USD/SAR及null原delivery完整，原plan/operation回执与Admin核价仍按原规则，继续自然周期验收。这里的代码准备、隔离测试和只读公网报价均不等于上述上线或自然周期完成。

## 验证

- updater三项直接测试：固定旧包/当前manifest、精确角色边界、preview无写入/无命令、旧CAS变化与既有backup拒绝；测试不调用现场服务。
- 本机对准确旧/新工件执行read_bundle与逐文件差异核对，node四源码/control五源码加manifest完全吻合。
- 未执行生产preview/apply、source gen13切换、worker digest写入或自然周期验收。
