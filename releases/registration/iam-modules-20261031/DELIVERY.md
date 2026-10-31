# FS 工作区权限修复 · 2026-10-31

已上线，陈超反馈 liushengjie 刷新后已恢复。

## 变更
- 角色按工作区整理为球类、RPG、营销、活动、数据、智体、机器人、协作运营；平台管理员、只读、部署与专用观察身份保留独立边界。
- 已批准注册账号的业务访问统一读取 IAM，不再被旧路由/查询参数白名单二次拒绝。注册、审批、撤销、停用、过期、同名冲突、CSRF 和账号数据结构保持。
- 补齐营销、主站活动、FC 进化、经营看板接口及 Hermes/FC API 映射。未登记资源仍拒绝注册账号；专用 FC 观察账号仍只允许原精确 GET。
- 既有成员有效授权和 deny 保留；旧混合角色中不能整模块归并的授权在成员抽屉明确展示，可取消。清空角色不再回落默认 Viewer。
- 注册审批复用成员管理的统计卡、表格、状态标签，增加搜索、筛选、全选和逐行操作，保留原审批 CAS、审计和未知写入结果不重试规则。

## 验证
- 63 项 Python 权限/控制台/注册访问回归通过；12 项密码请求合同通过。
- 原浏览器注册、待审批登录、未知结果不重试及审批并发冲突回归通过。新界面的搜索/筛选、拒绝原因、请求内容、浅深色和角色切换通过。
- 线上真实账号状态 + 进程内会话接缝检查 15 条访问，10 条从 403 恢复 200；3 条越权/未知请求保持 403。该诊断不创建凭据，不冒称本人浏览器登录。
- 真实 Chrome 管理员页面核对审批表格、工作区角色及 liushengjie 的权限自检结果；随后陈超明确反馈本人刷新后恢复。
- 无真实注册审批、改密、改价或业务执行试验；业务服务原有专属写入校验不在本次放宽范围。

## 活动来源与发布
- 负责人/发布者：GPT；分支 codex/fs-iam-modules-20261031。
- IAM 可维护源：opt/fs-access-policy/{rbac.py,iam_console.py,web/app.js,web/app.css,web/registration.js}。
- 注册适配可维护源：本目录 candidate/module_permissions.py → /opt/auth-portal/registration-runtime/20261007-ca6258ad/module_permissions.py。
- 本目录 candidate 为实际六文件载荷；manifest.json 记录原始/发布 SHA。canonical 文件仅换行保持仓库惯例，candidate 保留实际发布字节。
- 使用 2026-10-30 注册发布器的精确副本 publisher.py（SHA df4441db0e718585862cb4dbd7c84f06b1f2373cd5d262dafa537524205926c7），同一共享发布锁、CAS、备份、回退。apply.py 只限定本批六目标和认证服务重启。
- 服务器暂存 /opt/fs-release-stage/iam-modules-20261031；代码备份 /var/backups/fs-navigation-20261006/nav-20261031T094000Z。
- 活策略由 roles.py + migrate_live.py 经原 save_policy/audit 从19迁到20；不提交现场策略、密码、会话或用户数据库。
- 正式本机档案 D:\共享资源\服务器\2026-10-31_FS权限修复；含基线、载荷、测试及 verification-live.json / policy-migration.json。
- 最初发布编号格式被原发布器拒绝，发生在写入前；随后使用规定 nav 时间格式发布成功，未绕过检查。

## 回滚
在服务器运行 `/opt/python39/bin/python3 /opt/fs-release-stage/iam-modules-20261031/rollback.py`。
脚本核对本批代码 SHA 和策略 revision，再沿原 publisher 还原六文件；经原策略保存器恢复原角色授权并追加审计，启动 auth-portal。保留全部数据库、会话和历史审计。若之后有人改过策略或源码，拒绝覆盖，需定向合并回退；不得整库恢复。
