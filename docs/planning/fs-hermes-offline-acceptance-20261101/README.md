# FS / Hermes 独立离线验收反例

此目录只收录可复跑的合成反例与验收边界，不包含owner源码副本、客户数据、凭据、数据库、完整日志或未应用修复补丁。未修改A/B、数据实现或CI，未授权合并、生产发布和删除备份。

## 复跑

在完整本地Git checkout内，使用Python3.9+执行目录中的独立脚本。默认仓库根为本文件上三级目录；跨目录复跑时设置环境变量`FS_ACCEPTANCE_REPO`。脚本通过`git show 固定SHA:路径`只读源码，设置`GIT_NO_LAZY_FETCH=1`，缺历史对象直接失败，不自动联网获取。

被测源码导入前启用Python audit hook拒绝网络与子进程；源码读取所需本地Git命令发生在hook之前。只使用标准库、临时SQLite/文件与合成回调。该hook不是OS级沙箱，也不代表任意扩展都受其控制。

| 脚本 | 固定历史输入 | 期望性质与原观察 |
|---|---|---|
| probe_bound_files.py | 4e31c61（目标文件blob与首次审查587e96a4相同） | 非bool授权必须拒绝；历史代码接受1、字符串false和allowed:false对象，脚本保留退出码1，不用xfail冒充通过 |
| probe_daily_fixed_commit.py | 934f501 | 事实与dirty必须同一快照；历史代码可拼出旧10+clean，另记录源失败保旧与同事件币种冲突 |
| probe_jobs_fixed_commit.py | bf7f9ca | 请求字段完整性及cursor类型：历史缺amount仍缓存complete，cursor=0被视作首屏 |
| probe_checkpoint_generation.py | 40dbf3df | 单Engine同锁下迟到旧代不得覆盖新代；历史checkpoint从新queued退回旧cancelled |
| probe_proof_freshness.py | 0c29890b | proof有效期/撤销合同：历史格式验证忽略额外过期/撤销字段，仍给候选和恢复规划 |

后四脚本输出最小观察JSON，正常退出只代表探针运行完成，**不是被测性质通过**。源码修复状态见下表；历史反例保留固定SHA，不会因新HEAD修复就改变历史观察。需要新修复回归时由owner使用对应固定新SHA验证该性质，不能把旧探针的进程exit0列为生产绿灯。

## CI 检查工具本身

现有 `pr_fast` 将本目录映射到 `fs-hermes-offline-acceptance`，执行 `python -I -B test_probe_tools.py`。6项测试验证五脚本缺本地对象时真实失败、本地Git读取禁lazy fetch、网络及子进程守卫实际拒绝、JSON观察和非零退出状态原样保留、Python3.9语法及映射选择；既有未注册代码仍UNMAPPED，不增加豁免。

这是诊断工具行为检查，不是历史FS性质通过。测试只用空临时目录及明确合成的观察脚本，不复制或模拟修复FS源码。历史重放由操作者另行提供固定对象：现有Actions checkout虽然fetch-depth=0，但不会保证获取尚未推送或不在可达历史中的数据owner提交。CI不自动联网补对象，不把实际历史重放缺对象当通过；缺对象本身的拒绝行为可以被工具测试正确验证。沿用现有workflow的无网络执行环境，不新增workflow或安装依赖。

## 已核状态与范围

- a29050a将日事实/dirty置于同一读事务，并修复币种幂等。
- 40dbf3df补齐字段合同与游标类型检查；7661c98修复迟到generation及持久revision CAS。f630a6e上的原generation反例已独立复验为不倒退。
- 772cc6d补齐sink准备/发布回执及发布前后授权；真实sink/verifier/publisher/锁及提交后UNKNOWN对账仍需实际接线。
- 0c29890b新增总索引预算及纯dry-run，proof freshness缺口当次仍存在。后续修复等待新的固定提交验收，不能把旧结论当当前生产事实。
- BoundFiles类型差异交原A/B owner处理，本目录没有应用建议补丁。回调在生产是否可能返回非bool尚未证明，不是已证数据泄漏。

所有客户、scope、金额和文件均为synthetic。真实身份授权、水位adapter、目标Python3.9/SQLite3.7行为、维护引用图、发布与UI不由本包证明。曾有离线测试因POSIX环境缺失失败/skip，未以Windows模拟权限当生产证据。

## 对接验收

复用原owner的授权/发布/账本，不新建第二套grant或执行器。重点验收：撤权后的cache/status/续页/download先拒绝再读；query checkpoint恢复不重启cancelled AI；缺页/退款/过期证据保持partial/unknown；v2文件继续问答不混v1；artifact逐段鉴权，pin/引用不明不删。UI桌面/手机浅暗、键盘和200%缩放均待真实入口验证。

历史失败、源码修复、离线复验、生产接线分别记录。本目录没有删除、部署、PR发布或自动清理入口。
