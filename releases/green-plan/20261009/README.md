# 绿茵计划协作模块

本包将绿茵计划放到 FS 协作专区首位，新增共享的项目总览、50项任务、详细规划、按周排期、阻塞和更新记录。页面：`/dashboard/tasks/green-plan/`。

数据在现有任务台 SQLite 的独立 green_plan_tasks / green_plan_events 表中；复用活动注册身份和任务角色。管理员分派与验收，执行人更新自己的任务，只读账号查看。并发更新冲突返回409，验收需要证据及前置任务完成，已验收内容修改需先重开。

## 来源与构建

本地开发源：green_plan_20261009/backend、web。candidate 是本次精确冻结发布产物，approved-manifest.json 列 source→runtime、产物SHA、现场基线及保护项。活动 taskboard_server.py 基线包含注册runtime消费接线，本次只增初始化/路由；不把仓库中较旧任务台候选当作生产全量部署源。

任务来自2026-10-08负责人版V2。初始50项均计划中、0%、未指派，所有建设进度由实际执行更新。正式时间由用户确认在2027年2月内，2月1日发布/2月8日核心验收为建议排期。

## 检查

- `python candidate/backend/test_green_plan.py`：临时库权限、并发、事务、依赖、验收、种子幂等、只读探针及隔离HTTP。
- `python check_release.py`：仅临时根，精确载荷、备份、正常/失败代码回退，保留原数据库。Linux使用真实文件锁/fsync；Windows只验证其余逻辑。
- 现有 pr-fast 增加上述最小模块检查；HTML/CSS结构、JS语法不代替浏览器验收。
- 浏览器本地界面检查与Linux证据见交付记录。合成身份不是生产真实账号验收。

## 发布与重跑

沿用 release_navigation.py 的双发布锁、目标白名单、当前SHA比较、备份、原子替换和逐文件读回。新增scope仅10文件，必要时仅重启任务台。SQLite备份保留服务器受控目录，不进入Git或下载。

`python release_navigation.py inspect --manifest approved-manifest.json` 为只读现场检查。apply必须使用冻结manifest SHA和未使用release-id；有漂移先停止核对，不重放旧基线。失败回退和人工代码回退均保留数据库、绿茵数据与审计。重新启动只插缺失种子，不覆盖用户任务更新。

能力探针只读取限定快照的生成时间与状态，不执行采集/交易/通知，不把服务可用当成业务验收；周报人工补跑与自然成功分开显示。

不包含凭据、会话、生产数据库或客户明细。不更改账号角色、旧任务、业务定价、商品、订单、采集计划、主Nginx或其它工作区资产。
