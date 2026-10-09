# 看板管理员入口已发布

2026-10-09：当前管理员从工作台首页和经营分析页顶部“账号与权限管理”进入 `/__auth/access/`，处理注册申请与新注册账号模块权限。仅复用现有 `/__auth/verify` 的 `X-Auth-Role: admin`；未知/普通角色隐藏入口，账号失效隐藏，刷新及返回页面重新识别。后台权限保持既有规则，没有创建账号或授予权限。

活动增量源码：`registration_admin_entry_20261009/source/shell.js`、`runtime.js`；直接消费者为首页及原生经营/Google分析。其他工作区导航保持既有内容，未全平台接管。基线 `workspace-native-20261006-e006fb8d4ec1`，新版本 `workspace-native-20261006-721ad2810439`。上次已发布的Admin主站口径与页面切换保持均保留。

沿既有 `release_workspace.py`：14不可变资产、首页HTML/正式Nginx片段/navigation.js共17目标，114保护文件独立SHA读回一致，pending不存在，Nginx通过；没有服务重启/业务数据/账号/权限写入。批准清单SHA `034c0531457dda10699a9df10ce5f5dd8d236a9b23fe926d7fcea9153c83eb9d`，备份 `/var/backups/fs-navigation-native-20261006/workspace-native-20261006-721ad2810439`。

10条导航断言、Windows9及直接Linux9发布回滚测试通过；真实Chrome wulv首页显示入口且点击到管理模块（批量审批/审计可见）。没有提交审批、撤销或权限变更；实际普通角色UI未单独登录，隔离角色判断通过。首次预检因同一账本时间被本地旧清单转为+08:00而拒绝，零生产写入；修正为服务器+00:00原字符串后同一门禁通过，未放宽检查。最初猜测固定发布器路径不存在，改用已知上一发布留存文件，未另建部署器。

可重复只读检查：`node registration_admin_entry_20261009/check-entry.cjs`。同一发布版本不可重放；回退必须从上述备份沿原publisher重新核CAS，只恢复本次三个可变入口，保留不可变历史及所有DB/审计/账本。原E工程无Git远端或stage/commit/push，源不在server_187白名单，未作无关副本刷新；原服务器取消QA上传仍未重试。
