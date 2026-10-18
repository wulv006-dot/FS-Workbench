# Hermes 持续对话首期候选

状态：PR #211草稿已建立，首版受控发布后正在真实验收与修复，尚未合并或完成验收。此目录只包含可审查源码、前端、测试、受控发布工具和脱敏说明。生产运行数据库、原始报告、会话内容、批准清单及凭据不进入私库。

权限：持续对话、取数、生成和下载会话产物均限活动 FS 管理员身份；普通用户只可查看已有获授权报告，不可触发新的日报、周报、月报或自由对话。HTTP 入口依据 Nginx `auth_request` 覆盖后的可信用户，再由服务端检查管理员身份，前端角色声明不构成授权。

旧智体中心只更新 `brain.js` 中一个入口：同源新会话列表返回明确 HTTP 200 且 `items` 为数组时显示链接；原报告查看能力保留。CI 只更新既有 `tools/pr_fast.py` 的本候选分派，不修改全局工作流文件。

发布边界：`deploy/release_scope.py` 固定现场目标；发布前须重新读取全量保护基线，使用新 stage、锁内 CAS、备份与读回。会话 `preparing`、排队、运行、停止中或派发结果未知时禁止发布。回滚只恢复代码及服务状态，保留会话数据库和产物；不得重放旧 stage。此工具不包含服务器凭据，也不自动发起发布。

本地核验：`python -m unittest discover -s fs_hermes_conversation_20261018/tests -p 'test_*.py' -q`；`python -m unittest discover -s fs_hermes_conversation_20261018/deploy -p 'test_*.py' -q`；`python fs_hermes_conversation_20261018/frontend/test_conversation.py`。这些检查不等于真实 FS 身份、Linux 服务及生产会话验收。

私库候选由原工作区本地辅助程序 `fs_hermes_conversation_20261018/deploy/build_private_payload.py` 生成并用 `--verify` 核对；该本地辅助程序不随私库候选归档。输出仅在本机忽略的 `.agent_runtime/hermes-conversation-20261018/private-repo-payload.json`；写私库前应重新读取 main/目标分支并核对 observedMain、目标路径和所有 Git blob SHA。另将当前 `data-storytelling` 1.0.4 回补至既有的 `releases/fs-dashboard/hermes-data-workspace-20261018/skills/data-storytelling/SKILL.md`，不得在本任务目录复制出第二条技能真源。

长期知识：只有用户经Codex或Desktop明确交付可更新长期记忆与规则。FS聊天仅保存本会话上下文，不写共享知识；已审报告与业务技能由现行版本的按需章节工具读取，避免整包文本超出工具上限。
