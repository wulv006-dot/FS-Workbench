# 管理端（Hermes Desktop）改动通道

本文件由 Hermes 管理端建立，用于记录“管理端如何按仓库规则提交改动”。执行规则仍只看 [HOTFIX](HOTFIX.md)，本文件不新增流程、审批或权限。

## 通道

1. 工作区：`/profile/cache/workspaces/FS-Workbench`（管理端私有浅克隆，与线上 `/opt/*` 无写入关系）。
2. 分支：`dot/<topic>-<YYYYMMDD>`；一次改动一个分支、一个 PR。
3. 校验：`main` 由 ruleset `main-pr-fast` 强制 PR + 必需状态检查 `pr-fast`（`strict`，base 落后须先更新），禁强推、禁删除。
4. 合并：`pr-fast` 通过且 base 最新后 squash 合并；合并本身不授生产发布权限。
5. 发布：沿用模块既有 publisher 与发布锁，按 [模块发布与回退](../OPERATIONS-ROLLBACK.md) 执行；管理端当前只有仓库读写权限，没有宿主 `/opt` 或 Docker 权限。

## 边界

- 管理端不改 `/fs-source`（宿主机 `/opt/fs-hermes-fc` 的读写 bind mount）以外的线上文件。
- FC 自动采价/改价/Player 同步文件以宿主 `/opt/fc27-cloud-browser` 为运行真源；仓库顶层的 `fc27_cloud_browser/` 是 2026-10-05 归档口径，**不等于线上**。
- 代码完成、PR 合并、生产部署、实际业务恢复是四件独立的事，分别记录，不互相顶替。
