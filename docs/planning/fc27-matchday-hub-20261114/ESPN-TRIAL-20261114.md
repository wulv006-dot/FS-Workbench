# ESPN 备用赛事源：隔离采集试验记录

状态：2026-11-14 **187 隔离采集已启用，每 6 小时只读检查；Discord 未发布 ESPN 赛况**。用户说明已取得 ESPN 负责人免费使用授权，书面授权函预计周一补充。后续对接时仍需核对正式接口、可展示字段、署名和更新频率。

## 已找到的接口与字段

公开足球记分板接口：

`GET https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates=YYYYMMDD`

试验联赛标识：`eng.1` 英超、`esp.1` 西甲、`ger.1` 德甲、`fra.1` 法甲、`uefa.champions` 欧冠。响应的 `events[]` 包含赛事 ID、UTC 开赛时间、主客队、比分、状态；`competitions[0].details[]` 含进球、红牌等字段（某类事件实际是否出现需逐场验证），有球员 ID、事件分钟与球队 ID。卡片只提取事实字段，不复制 ESPN 图片、文章或视频。

2026-11-14 本机单次 HTTP 只读测试：五个联赛接口均返回 200、JSON 可解析；当日五个联赛均无比赛。回放日期 2026-11-07，英超 4 场/8 个进球字段、西甲 4 场/8 个进球字段、德甲 5 场/18 个进球字段、法甲 2 场/2 个进球字段；欧冠 2026-11-03 为 9 场/26 个进球字段。一个双源对照样本：2026-11-07 Nottingham Forest 3–1 Manchester City，ESPN 赛事 `401878757`、OpenLigaDB 赛事 `86626`，开赛时间均为 17:30 UTC，终场比分一致。2026-11-21 Manchester City vs Fulham 的两个来源也都列出 12:30 UTC 的赛程。

REA 在独立 Chromium 会话对同一 ESPN 端点做了被动网络记录，得到 HTTP 403。187 首次运行也发现：`/usr/bin/python3` 指向 `/usr/local/python39`，缺少 `_ssl`；另一套 `/opt/python39` 可用 SSL。将后者同 ABI 的 `_ssl` 模块复制到前者的 `lib-dynload`，SHA256 一致，`import ssl` 和 OpenLigaDB HTTPS 请求均通过。没有更换 Python 入口或重启服务。

187 携带自定义 `MMOEXP-FC27-Matchday/0.1` 请求标识时，ESPN 返回 HTTP 403；按用户要求移除该自定义标识后，Python 默认请求和 curl 默认请求均为 HTTP 200，均读到 2,503 字节。隔离采集器使用 Python 默认请求。2026-11-14 21:58 CST，历史英超 2026-11-07 返回 4 场/8 个进球；当天英超、西甲、德甲、欧冠、法甲各返回 200/0 场；2026-11-21 英超返回 7 场未开赛/0 个进球。`fc27-espn-probe.service` 首次运行成功，`fc27-espn-probe.timer` 已启用，首次下一轮为 **2026-11-15 00:05 CST**，此后每天 00:05、06:05、12:05、18:05。

隔离目录为 `/opt/mmoexp-fc-matchday-probe-20261114`，状态日志为其中的 `probe.jsonl`。每条只记录检查时间、联赛、HTTP 状态、耗时、场次与事件计数。标准化赛事快照保存在 `snapshots/*.json`；2026-11-14 22:04 CST 首次通过 systemd 保存五个联赛快照，文件权限为 `0600`。不保存文章全文或玩家信息。暂停：`systemctl disable --now fc27-espn-probe.timer`；手动验收：`systemctl start fc27-espn-probe.service`，再看 `systemctl show fc27-espn-probe.service -p Result -p ExecMainStatus` 与日志末尾。服务器时间为 CST +0800，日志时间为 UTC。

## 已写代码与尚缺部分

- `opt/mmoexp-fc-community/matchday_espn.py`：固定联赛与日期的只读响应解析器；提取比分、状态、进球/红牌候选及来源链接。ESPN `details[]` 未提供稳定的事件 ID，离线解析器用赛事 ID + 类型 + 时间 + 球队/球员生成事件指纹，正式去重还须核验修正情形。
- `opt/mmoexp-fc-community/matchday_openligadb.py`：主源组别变更标记、赛程/进球字段标准化与来源署名。
- 三组直接相关的单元测试共 9 项通过。已有 187 隔离定时器和标准化快照；尚无 Discord 发布、FS 控制台开关或主备切换任务。

## 主备切换门槛

OpenLigaDB 为主，ESPN 为备用；仅对运营选中的焦点赛事绑定两方赛事 ID。绑定必须核对同一主客队、联赛、开赛时间（允许最多 15 分钟的供应商修订差）与历史比分，不能只按相似名称自动对应。主源超时/缺字段后，备用源连续两次读取一致且授权、访问均有效才切换；切换时不补发之前的进球，避免重复事件。两个来源互相矛盾时显示 `Updates delayed` 并通知运营，不自动以任一来源结算优惠券。切回主源也必须核对比分和事件账本。

## 周一要核对

1. 补充授权函，确认 Discord 群内展示、更新频率、合作方指定接口/请求头及署名要求。若有正式 Partner API，迁移到正式接口。
2. 反馈 187 带自定义采集标识返回 403、默认请求返回 200 的差异，并确认合作方期望的认证或客户端标识方式。
3. 选定一场真实在赛中的比赛，观察延迟、进球/红牌/VAR 更正及事件 ID 稳定性。2026-11-14 目标联赛没有比赛，不能宣称已验证实时性。
