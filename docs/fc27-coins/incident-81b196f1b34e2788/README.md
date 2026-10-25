# FC 81b196f1b34e2788 — 成本进程超时分类与恢复

本轮原自然任务 `715ec3af-8ade-45c5-b821-186face4572b` 21:14:20 入队，21:17:50 因 `IGGM:http_blocked;P2PAH:collector_failed` 终止。9 条有效竞品、0 成本、汇率有效、NO_QUOTE；六类同 ID 报价/预览/请求/执行/ALL/Player 产物均不存在。IGGM 缺源按现有覆盖合同允许，本次阻断为三平台成本缺失。

失败文件 `p2pah-cost-Wmd3OyoU.failed.json` 为 0 字节。Docker 原事件显示容器 `6cbc8c6c880e…` 运行179秒后收到 SIGTERM，exit143 并销毁，与包装脚本原180秒 timeout 一致。原包装脚本丢弃该退出分类，空文件转成泛化 collector_failed，故原快速退避白名单未命中。不能由这些证据进一步判断当时卡在哪一页或共享会话步骤。

最小改动仅 `collect_p2pah_cost.sh` 保存 timeout exit124，输出 `collector_process_timeout` 与180秒限额诊断；`automation_tick.py` 仅允许 P2PAH 的精确新分类沿原同轮无写入证明进入既有5/15/30/60退避。泛化错误/身份/验证/UNKNOWN仍不快速重试，原180秒、成本身份/交货类型/三平台检查、策略与120分钟周期保持。

维护源 `fc_cost_timeout_20261025/source/`，原基线/测试/发布适配器/manifest 同目录。沿原CAS publisher、共享发布锁、队列锁与业务锁，备份 `/var/lib/fc27-cloud/rollback/fc-cost-timeout-20261025`。21:26:38北京发布成功，只重载API，worker/timer未重启、10保护项不变。按该更严起点6小时补PR截止为2026-10-26 03:26:38北京。

- automation_tick.py SHA256 `d655b45d5de928b10c9db5bff789e56a7510dc925aea3ebaca52d3c20694888b`
- collect_p2pah_cost.sh SHA256 `54162c961df9baca33057bf2fe2632380a2fca554d1d81a125af1b8a901c224d`

Windows只通过重试证明单测、3项shell测试未执行；原生产发布前Linux实际4项0失败/错误/跳过，包含原包装器丢失超时的复现、新超时码、成功成本/交货验证与写入护栏拒绝。测试使用临时目录/假Docker，无业务调用。

21:27仅发布一次人工完整恢复周期 `52e40842-e0e5-492c-8980-c36e676c3742`，原队列与持久 recovery-intent 防重复；原715失败未修改、不重放原写入。这是人工恢复，不称自然验收。完整结果与PR/正式CI尚待更新；不据新单running或告警消失关单。

原始私有回执在已ignore的 `fc_cost_recovery_20261025/READBACK-incident-81b196f1-*.json` 和 `fc_cost_timeout_20261025/READBACK-*`。只读重跑使用本任务 read_result.py 经现有获准SSH stdin入口；recover_once.py 仅回报已存意图，不可换ID补发。RPG仍由大超的WorkBuddy处理。
