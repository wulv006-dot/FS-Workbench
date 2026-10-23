# Hermes 原生学习：构建与发布候选

状态：2026-10-23，候选。默认 `releaseReady=false`，普通路由禁用。本轮未执行 Docker、生产发布、服务操作或模型调用。

## 普通FS与每日审核配套候选

`tools/prepare_learning_release.py`只离线准备新知识目录`hermes-learning-closure-20261023-1`及9个确切运行目标：FS的knowledge_catalog/business_context/controller/conversation_service/business-baseline/reviewed_skills、容器外审核的review_queue/reviewed_skills，以及原06:00的daily_review。政策、profile配置、timer与原worker不在该发布范围内。两个新增helper以外的运行目标必须具备前值SHA；复用原publisher、准入围栏、CAS、备份与回退，变动FS代码时只重启原worker/range。

未绑定真实包含候选的commit时，输出知识仍为candidate；提供commit则逐源核对Git字节。冻结publisher保留其原始换行和哈希。8项producer检查已通过，相关逻辑及完整基准装配由知识组回归。普通FS和飞书正式启用task_routes、技能写入审核开关及原06:10提示追加均是独立的生产/权限审批项，不能由此代码包推定已启用。

## 入口和固定范围

- `tools/prepare_learning_native_release.py`：默认只生成精确构建目录和阻塞预览；`--build` 是独立、明确的镜像构建动作。已有未构建预览可按同 operation ID 升为构建，`image_build_intent`、unknown 或已构建状态不会重建。旧 `prepare_native_knowledge_release.py` 和其两 COPY Dockerfile 保持。
- 本目录 `deploy/native_release.py`：唯一新 scope 为 `hermes-learning-native-20261023`。复用原 frozen CAS/备份/日志 publisher 和原 native SQLite、admission fence、停止/启动/回退函数。
- 新镜像只 COPY `/opt/hermes/fs_native_entry.py`、`/opt/hermes/gateway/run_turn_runner.py` 和 `/opt/hermes/reviewed_skills.py`。原 desktop 构造器源字节保持；基础镜像 ID、三份原源码、基础层、运行用户及构建后四份源码均严格读回。
- 真实 builder 在任何 Docker 操作前，以 `git show <source_commit>:<path>` 对九份源输入逐一核对 LF 字节，包括 entry、helper、patcher、Dockerfile、producer/adapter 和知识消费源；还核已准备 context 三份输入与该 commit 相同。未提交候选、缺失 commit 或旧代码冒充新 SHA 均不构建。离线 context 不声称绑定已发布 commit。
- 仍只有四个既有文件目标：原插件注册器、knowledge.py、原政策和 desktop systemd unit。注册器和政策必须与前值字节相同。unit 仅允许镜像替换及固定 `--mount=type=bind,src=/var/lib/fs-hermes-memory-approval/published-skills,dst=/approved-skills,readonly`。不会把包含待审/备份/记忆的整个审核 ROOT 挂进容器。
- `/opt/fs-hermes-fc/{knowledge_catalog,reviewed_skills}.py` 是明确的已有源码依赖，由 FS 候选先发布；新 native manifest 只把其精确候选 hash 加入 `unchangedRequired`，不在本 scope 改写它们。运行时 `/fs-source` 优先加载的 helper 必须与镜像候选一致。

本次已合法取得的现场源：基础镜像 `sha256:d51507514f3f52fdcc3cb6bc0d36e2b12863517aa590ae1338dd462ffe1636a4`；desktop `5e69b1d2290d5cca7ea9fd8be543585ad393d65fd9a8d9d1d9645437dc853252`；原 fs_native_entry `3ec3401b894bd576260b87a6e29f2b406bbc06b3e3f1cb0ad63aea2499e1e278`；gateway `6ec879a91aa09765515a69368c886d1ce4d3174b159868c966e8740e9cf1b347`。gateway 精确补丁结果 `23b99dac6998e1e1e4639bcaf80b3cd6cc72e6582c3fcb13f423754bbd36aaf9`。

## 预检与 manifest 合同

完整 `preflight` 需要 `current_image`、`native_image_sources`、`unit_before_path`、`policy_before_path`、`gateway_before_path`、`native_sqlite_version`、`source_commit`、原插件两文件 `before_hashes`、`unchangedRequired` 与 `runtimeRequired`。要批准实际发布还须完整 `nativeProtection.metadata/trees`。缺失或不兼容 SQLite、漂移源码/注册器、已开启普通路由及超出既有目标均拒绝。

可执行 manifest 的 schema 由 `deploy/native_release.py::checked` 和原 publisher 联合强制：

| 字段 | 约束 |
|---|---|
| scope | 仅 `hermes-learning-native-20261023` |
| releaseReady | 生成器固定 false；明确批准后仍须完整保护证明 |
| businessWrites / timersChanged / ordinaryKnowledgeRoutesEnabled | 均 false |
| nativeImageBefore / imageId | 精确等于本次已核基础镜像 |
| nativeImageAfter | 真实构建读回的不可变 sha256，必须不同于 before |
| nativeImageBeforeSources / nativeImageSources | 原三份源码及新四份镜像源码集合精确匹配 |
| nativeExtraSources | 两份 FS helper 的候选 hash，必须有对应 unchanged guard |
| reviewedSkillsMount | 仅固定 published-skills 只读目录 |
| files | 仅四个既有目标，逐文件原值 CAS、候选 hash、root:root、0644 |
| policyPreservedSha256 | 完整原政策 canonical hash；政策候选本身还须原字节不变 |
| nativeSQLiteVersion / nativeProtection | 原版本与原 SQLite/admission/保护检查保留 |

实际镜像构建需要独立审批。未构建的 `native-build-preview.json` 没有 after image ID，也不是可执行 manifest；不会用虚构 image ID 或 unit 内容填补。

## 本轮可审结果与缺口

已使用此前合法读回的 gateway 原文及本地候选生成实际四文件构建目录，见本任务 `.agent_runtime/native-learning/prepared-context/`。该目录和预览保留 `context_only_needs_preflight`，未生成可执行发布 manifest。

新请求导出精确 systemd unit 的动作被自动审批拒绝，尚无本轮完整 unit 原字节；因此具体 unit diff、原 SQLite 当前版本、Linux root-owned 发布目录/锁检查及新镜像 digest 均未伪造、未验证。后续须取得针对这些必要最小读取/隔离构建的合法批准；不换脚本、分包或通道重新导出被拒对象。无需再次导出群身份或历史会话。

## 离线验证

- 新 producer/adapter 11 项测试全部通过：默认无进程执行、实际 COPY/文件路径、精确 policy/unit 增量、底层原 publisher/fence 复用、不可扩挂载/路由、source/layer/user/readback 漂移、同原 ID 正常升阶、unknown 不重建、commit 源字节绑定。Docker builder 单测的 image/source 返回均为明确 fixture，不能当真实镜像或 commit 验收。
- 旧 producer 7 项回归通过，原插件注册器仅工作副本 CRLF 对齐 LF，逻辑差异为 0；原检查未放宽。
- 原生知识/已审技能定向验收见同次主交付。上面的 Docker/systemd 测试全部是 mock，不代表真实 Linux、image build、真实模型或生产验收。

重跑：bundled Python 执行 `-m unittest discover -s releases/fs-dashboard/hermes-learning-closure-20261023/tests -p test_learning_native_release.py -q`。只读上下文准备使用 `--context-only --gateway-before <已合法取得的源码文件> --output <新候选目录> --operation-id <原变更ID>`，不需要 systemd、Docker 或网络；现有目录不会被覆盖。
