# 注册成员登录与权限衔接修复

liule 已被授予 PlatformAdmin，经营管理台数据接口却只读取旧门户 Cookie，返回401。公共 IAM 会话读取现在使用现有注册适配器的固定身份自举校验；业务接口继续检查实时RBAC与CSRF，不信任客户端身份头，也不在适配器拒绝后回退旧Cookie。

另外修复注册超级管理员被降为readonly的投影；任务台与旧FC身份消费者仅在实时IAM仍确认为super时接受注册admin。模块运营角色不会因此提升为平台管理员。任务台session由tasks/green_plan资源投影编辑权限，避免查询不存在的虚拟task_session资源。

## 活动来源与范围

- `opt/fs-access-policy/iam_console.py` → `/opt/fs-access-policy/iam_console.py`。
- 本目录`candidate/module_permissions.py`、`candidate/consumer_seams.py` → `/opt/auth-portal/registration-runtime/20261007-ca6258ad/`同名文件。consumer_seams原始活动来源是fs-revision-20261015/accounts/candidate/runtime，原部署SHA为d82a0db5301888a073003d6904c3e4a0f779976a4c8a396e30628b75458b72d8。
- `/var/www/dashboard/fs-home/{navigation,module-registry}.json` 原模式0600导致Nginx读取403；发布时仅恢复0644，内容不变。公共静态目录扫描未发现其他应公开静态文件有同类模式；私有事务锁保持0600。
- 不改变账号、角色绑定、密码、数据库、业务目标、采集/改价计划。只重启auth-portal、mmoexp-taskboard、fc27-gate三个身份消费者；不重启FC写入器、采集器或共享业务会话。

## 验证与限制

- Windows与183隔离Linux各68项IAM Python回归通过；离线密码表单12例及注册UI模拟流程通过。
- 生产只读适配器核对14注册账号×39入口=546决策，286允许、260拒绝，与现行策略一致。liule真实账号状态与授权主体经进程内会话测试接缝读取经营管理台配置200，未签发其凭据、未创建生产会话。
- 原生管理员正式HTTPS：首页、管理台数据、两份导航、IAM session、任务台session、机器人overview全部200；匿名管理台及无效注册会话401。现行策略文件SHA未变。
- 未操作liule浏览器，未执行真实业务写入。Computer Use因无法可靠确认当前浏览器网址停止，不能宣称用户客户端画面已验。
- Windows完整pr-fast的IAM与ops合同部分通过，MLB既有符号链接用例因Windows缺少创建链接权限失败；PR必须以Linux CI实际结果为准，未关闭或跳过该用例。

## 发布与回退

沿现有IAM publisher的共享锁、逐文件CAS、持久备份和回退；适配入口`release_session_fix.py`，不部署第二套publisher。

1. 初批：stage `/opt/fs-release-stage/registered-session-fix-20261106`，备份 `/var/backups/fs-navigation-20261006/nav-20261106T065300Z`，manifest SHA `421645b6625076e9de2309296911b8eedb35695bb00bb4ffc5532f1036083848`。
2. 任务台session增量及源码LF统一：stage `/opt/fs-release-stage/registered-session-fix-20261106-v2`，备份 `/var/backups/fs-navigation-20261006/nav-20261106T065800Z`，manifest SHA `d993cba3d54c7540312e365bf421b1276de0b24d32b861d3cc1c65f7bd6769ec`。

回退必须v2→v1逆序，在各stage执行：`/opt/python39/bin/python3 -B release_session_fix.py rollback <对应manifest SHA> <对应备份目录>`。恢复本批代码及文件模式，保留所有数据库、会话、角色策略、审计和业务数据。若目标出现后续编辑，CAS拒绝，应定向协调，不覆盖新版本。

生产验收脚本`verify_session_fix.py`只读；输出`verification-session-live.json`保留服务器和本地档案，不写Git。其注册账号核验使用清楚标记的进程内诊断接缝，不冒充真实浏览器登录验收。
