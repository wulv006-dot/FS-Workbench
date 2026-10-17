# 隔离验证与主线交付

本机可安全重复运行，所有测试仅临时合成数据：

```powershell
python -B docs/planning/fs-revision-20261015/accounts/tests/test_accounts.py
python -B docs/planning/fs-revision-20261015/accounts/tests/test_http.py
python -B docs/planning/fs-revision-20261015/accounts/tests/test_publisher.py
python -B docs/planning/fs-revision-20261015/accounts/tests/test_ui.py
```

`prepare_candidate.py` 仅首建隔离副本，发现已有候选即拒绝，不能重跑覆盖修改。`prepare_publisher.py` 只从固定活动publisher派生补丁并复制9目标到本目录deploy，未连接服务器。

Linux QA：由主线获准私库新候选进入独立Linux环境，运行后台/真实localhost HTTP/publisher测试；设置现有Linux Python/SQLite，不向187上传旧QA包。Chrome隔离脚本可在本机运行，不能替代Linux。需另做POSIX namespace争用、真实publisher备份/失败回退/会话撤销与权限拒绝接线；只使用合成账号、临时root与临时数据库，不恢复生产数据求测试通过。

主线冻结前：核本目录9 payload、publisher.patch、当前master publisher合并组合；补当前 `/var/www/dashboard/index.html` 及受影响外部consumer/认证依赖保护SHA。`deploy/candidate-manifest.json`为false候选，缺正式保护HTML，不可直接apply。以 `SOURCE-MAP.json` 和 `baseline-map.json`选择当前活动文件，不能回放旧10/9整包。

发布前：fresh核账号源、schema、checkpoint、活动9SHA、publisher精确SHA与auth/taskboard服务；不动真实账号。代码发布只安装9目标，原锁/CAS/备份/失败恢复保留；确认服务器现有SQLite3.53.4加载方式。仅重启auth/taskboard，保留原调度、价格、采集、DB、撤销及审计。

发布后：真实已登录管理员仅读取完整7账号和新表单；匿名/伪造头/普通身份被拒绝；读回9SHA及旧数据库逻辑用户/申请/账号审计仍未变。实际密码值由管理员在网页输入，不在聊天、脚本或报告提供。用户首次合法操作再验密码旧新及会话/权限真实读回；不制造账号或重置现有密码求放行。

第一次真实保存后schema5生效，pre5代码回退拒绝；保留最新状态，采用兼容5的前向修复。生产私有DB和checkpoint备份是保全材料，不能恢复它们撤销密码/权限变更。
