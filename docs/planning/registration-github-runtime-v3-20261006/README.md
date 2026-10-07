# 登录权限 runtime v3：独立 GitHub 草稿，未部署

2026-10-06，本次用户明确选择：将精确 runtime v3 已审查源码入私库 `wulv006-dot/FS-Workbench` 的独立草稿 PR，保留原服务器上传拒绝及生产验收门槛。本范围不含合并、生产上传、账号/权限/服务/Nginx 变更。

## 精确范围

- 基线 main：`bc3b29531cec2fab3fc090385f3d7d126eb9ada7`。
- 独立分支：`codex/fs-registration-runtime-v3-20261006`。
- 原冻结 ZIP：84,223 bytes，SHA256 `08c092e359205e00aa24f4746448402bc0931dd7209b45af6cb78b7904e14763`；ZIP 本身不入库。
- 冻结包 37 个载荷文件原路径、原字节保留；包根 manifest 按原字节存至 `docs/planning/registration-approval-runtime-v3-20261006/package-manifest.json`。
- 另增本目录四项：本说明、独立校验入口、本轮合成测试摘要和原始输出。合计 42 项新增；不更新旧 checker/AGENTS/其它 PR。
- PR #4 保存的是 v5 候选；本 runtime v3 使用冻结 v5 vendor，但不是 PR #4 的相同产物。#4 的 Linux 结果不能证明本 runtime 已验。

## 行为与批准合同

新用户 pending 仅介绍/本人申请，四个现有全局管理员明确批准后才授予 global readonly；敏感操作仍 admin。原全局身份保持；旧 FC 独立身份退役且不做同名提升；撤销使旧 session 失效，兼容回滚保留最新撤销账本和 witness，不恢复撤销。

v3 对旧 logout 的尾斜杠别名及直接方法调用统一使用确认页/拒绝写入；唯一状态变更退出仍为带 session、Origin、CSRF 的 POST API。历史三项独立静态审查均已闭合，见原工作区 v3 审查报告；静态审查不等于 Linux、真实角色或生产验收。

## 当前核验与失败

本轮逐项核对：38 ZIP entries 无重复/路径穿越，37 载荷的 bytes/SHA256 与本地冻结源码一致，manifest 原字节一致；四类凭据特征扫描无命中，不能称绝对无秘密证明。

本轮 Windows/Python 3.14 合成临时目录重测：**39 项，36 通过，2 项 POSIX 跳过，1 error**，退出码 1。`test_real_portal_handler_http` 在 logout alias/method 矩阵中出现 `ConnectionResetError [WinError 10054]`。本轮未定位为确定性源码缺陷，也未重跑掩盖失败，冻结源码保持不变。详见本目录 `verification.json`、`unit-tests-current.txt`。原冻结文档 37 pass/2 skip 是历史记录，不能代替这次失败。

本次新增 Linux 通过数为 0。未运行正式 checker，未新增或启用 Actions，不把空 check-runs 当 CI 通过。

## 检查入口

在独立协作仓库根目录运行原字节校验（只读）：

```text
python docs/planning/registration-github-runtime-v3-20261006/verify_candidate.py
```

在独立临时副本中运行合成套件，保留退出码和输出：

```text
python -B -m unittest discover -s registration_approval_runtime_v3_20261006 -p test_*.py -v
```

不要执行 `archive.py`/`qa.py` 来重写历史冻结文档。以上只核对/测试；重复执行不创建真实用户、不部署。Linux 的 POSIX 案例、独立多进程 harness 另行验证，后者未纳入本次上传范围。

## 合并与生产门槛

`releaseReady=false`。先解释本轮 HTTP 失败，再完成 runtime v3 精确源码 Linux/多进程/故障恢复检查。完整 consumer/query/session 隔离、全部 native creator fence、有效 Nginx/可信身份头/TLS/目录 UID/mode、合法已有四 admin/readonly 实测仍待验；不能拿导航、FC 或 v5 记录补算。

合并必须针对实际组合树独立复核，重建 checker 两份精确清单并执行有效检查，得到确切 head 的 owner 确认。生产另需当前现场 SHA、唯一写窗口、最小差异、保留 DB+witness 的兼容回滚及正式 action-time 批准。本 PR 没有生产 publisher。

原 `47.85.224.112:/opt/fs-registration-v3-qa-20261006T1010Z-08c092e3/` 上传两次自动审批拒绝仍未解决。本次仅为用户新明确选择的 GitHub 草稿目标；不重试原上传、不换方式向该目标传送、不修改审批设置或视作服务器上传批准。
