# 主线集成交付

本目录为隔离候选和只读证据；未做 Git 写、部署、账号/密码/权限修改、任务执行、服务器清理或 timer 启用。主线负责最终组合树、私库 CI、受控发布与根 HANDOFF。

| 产物 | 精确 SHA-256 | 状态 |
| --- | --- | --- |
| 原活动 publisher | `e0c8db6ad0e4b732593f72494980e62f55adee88c8ae5c446a9f76c8c834dc95` | 派生基线，未编辑 |
| `../deploy/release_navigation.py` | `19ce1c36b277e55bbd81ceb89e4187ed894c9dc5b42a65461370076d06aebee0` | 账号9目标扩展 |
| `release_navigation.py` | `fe8f5fa6583991c2eca8a2611f95c809d7c45f7a3c487e05ea5bd424f7d5d03e` | 在账号版本上追加 AI20目标，已冻结 |
| `ai-publisher.patch` | `b6e18b8518667f96244ac658a70dbec330d4c6f0ce4314dfc86125b235ddd87c` | 相对账号版本；不能直接套到原活动版本 |

账号候选的9项活动载荷及16项依赖身份在 `../SOURCE-MAP.json`。账号状态延迟到首次合法保存才升为schema5；安装代码不改账号。原四管理员、审批、默认模块和历史源均保留。密码和权限保存使用当前管理员密码复核、CSRF/Origin、opaque CAS、追加审计及全会话撤销；schema5后拒绝pre5代码回退，不恢复数据库或checkpoint撤销已发生的保存。

AI scope 是 `fs-revision-ai-20261015`，20目标中7项新文件。包括 range8、boss4、Hermes4、知识2、cleanup单位2；明确为 `fs_cleanup.py`，没有独立 `cache_guard.py`。完整映射由 `AI_REVISION_TARGETS` 与主线最终manifest共同冻结。知识原文/价格/目标值和其他scope业务未修改。

所有旧共享锁、collector锁、provider ledger锁、Hermes admission fence、锁内CAS及原子读回继续使用。旧advisor/daily pending/running和Hermes未知/待核对任务阻止替换；原操作ID及失败证据不删除、不重标成功。boss服务允许inactive或failed且PID=0，cleanup仍须严格inactive且未启用；timer不要求不存在的MainPID。

发布只作daemon-reload及受fence保护的range重启，不重启Hermes worker、不启动cleanup service、不enable timer。cleanup service必须精确带 `--apply`，timer必须精确 `OnCalendar=*-*-* 06:30:00 Asia/Shanghai`、`Persistent=false`；这一阶段两单位保持inactive。部署后精确SHA读回、无apply手动dryrun、Linux17项0skip及writer新PID通过后，主线才单独启用timer，首次按下一06:30执行。dryrun不表示已清理。

`approved_daily_group`原例外未扩大。现场 `/var/lib/fs-hermes-fc` 为root:9876/0750，但不是本scope20目标的祖先；真实目标祖先包括 `/opt/fs-hermes-fc` 均root:root且无group/world写，相关FD锁保护也与现场相容。证据 `live-nightly-metadata.json`。

本机账号20、localhost HTTP3、账号publisher6均通过；Chrome26项断言全网络拦截且仅合成账号。AIpublisher10项通过，覆盖failed+PID0允许、failed+正PID拒绝、cleanup严格inactive、精确时区、pending/unknown保护及仅range重启。见 `../verification.json` 与 `test_ai_publisher.py`。这些不替代新候选Linux或正式入口验收。

最小Linux CI无需pip：Python3.9+、标准库、支持partial index及table_xinfo/index_xinfo的现代SQLite、普通临时目录权限即可运行以下39项账号/publisher检查，无需root、生产文件或模型密钥。不能只检查partial index而忽略既有schema verifier使用的扩展结构PRAGMA。新私库包当前主线实际位置为 `releases/fs-dashboard/fs-revision-20261015/accounts/`（独立账号包名称是规划映射，执行以主线最终inventory为准）。

```sh
python3 -c "import sqlite3; d=sqlite3.connect(':memory:'); d.executescript('CREATE TABLE t(v); CREATE UNIQUE INDEX p ON t(v) WHERE v IS NOT NULL;'); assert len(d.execute('PRAGMA table_xinfo(t)').fetchone())==7; assert len(d.execute('PRAGMA index_xinfo(p)').fetchone())==6"
python3 -B releases/fs-dashboard/fs-revision-20261015/accounts/tests/run_ci.py
python3 -B releases/fs-dashboard/fs-revision-20261015/accounts/integration/test_ai_publisher.py
```

最终组合publisher必须也被主线测试加载，不能只测本目录冻结副本后忽略UI合并的结果。UI脚本另需Playwright和Chrome；不作为上述标准库CI依赖。服务器现有Python3.9需沿已安装SQLite3.53.4加载方式运行认证publisher，不用旧系统SQLite解析注册库部分索引；独立LinuxCI可直接使用其现代系统SQLite。

主线包装脚本已将AI retirement的boss_insights改为包内baseline、projection脱敏fixture改为包内fixtures、旧业务回归源改为私库原release路径；已只读确认当前private-candidate相应内容。包装仍需按主线最后冻结重新生成，不能引用本轮审计SHA去证明后续变化的组合包。

尚未验证：新候选Linux完整执行、多进程POSIX接线、真实角色入口、新密码/权限生产生命周期、自然夜间周期、正式provider输出及真实清理。既有Linux依赖import和密钥权限链仅证明运行环境可接线，没有读取密钥正文或发起provider调用。
