# ES 与游戏名称线索 V3 发布候选

状态：仅候选，不代表已部署。默认 `releaseReady=false`；未冻结 source commit 时保留 `baselinePending`，不得执行。

固定13目标：Google details 的 `detail_model.py`、`traffic_contract.py`；Hermes 的 controller、research、marketing_snapshot、ES、traffic_contract；共享 business range；session 的 service Python、ES、traffic_contract、Dockerfile；session unit。ES 与三份共享合同逐字节一致。其余当前97项基线中84项保护不改。

ES 默认 `profile=ALL&group_by=game`，单游戏使用已核实的精确导出标签。七参数上限只在当前真实共享 Handler 从6增至7，参数白名单与重复参数拒绝不变。按期间共享源任务、按查询冻结投影；切游戏不重新导出。历史档案缺文件集合元数据时明确 partial/unknown，不补造完整性。原件、durable attempt、未知结果及历史报告保留。

D4-SN-* 只作 `campaign_name_prefix` 名称线索，普通候选可展示小计；D4-SN-Brand-Global 为 `brand_scope_unverified`，`game_target=null`、`game_candidate=D4`，单独列示。没有 Aion 匹配不能标零。全局仍用全部原生账号合计，FC 及用户已确认全局品牌规则保持。

## 准备与检查

父任务目录以下记作 P。当前现场基线由 `es-v3-runtime-baseline.json`、`es-v3-maintenance-baseline.json` 保存；与成功4b发布逐项比对，无哈希漂移。新镜像只基于精确本地 `sha256:b0235b2e5fd21d079dcd6c39c1eb5a7083e86f2748c0c030f2ce320468f6178f`，旧 tag 不变。新 tag 是 `fc27-cloud-session:es-multigame-20261017-v3`。原持久 mount、权限、端口、网络和定时器保持。

从 repo 执行（必须使用新的输出目录和最终核验 head）：

```text
python releases/fs-dashboard/traffic-hermes-20261017/publisher/prepare_es_v3_patch.py --repo . --prior-stage ../report-inputs-stage-4b790805e5b0 --receipt ../report-inputs-release-verification.json --baseline ../es-v3-runtime-baseline.json --maintenance ../es-v3-maintenance-baseline.json --output ../es-v3-stage-<new-head> --source-commit <verified-40-character-head>
python ../es-v3-stage-<new-head>/publisher/es_v3_patch.py inspect --manifest ../es-v3-stage-<new-head>/approved-manifest.json
```

stage 的 `target-deltas.json` 列每个目标的 before/after SHA。新 head/源码/现场基线变化必须重新准备独立 stage。准备器不上传、不调用模型、不触发导出、不写生产。

## 受控执行边界

沿精确冻结的原 publisher：release locks、collector lock、Hermes admission、provider lock、锁内 CAS、逐文件备份/journal、恢复与原 worker/read service 健康检查。第一处替换前停止只读 business range 与 marketing range；marketing 使用本次新 PID/cgroup/unit 指纹，原 daily collector 和 timers 不停。两只读服务确认 inactive/MainPID0/cgroup 无残留才写文件；未知结果保留 journal，不强行继续。回滚恢复前再次实测停止，不能相信旧布尔标记。

发现既有 `.attempt` 时先沿原查询只读对账，拒绝重启 session 丢失未核结果；不删除标记、不盲重提。session build 显式 legacy builder、`--pull=false --network none`、精确 image ID 和超时，失败保存私有输出，超时 UNKNOWN；同 build intent 不自动重试。失败恢复保留档案/cache/attempt/镜像。成功后整包手工 rollback 默认拒绝，应前向修复；不得顺手恢复旧 Admin/Order、品牌或 Top 口径。

CI、独审及本次具体生产授权完成后，父任务可产生新的 execution manifest 和独立 release ID，继续调用同一 `es_v3_patch.py apply --manifest ... --approved-manifest-sha ... --release-id ...`。不得改用裸覆盖或重用此前操作 ID。发布后仍需逐项读回13目标/84保护、旧 tag、新运行 image、三源码、持久 mount、原 timers/nightly、匿名401和真实角色/按需数据验收。
