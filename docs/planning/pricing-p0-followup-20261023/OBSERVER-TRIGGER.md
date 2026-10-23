# ItemD2R 观察服务触发修复候选（2026-10-23）

状态：候选已通过本地 11 项、服务器隔离 Linux 11 项检查；本模块未发布、未启停服务、未触发采价、模型或业务写入。主 Agent 负责统一发布，预计等待下一原自然周期验收，不能将候选测试称为自然恢复。

## 现场事实

17:23—17:29 只读核验：`/var/lib/fc27-price-observer/samples/` 仅一个样本，`latest.json` 是其重复投影，不能计作第二个样本。样本原 ID 为 `efa86d1a-dd67-410d-807e-6840f069594b`，观察开始于北京时间 15:44:34，完成于 15:44:39。

ItemD2R 的 PS、XBOX 均为 USD 9.85/100K，PC 为 USD 8.15/100K，赠送均为 0K；三平台真实公开采价均有效。但关联原竞品快照采于 14:56，本次 ItemD2R 采于 15:44，最大时间跨度 2905.966717 秒，超过原 300 秒同轮可比上限。因此现有可比组数为 0、有效实验加权情景为 0；只有单点观察，尚不能声明涨跌趋势或加权模型结论。IGGM 三平台仍缺失，不能用旧价补齐。

17 点原自然任务的准确 ID 是 `90b1662b-3ce1-4d3d-a535-d344fb01a58b`（`a535`，不是早前转述的 `a53d`）。它于 16:59:36.930060 创建、17:02:26.236655 完成，原 run 已 `ready_for_quote`，12 行原竞品、汇率及公开售价完整；原 Hermes 结果为 `no_price_change`，预览为 `review_only`，并非新写价。原 run SHA-256 为 `e3bc5628afa06b43a039a2ef5c79b608f624cc666ebe248d35cb19d92884a04d`。

## 漏采根因

原 path 监视整个 `/var/lib/fc27-cloud/jobs`。原业务进度的多次原子写触发服务；新任务尚未 ready 时，原观察程序只找到旧 ready 任务并立即返回 `already_observed`。日志中 16:59:37、17:01:00、17:01:05、17:01:15 四次启动均如此，17:02:23 开始因 300 秒内最多四次启动而 `start-limit`，早于新任务 17:02:26 ready。

这是触发与 ready 生命周期未衔接导致的漏采，证据不支持将其归为 ItemD2R 公开采价失败。path 本身仍 active/waiting，但 service 已 failed/start-limit，不能凭 path 正常就认定追踪正常。

## 最小候选

维护源与确切 SHA 见 [`SOURCE-MAP.json`](../../../fc_itemd2r_observer_trigger_recovery_20261023/SOURCE-MAP.json)。候选源码冻结为 `2d5f9f35e66c35de8ace22dfdb88d7eb15bbff6f99fcb9076ffd399c0f50d216`。

在原 path 启动的同一进程内，最多等待 300 秒，每两秒检查原 queued/running 工单；等待期间不持有业务锁。空闲后才调用完整保留的原 `main()`，真实采价仍沿用原 queue、全部 RETRY_LOCKS、UNKNOWN/未完成执行门禁及原 ID 样本排重。若锁忙继续有界等待，不增设 timer/daemon、不放宽启动限制、不改变原业务周期。此次 17 点从任务创建至 ready 约 169 秒，在等待预算内。

原单位为 `Type=simple`，`TimeoutStartSec=80` 是启动超时，不能当作主体运行期限；有界等待由程序的 300 秒预算负责，原公开读取另有 60 秒上限。预算耗尽沿原 exit 75 和 15 秒 Restart 处理；每个忙碌进程会持续等待，避免进度写频繁消耗启动预算。

CLI 结束后调用主 Agent 提供的 `reference_observer_view.publish_view()`，仅导出白名单展示投影。导出失败输出明确 journal 事件，保留既有采样结果且 exit 2；原 `RestartPreventExitStatus=1 2` 禁止因展示导出故障盲目重采。

11 项测试覆盖同进程等待到 ready、其他 writer、原子临时文件、锁忙、有界退出、原 ID 排重、按创建时间选择新工单、导出成功/失败、原 busy 合同及原 main 精确源哈希不变。

## 发布后待验

统一发布时按原 baseline SHA 做 CAS；仅清除已查明的 start-limit 状态，不为验收手动启动观察或采价。等待下一原自然轮，核原 ID 对应样本、三平台 ItemD2R 新时间、原快照 SHA 不变、同轮跨度及模拟状态、白名单 UI 投影。仍缺来源或超时必须按实际标注，不能将展示可读等同于形成趋势或可投入生产的调价规则。

原引擎、策略、12 行业务快照、模型及写价入口均不在本候选变更范围。实验权重仅供追踪模拟，不用于真实报价。
