# FC采集接线发布准备

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，当前会话实施，最终独立审查。

**Goal:** 沿原publisher准备精确三个原入口文件的增量发布和回退，不启用生产消费。

**Architecture:** 在现有target_map/prepare_manifest/fc_v3_release_adapter增加一个固定collection scope；原locks、CAS、备份、就绪、restart和UNKNOWN保护保持。控制/节点角色仍由既有独立角色更新器处理，凭据/业务DB不进包。

**Tech Stack:** Python3.9标准库、现有publisher。

**Spec:** 最新施工包P5/03验收回退，COLLECTION-TRANSPORT.md。

## Global Constraints

- 只发布两份fc_pricing_v3/sources.py和server_quote_job.py；不整包覆盖业务目录。
- 原publisher每次发布仍检查真实空闲和原ID/UNKNOWN，并按原机制重启FC API/worker/scheduler及Hermes就绪；不动Order浏览器/RPG/tunnel。
- off配置、真实影子、受控消费、自然轮分别验收；授权缺口只问具体动作。
- 本地执行环境故障已通过受审查宿主入口继续；Linux检查默认183隔离。

## Review Focus

- 新scope不能混入writer/业务规则/服务文件或新增目标。
- 新scope不能放松原locks/CAS/UNKNOWN/备份或漏重启需刷新代码的scheduler。
- Git来源及manifest完整性保持，三个目标的新旧hash可复核。
- 回退只恢复本次代码/开关，不清账本、任务、回执、策略或原失败证据。
- off时原自动化行为继续；消费开关必须单独按明确授权启用。

## Tasks

- [ ] 先测精确三目标、禁止新增/夹带writer、原重启保护与旧scope回归。
- [ ] 最小扩展现有scope/CLI，不新建publisher。
- [ ] 正式FC回归、183目标Python3.9检查、独立审查、CI/PR。
- [ ] 准备Git载荷、实际hash基线、一次性具体发布/验证/回退清单；生产动作仍按当前明确授权。

## Execution ledger

- BASE c4692767083b55eb0f39da24d31613cbf9f6af7c，PR760已合并，CI41472978702成功。
- 187三个活动文件hash与P3之前Git0ab6b023一致；routing.json不存在，原生产尚未切换，入口空闲确认只用于准备。
