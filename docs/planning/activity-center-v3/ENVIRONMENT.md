# 执行环境与基线

核验日期：2026-10-24 UTC。

| 项目 | 实际值 |
|---|---|
| 执行电脑 | PC-20260909OJLI |
| OS | Windows 10 / 10.0.19045.0 |
| 沙箱用户 | pc-20260909ojli\codexsandboxoffline |
| 原通道本机用户 | pc-20260909ojli\administrator |
| 任务目录 | D:\codex\2026-10-24\task |
| Git | 2.53.0.windows.3 |
| 新独立检出 | D:\codex\2026-10-24\task\fs-campaign-center-v3 |
| 私库 origin | https://github.com/wulv006-dot/FS-Workbench.git |
| 远端获取基线 | 2c976e7f849b3b7916e006dd6907e633051cb3fb |
| 项目分支 | codex/fs-campaign-center-v3-20261024 |
| Node | 24.19.0 |
| Python | 3.14.7 |

本检出从 GitHub main 独立浅克隆，不使用其他任务分支施工。最初从旧部分克隆建立副本因缺少 promisor 对象失败，Git 清理了失败目标；随后直接私库克隆成功。原 E:\WorkBuddy\大超服务器 只读保留，其 main=1dd843ef0b991215fe66bd26b006f8ce37923a41、无remote，823条既有状态（92修改/2删除/729未跟踪）不纳入本项目提交。

## 原 SSH 与同任务续派证据

原入口：E:\WorkBuddy\大超服务器\server_187\access\Invoke-Server187.ps1。保持固定 known_hosts、既有原钥匙、本机临时受限副本和退出清理；不复制到云端、不改原密钥ACL或白名单。

| 检查 | 本机开始/结束 UTC | 远端 | exit |
|---|---|---|---|
| 首轮 | 08:36:38.2424169 / 08:36:40.8450165 | play187；2026-10-24T16:36:40+0800；root；/root | 0 |
| FS-V3-P0-READBACK-02 | 08:41:13.7345151 / 08:41:16.1964086 | play187；2026-10-24T16:41:16+0800；root | 0 |

首轮命令 `hostname && date -Is && id -un && pwd`，第二轮 `hostname && date -Is && id -un`。两轮本机均 PC-20260909OJLI，SSH运行用户 administrator。本轮 G1 尚未读取现役服务/文件SHA；SSH通不等于活动模块现场基线已核定。

任务API登记 hostId=durable，cwd呈服务端包装路径；命令实测在上述Windows电脑执行。现有接口不足以解释 durable 的确切语义，保留不确定性。

## 输入传输历史

Library解析成功；官方传输助手首次download failed，网络升级重试在Windows os.setxattr处失败，最终输入文件当时不存在。未修改助手或绕过元数据。用户后来明确指定本机Downloads ZIP，经本机文件读取关闭材料缺口，原失败记录保留。
