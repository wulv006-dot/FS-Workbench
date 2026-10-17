# 自动采集（d4follow-collect.timer）

2026-09-24 新增。**这之前服务器完全没有定时采集** —— 数据全靠人手动点页面上的「采集一轮」，
所以你才会看到「成本快照已超过 24h / 我方价已超过 12h」这类警告。

## 它做什么

每 2 小时调一次看板的采集接口：

```
POST http://127.0.0.1:8900/api/task   {"kind":"collect"}
```

**与手动点「采集一轮」是同一条代码路径**，行为完全一致：
IGGM 抓取 → 我方前端价抓取 → 千岛成本（按需）→ 引擎计算 → 写决策与改动记录。
**只采集与记录，不会改价**（真改价仍必须显式触发执行器）。

## 相关文件

| 文件 | 作用 |
|---|---|
| `/etc/systemd/system/d4follow-collect.service` | 触发一次采集（oneshot） |
| `/etc/systemd/system/d4follow-collect.timer` | 每 2 小时触发一次 |
| `/opt/d4follow/logs/auto_collect.log` | 每次触发的接口返回（含 taskId） |
| `/opt/d4follow/logs/task_<id>.log` | 该轮采集的详细日志 |

## 常用命令

```bash
systemctl list-timers d4follow-collect.timer     # 看下次触发时间
systemctl start d4follow-collect.service         # 立刻手动跑一轮
journalctl -u d4follow-collect.service -n 30     # 看执行历史
systemctl disable --now d4follow-collect.timer   # 停掉定时采集
```

## 改频率

编辑 `.timer`，改 `OnUnitActiveSec=2h`（例如 `30min` / `1h` / `4h`），然后：

```bash
systemctl daemon-reload && systemctl restart d4follow-collect.timer
```

## 注意

- **并发安全**：看板的 `spawn()` 自带锁。若定时触发时已有任务在跑，接口返回 409
  （日志里能看到），本轮自动跳过，不会叠跑。
- **两个开关**（页面「服务器直连抓我方价」/「服务器直连抓千岛」）控制服务器能否自己
  抓这两个外部数据源。任一关掉或抓取持续失败时，数据回退为库里上一份快照，
  并可用本机的 `6_推送数据到在线看板.bat` 手动补。
