# FC 项目复盘的 FS 数据入口

`business.fc_project_review` 从 `unified-business` 目录发现。只接受 `profile`、`start`、`end`，游戏取 FC26 或 FC27，日期采用包含结束日的北京时间自然日。目录声明固定将原调用者的登录态带到 `/dashboard/fs-home/range.json`，查询条件为 `mode=fc-project-review`。FS 后端复用原管理员权限，范围和结果不由连接器改写。读取返回 202 时沿相同参数继续。大报告用 `data_path` 展开，例如 `/packets/0/kpi`、`/packets/0/ordersData`。

## 发布输入

- 2026-11-19 已读回运行中镜像 `sha256:18a4c07741382bef8a99e0c3967d7b31a0c9a4d21e0a6d080018f706dd379088`，本机标签 `fs-data-connector:stage5-methods-27fe096`。
- 现行目录哈希 `07c81c4615d5c30aeee969f145a3c4c09971030f445682eb3330f2a70394a598`。新目录只增加这一入口及统一经营模块的操作计数。核对脚本逐项比较原 116 个操作、其余覆盖和数据方法。
- 运行服务定义哈希 `e353ddb0c4ac846086675f331fc3e8331260ff7ff965ff2156e4598c5f7f9ffb`。只替换连接器镜像 ID，应用、读回和回滚复用原连接器发布器。OAuth 数据、访问权限、网关配置和其它服务使用现场现有配置。

## 流程

先通过原授权读取现役镜像中 `/app/fs_mcp_connector/catalog.json` 的原始字节。在包含已审核源码的工作树，使用 `connector_release.py prepare <候选目录> --active-catalog <原目录文件> --source-commit <完整源码 SHA> --merged-commit <完整合并 SHA>` 生成候选。真实发布在同一批准窗口最后执行，先确认所映射的 FS 后端已经随本专项发布且可使用。

在已批准的服务器隔离目录运行包内 `python3 -B connector_release.py build`，以现场固定镜像离线构建单目录层。运行 `python3 -B connector_release.py check <新镜像 ID>` 复核运行镜像、服务定义及候选哈希。经正式授权执行原包内 `apply` 后，从真实连接器按本目录和目标操作读回，核对原 admin 权限和返回期间。回滚沿同一候选包内 `rollback` 与备份回执。若原基线已变化，先核对现场实际版本和差异。

本地已验证固定路由、未知参数拒绝、原管理员拒绝透传、202 原样续查，以及目录逐项差分。镜像构建、运行镜像读回和认证角色验证分别记录。
