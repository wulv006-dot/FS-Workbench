# 私库候选边界与写入步骤

2026-10-18 只读核对 `wulv006-dot/FS-Workbench` main：commit `bae1f9e3302553e0bb88505d4e1e42eda25bf885`，tree `06d2c03b50440bbf1e2795c1ea6b9a93f3dfb105`。新目录 `releases/fs-dashboard/hermes-conversation-20261018/` 未出现；既有 `releases/fs-dashboard/hermes-data-workspace-20261018/skills/data-storytelling/SKILL.md` 已出现，旧 blob `99cbe20c0a206cbb420cb6d49e4cac6d0a4ddaf8`。这些是准备时基线，写入前必须刷新。

`deploy/build_private_payload.py` 逐个读取明确清单，将每份源文件、字节数、SHA-256、Git blob SHA-1、预期旧 blob 写到本地忽略区的 `private-repo-payload.json`。本任务目录下只收录 `source/`、`frontend/`、`tests/`、`deploy/`、`docs/` 和 README；额外精确更新既有私库 `tools/pr_fast.py`，以及既有路径的 `data-storytelling` 1.0.4。本地技能源为CRLF，脚本仅对此文件生成LF派生件，派生SHA `a9e8e61e9d90be4417039983b6b9560119c363063ce5f5cc052865fb95ee1acd` 与已读回现场r4一致；原件SHA、派生SHA和关系均进入本机payload。源码仍可能继续修订，因此每次候选冻结都要重跑生成和 `--verify`，不复用先前字节或 stage。

绝不加入 `.agent_runtime/`、批准发布 manifest、会话数据库与原始记录、报告原稿、业务取数、凭据、密钥和运行产物。脚本拒绝非 UTF-8、二进制、符号链接、超大文件和可疑凭据赋值；人工仍需看完整候选 diff、路径与业务敏感信息。

可复用的私库 Git Data 写入顺序：重新只读获取 main commit/tree 和目标分支；用 `--verify` 保证候选未变；对照 main 的每个预期旧 blob 及新路径空缺；以当前 tree 为 `base_tree_sha` 创建精确 tree；创建父提交为当前 main 的 commit；创建 `codex/` 前缀分支或用 `expected_sha` 更新既有分支；读回 branch head/tree/文件 blob，再创建指向 main 的 draft PR。`github_create_tree`、`github_create_commit`、`github_create_branch` 或 `github_update_ref`、`github_create_pull_request(draft=true)` 均可走已连接的私库工具；任何写入结果未知时先读回，不盲重试。PR 必须保持候选状态，CI/隔离 QA、owner 和合并审批与生产发布分开。

首期最终权限：普通用户仅查看已有授权报告；新会话、取数、日报/周报/月报新生成、会话产物均只给管理员。私库代码检查不能替代活动 FS 身份、真实会话、在线文件隔离和回滚验收。
