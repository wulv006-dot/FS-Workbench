# 夜间调度与现役控制器的上下文合同

2026-10-30 生产 `nightly.py` 在原夜间任务上调用 `submit_scheduled(body, context=report_context(...))`，现役 controller 仅收 body，导致 `nightly_TypeError`。主代理只读快照 controller SHA256 为 `75c1b1f6b6af47fe00465e8b4dd0e9628ed17dbd85be0b1988145dbf41dc8e28`；全文与 `releases/fs-dashboard/knowledge-layering-20261023/source/controller.py` 一致，CRLF 转 LF 后 SHA 为 `706b11a00319de14c32faf0e3ffcc68974cc2d20745bc954c2e01213bbde5c35`。

旧 `nightly-reschedule-20261025/source/controller.py` 已有 context 合同，但整文件还包含旧 admission_guard 及另一套状态诊断，不能直接覆盖现役控制器。活动维护源继续使用 knowledge-layering 的 controller，仅回补四点：内部 submit_scheduled 接收可选 context、原线程池传递 scheduled_context、execute 接收可选参数、已有夜间 deadline 时把观察附入原 prompt。观察明确不证明区间完整，不替换原 question、事实、任务 ID 或幂等处理。

用户公开请求仍不接受 scheduled_context，原 600 字提问限制、owner 授权、截止边界、维护准入锁及已有请求去重保持。过期任务仍 EXPIRED，不新建请求，不补跑 10/30 日报，也不创建缺失的旧管理日报行。本次不改 nightly/nightly_data、时间表、采集、业务权限或其他服务。

回归直接抽取活动维护源的真实 submit_scheduled/_submit_report/execute，与真实 scheduler 接线，在隔离 SQLite 中验证五类原报告、长缺口观察进入实际派发输入、原请求 ID、公开字段/提问限制、无权限拒绝、过期原 ID 不准入。pr-fast 将活动 controller 的变动同时映射至 knowledge-layering 与 nightly-reschedule，避免只测历史候选。

当前范围为本地修复、PR 与正式 CI；不代表生产已安装、下一自然轮成功或历史日报已恢复。后续单文件发布须以现场新鲜 CAS 对应现役 controller，沿原发布器保留准入锁、备份、回滚及读回，另行授权执行。
