# IGGM 外部生产者定位（2026-10-23）

截至北京时间 15:37:52，已按用户授权在原飞书群单次精确 @ 大超的 WorkBuddy，询问实际运行脚本、GitHub备份、调度、HTTP方式和新鲜度证据。消息已经送达并读回原生 @；尚未取得对方回复，不能把服务器组件当作本机实际生产者，也不能宣布 FC 可直接复用。

用户已明确生产者在 chenchao/大超电脑、由其 WorkBuddy 维护；这是用户提供的定位，尚未由本任务核实该电脑上的进程或文件。本任务不连接其电脑、不索取凭据、不启动任何采集或挑战测试。

## 已查 GitHub 与本地资料

核查 [FS-Workbench](https://github.com/wulv006-dot/FS-Workbench/tree/7eeb8320f925fd694d1f363aaba7fab8a75dc16c) 的不可变提交 `7eeb8320f925fd694d1f363aaba7fab8a75dc16c`，递归树 5580 项、truncated=false；并搜索 `iggm_push`、`iggm_local_push`、`iggm_gold_push` 及本机 IGGM 相关条目。发现的是：

| 精确路径 | 能证明的用途 | 不能据此认定 |
|---|---|---|
| [opt/d4follow/app.py](https://github.com/wulv006-dot/FS-Workbench/blob/7eeb8320f925fd694d1f363aaba7fab8a75dc16c/opt/d4follow/app.py) | POST `/api/iggm_push` 接收；70 分钟近期推送则跳过服务器自抓 | 谁在大超电脑运行、如何新抓、实际计划任务 |
| [opt/d4follow/core_iggm.py](https://github.com/wulv006-dot/FS-Workbench/blob/7eeb8320f925fd694d1f363aaba7fab8a75dc16c/opt/d4follow/core_iggm.py) | 普通 urllib/CookieJar 及商品 AJAX 读取组件；已有多游戏参数和折算逻辑 | 本机生产者是否用了这个版本、服务器现在可访问 IGGM |
| [opt/d4follow/core_gold.py](https://github.com/wulv006-dot/FS-Workbench/blob/7eeb8320f925fd694d1f363aaba7fab8a75dc16c/opt/d4follow/core_gold.py) | 金币读取组件与外部推送消费，3 小时有效窗 | 本机本次实际新请求成功 |
| [opt/d4follow/push_data.py](https://github.com/wulv006-dot/FS-Workbench/blob/7eeb8320f925fd694d1f363aaba7fab8a75dc16c/opt/d4follow/push_data.py) | 千岛成本与我方前端价推送，POST `/api/cost`、`/api/our` | 不是已找到的 IGGM 生产者 |
| [opt/d4follow/README_auto_collect.md](https://github.com/wulv006-dot/FS-Workbench/blob/7eeb8320f925fd694d1f363aaba7fab8a75dc16c/opt/d4follow/README_auto_collect.md) | 历史服务器 timer/采集说明 | 不是本机 IGGM 活动计划，也不能据旧“两小时”说明重设当前周期 |

本地主工程相关历史副本和本次 `.agent_runtime/fc-iggm-recovery-20261023/core_iggm.py` 均为服务器组件证据。所查当前 main 树及已定位资料尚未找到实际本机生产入口；这不等于其不存在，也不排除在另一仓库、未合并分支或大超电脑独立目录。

原 RPG 子任务已只读检查现有 Nginx access.log 等指定范围，没有找到 `/api/iggm_push` 请求记录；本任务复用该结果，没有重复扫描或把空日志当作没有推送的证据。

## 原群单次询问与对账

- 查询编号：`IGGM-PRODUCER-20261023-01`。
- 使用现有 Hermes 飞书身份明确说明代当前 Codex 询问，不冒充大超或其 WorkBuddy。
- 原群：AI 协作，chat_id=`oc_b1964fbd9c2fad92825a30f601313d66`。
- 精确目标 open_id=`ou_851140c62fd564e2fef467669814b2e8`；当前 private-target 配置与旧真实绑定验收相同。发送前用官方 GET 读取原验收消息 `om_x100b6247a4bd9ca0ddff836dc267b6d`，此 ID 的 name 确为“大超的WorkBuddy”。没有使用另一个历史同名机器人 ID。
- 发送于 15:31:22，真实 message_id=`om_x100b62849a5dc0b8de6f330db464664`。官方 GET 读回原群和 post 原生 at，mentions.id 精确匹配。新 post 的 mentions.name 为空，第一次按名称断言未通过；随后按精确 ID 和已核验身份对账，不是漏 @，未重发。
- 回执位于 Hermes 原 profile `/profile/ops-watchdog/iggm-producer-query-20261023-01.json`；只保存本次询问/发送/读回状态，不改变巡检、调度或业务配置。
- 飞书历史列表 API 返回 HTTP400/code230027，缺 `im:message.group_msg`。本任务未改权限；仅查看原身份正常已接收的网关/原群消息记录，15:35 时未见相关回复。没有用空结果推断对方未收到或无法处理。
- 15:37:52 补核现行接收服务实际为 `hermes-dingtalk.service` 且 active，原 profile 网关日志持续更新；本查询之后相关入站日志及原群 role=user 的 IGGM 消息仍未见。一条 Hermes 自身工具结果列出了查询回执文件名，已排除该误命中，未当成 WorkBuddy 回复。

询问内容覆盖实际路径/启动器/计划、仓库和 commit、普通 HTTP 或浏览器、商品/接口/单位/币种、推送周期与缓存判据、最近一次新请求脱敏证据，以及是否支持 FC27 三平台和地区/出口差价。明确不要求新抓取、换代理或账号、重启、改计划、调价，也不索取密码、token、cookie 或会话。

## FC 复用的当前结论

普通 HTTP 传输、JSON 读取、连接关闭及已有数据接收等组件可以继续评估复用；当前尚未确认实际生产者代码与活动版本，不能直接接入 FC。IGGM 外部访问 403 仍未解除，本次没有再次访问 IGGM。

即使对方确认脚本可共享，FC 还须独立保留：PS/XBOX/PC 精确商品身份、100K 加赠送数量、USD/K 单位、真实源请求时间、报价与可见原价一致、原稳定读取及来源覆盖合同。RPG 的默认百万/每万单位、地区或机房折算系数、70分钟/3小时缓存不能直接套入 FC。收到来源与实际活动证据后再判断可用范围，不把备份存在当作生产成功或合法访问证明。
