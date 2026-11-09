# WoW Forever 查询口径重试修复（2026-11-09）

## 问题与修复

经营台月累计/上周累计曾因 `admin_all_sites_contract_mismatch` 冻结为不可用；同期间后续读取恢复有效，但原 `read_query` 在第一次校验异常时立即退出。

仅修改现有共享 `read_query`：对 `source_contract_mismatch`、`admin_all_sites_contract_mismatch` 在原单查询 100 秒及全局 deadline 内重试，绝不接纳不匹配响应。永久不匹配保留原错误；401/403 和非预期异常立即失败；已取得的同期间有效部分结果仍保留。不改口径、目标、调度、权限或模型计划。

## 本地回归

`python -B -m unittest discover -s releases/fs-dashboard/management-november-20261103 -p test_november.py -v`

- 修改前：新增用例复现首次口径错误立即退出（4 failures、3 errors，包含子用例）。
- 修改后：11 tests 通过。新增用例使用真实 `project_summary`，验证两类暂态错误恢复、两类永久错误与 12/100 秒边界、401/403、非预期异常、202 恢复以及有效部分结果保留。
- 现有 `test_sandbox.cjs`、`test_home_display.cjs`、`test_target_hash.cjs` 均通过。
- 新增用例在原 `test_november` 中，复用现有 pr-fast 的 management-november 分组；Linux runner/文件锁检查由原 `check_linux.py` 执行，不以 Windows 单测冒充 Linux 验收。

## Git 与生产状态分开

此前已直接热修并重采集生产，这是未按本地→PR→CI→main→部署顺序执行的历史事实，不能声称本 PR 已先于部署或补造发布回执。本次补回正式仓库流程，PR/CI/合并及后续部署以真实结果为准。

生产下载副本还包含动态配置支持（`collect` 的 `_source`、`bindingKey`、`forecast_enabled`），其原始提交未在当前仓库历史找到。本 PR 将这些已运行行为作为独立的源码基线同步提交保留，不声称是本次新功能或已查明原作者。新增 4 项回归验证空绑定不取数、自身绑定不递归、单来源字段原样保留及绑定标识/关闭预测；同步前 1 failure、3 errors，同步后共 15 tests 通过。

2026-11-09 17:39 只读核验生产完整文件 SHA256 为 `afd1ba4d56e883917d0c17eb0cd31b2346900789b8296f42b3b545d8d7e948df`，与同步后的候选文件逐字一致。正式合并后应重新读回核验，不为制造发布动作而重复覆盖同一文件或重启服务；若现场已变化，必须重新核差异并沿既有锁/CAS 发布器处理，禁止覆盖新改动。配置服务、数据库、目标、调度、缓存及快照均不在本次发布载荷内。
