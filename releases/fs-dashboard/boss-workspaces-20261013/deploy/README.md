# 双工作区每日任务

本目录只提供两个 oneshot 与两个 timer，没有新增常驻服务、密钥或 ACL。游戏每天上海时间 09:00，经营每天 09:30；`Persistent=true` 补偿错过的触发，单次最多十分钟。重启后若尚未到当天计划时间，runner 返回 `not_due`，不提前消耗当天任务；到时执行当天一次，不循环补跑历史日期。

兼容现场 systemd 219，`OnCalendar` 使用服务器本地 09:00/09:30、不带新版时区后缀；发布合同须核实 Asia/Shanghai 并固定 `/etc/localtime` SHA。不使用新版 `StateDirectory` 指令，状态目录由 runner 自行创建。

代码放 `/opt/fs-boss-workspaces/backend/`，经营目标文件保留模块要求的位置。复用 `/opt/fs-exact-range-20261001` 的 `fc_daily.py`、`ai_advisor_model.py`、`fc_daily_model.py`；provider 必须已经支持 `max_tokens` 与 `timeout` 参数，共享账本版本必须完成本轮已授权的额度调整和跨进程锁。runner 只调用 `DailyReports(None, '/var/lib/fs-business-ranges/fc-daily').bounded_model`，绝不启动其 FC 调度器。

服务沿用 root 身份及已有 `/etc/fs-daily/deepseek.key`。经营来源只读固定 `127.0.0.1:8931/range` 的 catalog/summary，使用本轮已核实且授权的原执行用户 `wulv`；不允许任意 URL，不能新增管理员或绕过 catalog 可见性。游戏外部信息采集规则由 `game_intelligence.py` 白名单实现。

状态根 `/var/lib/fs-boss-workspaces` 为 0755，`public/` 为 0755、公开 JSON 为 0644；`journal/`、`history/`、`locks/` 为 0700，内部文件 0600。Nginx 只能通过既有登录保护的 exact alias 暴露：

- `/dashboard/game-monitor/daily.json` → `public/game-monitor.json`
- `/dashboard/game-monitor/daily.status.json` → `public/game-monitor.status.json`
- `/dashboard/management/daily.json` → `public/management.json`
- `/dashboard/management/daily.status.json` → `public/management.status.json`

不要开放状态根或私有子目录。源码与单位的安装、启用、SHA 读回及 nginx 配置由主任务沿用受控发布流程处理；本目录不自建发布器，不停共享服务或正常采集。

只读检查（不创建目录、不触发采集或模型）：

```text
/opt/python39/bin/python3 /opt/fs-boss-workspaces/backend/boss_daily.py inspect
/opt/python39/bin/python3 /opt/fs-boss-workspaces/backend/boss_daily.py inspect --kind management
```

显式人工触发会写来源投影、日志、快照，并可能产生已授权模型费用：

```text
/opt/python39/bin/python3 /opt/fs-boss-workspaces/backend/boss_daily.py run --kind game-monitor --trigger manual
/opt/python39/bin/python3 /opt/fs-boss-workspaces/backend/boss_daily.py run --kind management --trigger manual
```

同工作区、同上海日期仅保留一个 `run_id`，重复执行只回读该记录，不重新采集或 POST，包括来源失败、共享模型 busy 与 unknown。下一天可自然尝试新任务；首版没有删除当天记录或换 ID 重试入口。同次运行遇到明确无回执的 `model_busy`，仅等待 20 秒后用原 run_id/原投影再申请一次；已有回执或 unknown 绝不重发。`busy` 不表示模型已发出，`unknown` 不表示成功。中断时保留 journal，`model_pending` 回读为 unknown，发布未完成回读为 incomplete。

来源完全不可用时保留上次公开成功 JSON，只更新独立状态。经营有事实但模型失败时仍可发布明确标注 AI 失败的事实快照；游戏不把未分析来源冒充已验证事件。每次发布先保存私有历史，用原子替换写 JSON，并核对公开文件未被并行任务改动。原历史、共享模型账本和回执不删除。

离线测试：`python -m unittest discover -s fs_boss_workspaces_20261013/tests -p test_boss_daily.py -v`。测试使用假来源/假 provider，不调用付费模型。Windows 文件锁使用系统字节锁；目录 fsync 只在 POSIX 执行，Windows 通过不能证明 Linux 持久化、真实 systemd 调度或自然周期成功。
