# 受限发布入口（施工中）

- 负责人：DSH lead；分支 `dsh/release-channel-20261111`。
- 基线：`3efb92c60cfcc5b9b70496b58cbd18893e3c8ce6`。
- 用户选择独立受限脚本，不新增公网服务、端口、凭据或权限，不开放任意 shell。
- 原邮箱导出任务的独立工作区及未提交变更保持不动。

## 已实现的候选范围

`tools/release_channel.py` 是在合法服务器工作区运行的本地 CLI，不是 SSH 隧道，不解决当前 LOCAL 会话绑定，不提供远程任意读取。它不修改 Remote Workspace 的隔离规则。

首个适配器只允许 `business-html`，复用 `fs_dashboard_overwrite_20261003/release_gateway.py`。这是仓库可核实的统一经营 HTML 发布器；不是邮箱导出 API/前端的发布映射。未核实模块一律拒绝，不拿历史 publisher/清单补位。

入口要求完整 main SHA、受版本控制的 releases/ 发布清单、干净 checkout、核实 origin 并 fetch main；HEAD 和 origin/main 必须等于指定 SHA。通过 gh CLI 读取该 SHA 的完整 check-runs，必须含成功 pr-fast 且无失败/未结束检查；超过100项无法完整读取时拒绝，不把第一页当完整。

发布清单、HTML 及 gateway 的本地字节必须与指定 SHA 一致。清单载荷哈希必须匹配。默认只做来源检查和计划，**不表示现场 CAS、依赖或业务健康已验证**。显式 --apply 才调用原 gateway，由它保留原发布锁、现场基线、七个共享依赖、备份、pending 意图及账本守卫。无 rollback/recovery 绕行参数。

示例（占位路径，待准备真实清单，不可原样发布）：

```bash
python tools/release_channel.py --module business-html --sha <完整当前mainSHA> --manifest releases/<本次发布>/manifest.json
# 只有合法服务器会话、实际部署授权、真实清单及现场基线核实后才追加 --apply
```

入口不获取持久 token、不存认证数据；使用环境已有 git/gh 登录。失败不输出子进程 stderr（可能带认证 URL）。apply 失败报告副作用 unknown，沿原 releaseId 检查 gateway pending/账本/现场，不盲重放或自动旧包覆盖。

## 尚未完成，不能宣称上线

- 生产活动 publisher 的安装路径/版本、实际主机部署映射和受限调用身份尚未读回。
- 目前仅支持统一经营 HTML；FS 数据工具 API/静态资产须核实现行 publisher 后增加精确适配器，不能误用本入口覆盖。
- 精确 main SHA 若没有成功的 pr-fast check-run，会明确拒绝；不把分支 CI 当作 main SHA CI。既有 pr-fast 工作流增加 main push 触发、before→sha 差异范围，保留原PR触发、只读权限与离线隔离。入口核对 github-actions issuer、固定工作流路径/main push/仓库/精确SHA及 job.check_run_url 与 check ID 的关联。该工作流尚未在远端实际运行验收。
- gateway 成功返回仅说明文件级发布及账本回执，业务入口/权限/数据健康仍待读回；输出 published_readback_pending。
- 未部署、未运行生产 apply、未完成183 Linux验证。自动失败恢复仅复用 gateway 已有保护；未知状态人工/既有恢复流程对账，不新增自动回滚。
- 本入口是受控工作流，不是对 root 的 OS 安全边界。

## 验证

- Windows Python3.9：7项单测通过；pr-fast --selfcheck通过；受影响分组release-channel在离线进程/网络守卫内再次运行7项通过；git diff --check通过。均非生产/183验收。
- 独立审查发现4处问题，已修正候选：用git指定SHA的字节直接compile/exec，忽略pyc；原gateway锁内部阻断pending意图；绑定GitHub Actions工作流/job身份；为既有pr-fast补main push路径。未修改原gateway源码，未新增第二套发布锁或覆盖器。
- 初次回归1个夹具缺issuer导致失败，补齐后10项通过（包含真实gateway锁/pending、缓存替换、工作流身份测试）；后续增加main/PR触发静态合同测试。最终11项回归及离线分组11项通过，pr-fast --selfcheck与diff --check通过；复审结果待收取。
- PR、CI、合并、生产部署、业务入口验收分别待执行。
