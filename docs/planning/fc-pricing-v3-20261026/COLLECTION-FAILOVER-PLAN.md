# FC采集接替候选计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，当前会话实施，最终独立审查。

**Goal:** P6候选使183单节点故障时187按同job有限接采，并保留来源全局拒绝与原回执。

**Architecture:** 沿用Coordinator租约/permit与Worker；仅显式nodes包含187时允许备用，最多2attempt/6GET。187备用为短任务，独立spool和本机互斥，无新daemon；183恢复需60秒冷却和既有健康稳定窗口。原业务publisher/消费保持未启用。

**Tech Stack:** Python3.9标准库、SQLite、Linux flock、已有RestrictedHTTP/Worker。

**Spec:** 最新施工包01 P6、03故障矩阵，COLLECTION-TRANSPORT.md。

## Global Constraints

- 不停原FC/RPG/Order，不改计划/定价/writer；仅新增FC候选。
- 旧lease、unknown permit、重试退避全部到期后才接替；失败不退还请求计数。
- 401/403/challenge/429不切出口；原run/context/deadline不刷新。
- 使用183隔离Linux测试，不向其业务服务注入故障。
- off/shadow沿旧输入；显式路由配置下仍尊重全局拒绝/冷却和在途窗口，不清账本。

## Review Focus

- 丢ACK其实已成功时先读原回执，不启动备用。
- 分区旧请求仍在飞时，备用不得并行发同origin请求。
- 恢复183不能在冷却结束前抢当前备用任务。
- 同run多进程只能一个187备用进程，不相互替换boot或混用spool。
- off回退保留拒绝/冷却、permit和原失败记录。

## Tasks

- [ ] 测试先覆盖：真实失败接替、旧结果拒绝、丢ACK、403/429无备用、恢复冷却、目标job、在途关闭。
- [ ] Coordinator节点隔离/恢复窗口、Worker目标job，复用原租约和permit。
- [ ] 187本机有限fallback，固定原task，Linux互斥、独立spool，原失败证据保留。
- [ ] 控制角色/测试白名单、完整FC及183Python3.9回归、独立审查和正式CI。
- [ ] 准备具体试点发布/验证/回退清单；生产切换另按明确授权，入口空闲不自动视为切换授权。

## Execution ledger

- BASE f5b318694c13735184124fee88340f47ad94fa0e，P3 PR758已合并；源生产文件未发布。
- 用户确认生产入口现已空闲，允许继续准备验证。
