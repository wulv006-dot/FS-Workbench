# FC知识只读接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过既有知识发布器让真实FS原生新turn读取本次五项FC知识，不改native程序或服务。

**Architecture:** 在原知识scope适配器增加明确的knowledge-only分支，继续复用原冻结publisher的锁、CAS、备份、journal及rollback。克隆现场原25条已发布索引及原文，只追加本次五项，最后原子切换原FS路由；旧任务继续使用原冻结版本。

**Tech Stack:** 现有Python标准库、原知识适配器与固定publisher、既有FS原生knowledge host-call。

**Spec:** 用户本次授权FC知识库供Hermes使用；现行HOTFIX、知识CLOSEOUT和本目录交付记录。

## Global Constraints

- 不改native代码、模型/API、权限、价格、广告、排程或服务；本模式禁止停止/重启服务。
- 原13个FS条目、baseline兼容和其它用户路由保持；原25条知识及内容保持，新增五项按Git固定提交取源。
- 未知写入先核原release ID、journal、备份和实际状态；不盲重放。
- 无新增付费模型测试；真实FS模型报告与自然周期仍另列未验。

## Review Focus

- 载荷含代码/基准/服务或目录逃逸：拒绝；旧发布分支原行为和测试保持。
- sourceCommit与本次不可变目录不匹配：拒绝；旧目录不可覆盖。
- 原路由前值变化：CAS拒绝，不覆盖他人更新。
- 中途失败：沿原备份/journal回退；仅本模式没有可执行载荷，不进入代码恢复的服务停止分支。
- 真实FS冻结：使用原host授权链核读五个条目及SHA，不手写session或伪造来源。

### Task 1: 原scope知识-only分支

**Files:** 原 `releases/fs-dashboard/knowledge-layering-20261023/deploy/release.py` 与其现有 `tests/test_knowledge_release.py`。

- [x] 写并运行失败测试：仅policy与新不可变文档可入清单，代码/目录逃逸/授权扩大拒绝。
- [x] 最小实现：保留原fence获取与锁，只对非可执行知识载荷不激活代码恢复的服务动作。
- [x] 原2项及新2项本地测试4/4；PR813正式Linux pr-fast通过并合并。

### Task 2: 精确载荷与批准

- [x] 冻结原policy、原catalog与原文，哈希核对后克隆，原25条逐字保留。
- [x] 新增五项为 `fc.reporting.methods/data/report/business/maintenance`；新FS路由为原13项加5项。
- [x] 采集原publisher要求的52个保护SHA、目标元数据和运行前值，生成21文件最终manifest，主控核清单。
- [x] 正式PR813/CI/合并完成；原publisher inspect已执行。
- [ ] 原inspect被另一条2026-11-02的历史`dispatch_unknown`会话保护阻断，原native GET对账503；未apply。待原业务支持对账恢复后，同stage复核CAS与保护项，沿当前授权接续；不清状态、不停服务或绕保护。

### Task 3: 读回与收尾

- [ ] 核policy只改变原FS路由catalog/SHA与新增5个ID，原文SHA、其它路由及保护对象保持。
- [ ] 用真实受支持FS知识host链固定原identity，核5项可检索读取；不调用模型、不写伪造冻结文件。
- [ ] 记录原backup与回滚方法、实际入口/模型/自然周期未验边界，补交付记录与中文入口。
