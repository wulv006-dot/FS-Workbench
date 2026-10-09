# 绿茵计划 PR39 复核修复：已上线

2026-10-09 07:59:40（北京时间），按用户“线上给我部署一下啊”的明确授权，完成四项复核修复。发布只替换五个文件，认证与任务服务必要重启；备份和进展保留检查通过。

## 修复效果

- 已登记的执行人可保存本人负责任务的执行字段；仍由任务台校验成员启用状态、指派关系、字段权限、版本和来源。只对绿茵计划精确 PATCH 路由委托应用层授权，不开放其他业务写入。
- 注册只读账号的八个绿茵读取路径加入白名单，仍不可写入或访问管理接口。
- 恢复本次代码不再被无关服务 PID 或文件变化阻断；恢复保留双锁、原批准清单、目标和备份哈希、白名单及中断恢复检查，不恢复数据库。
- 管理员表单补齐“配合岗位”和“预计投入”，每项500字；执行人仍不可修改这两个结构字段。

## 验证与范围

Linux 3.9：60项身份/路由/真实任务处理器隔离组合检查、14项恢复场景通过，使用真实 POSIX 锁和目录 fsync；已有绿茵后端回归通过。本机 Chrome 9项表单/模拟 API 检查通过。合成身份与假 API 只证明对应测试范围，不代表生产真实角色验收。

生产独立读回：五个目标哈希一致、98个保护文件一致；原有全部8张业务表摘要不变，其中绿茵50项任务和1条进展记录完整保留。认证与任务服务 active，匿名和伪造身份头的4个入口请求均302转登录。FC API/worker PID和经营采集timer保持。浏览器工具启动报 helper_unknown_error，尚未完成修复后的真实执行人/注册只读页面验收。

不包括接口补充材料或G06等规划导入、Admin/Order数据迁移、自动供应商派单、账号角色变更或外部消息。本轮没有代发给蒋永增。

## 精确发布记录

- 基础 main：f0ec313c5bb9d90b400113fe5f58cec82234d108（PR39）；旧冻结发布包保持。
- 新本地活动修复源：green_plan_review_fix_20261009/source/。Git归档对应 releases/green-plan/20261009-review-fix/candidate/ 和 source/release_navigation.py。
- 清单 SHA256：1ca18d216f9f919b749e47dbac9664fd9763ab3deafbe65c2c81537b245e97b1。
- 执行发布器 SHA256：d858445f4387b0783d8b9c0f4c327cfee127bc0bc5deccac6c9daf6759328adc。
- 服务端 staging：/var/tmp/green-plan-review-fix-20261009T0800。
- 私有备份：/var/backups/fs-navigation-20261006/nav-20261008T235940Z。数据库备份只保留服务器，不下载或入Git。
- 五文件 source→runtime 与产物/旧基线哈希见 approved-manifest.json。旧注册源码/旧绿茵包不再覆盖本次五个路径。
- 现场验收位于本地 evidence/live-after.json，首次发布状态为 applied-awaiting-actual-http-role-acceptance，未伪造真实角色通过。

## 可重复的检查

Git仓库根运行（仅本地临时数据库）：

```sh
GREEN_AUTH_RUNTIME="$PWD/registration_approval_runtime_v3_20261006" GREEN_BACKEND="$PWD/releases/green-plan/20261009/candidate/backend" GREEN_AUTH_CANDIDATE="$PWD/releases/green-plan/20261009-review-fix/candidate/auth" python -B releases/green-plan/20261009-review-fix/tests/test_auth_flow.py
python -B releases/green-plan/20261009-review-fix/tests/test_rollback.py
```

复用现有 pr-fast 增加本次两个检查映射，没有新建工作流或放宽旧检查。

已发布清单是历史精确凭据，不能重跑 apply（当前目标基线已经变化）。后续更新先重读现场、生成新清单、备份并通过既有发布器；代码恢复仅针对上面的精确备份和清单SHA，先检查目标仍是本次版本，不恢复任何数据库。线上无需再次执行模拟写入来补造验收。