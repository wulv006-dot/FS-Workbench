# FC27 内容机器人试用说明

当前为离线验证候选，尚未安装到 Discord 测试群或部署常驻服务。无需 MMOEXP 邮箱、Admin 或 EA 账号。活动会保存 Discord 用户ID、首次成功报名频道和时间，因此不是匿名系统。

## 已实现命令

| 命令 | 用途 |
|---|---|
| `/fc latest` | 最近 10 条已审核的 FC27 内容 |
| `/fc guide content_id` | 读取具体内容及来源、审核时间 |
| `/fc draft title kind body source` | 运营创建草稿；类型为 news/sbc/squad/guide |
| `/fc preview content_id` | 运营预览草稿与来源 |
| `/fc approve content_id` | 运营本人即可发布并开放查询 |
| `/fc withdraw content_id` | 撤回过时或错误内容 |
| `/fc event-create title capacity hours` | 运营创建报名活动；1–5000 名额，截止期最长90天 |
| `/fc events` | 查看最早截止的10个开放活动 |
| `/fc join event_id` | 自助报名，重复提交不重复占位 |
| `/fc leave event_id` | 自助取消并释放名额 |
| `/fc report event_id` | 运营查询首次成功报名频道的有效/取消人数 |

所有命令回复仅本人可见。内容“审核通过”表示进入查询目录，当前不会自动向公共频道推送。活动报名不包含抽奖、派奖、支付或自动发优惠码。

归因口径：同一活动/用户首次成功报名的频道固定；取消后重新报名保留该频道；报表为当前有效和当前取消的唯一用户数，不是累计点击、取消次数或网站订单转化。超过 Discord 文本长度的结果作为完整私密文本附件发送，不丢行。

## 本机验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe content_bot.py --check
.\.venv\Scripts\python.exe -m pip check
```

2026-11-06：25 项通过（原绑定12项＋本轮13项）；11个测试群命令注册的离线检查通过；依赖检查通过。新增适配器仅在 Windows Python 3.14 + discord.py 2.7.1 验证。本轮没有新增183上传测试；此前Linux通过的12项仅属于绑定核心。

## 启动前配置

1. 使用独立的新 Discord 应用，配置 Bot Token 到运行进程的 `DISCORD_BOT_TOKEN` 环境变量，不写入配置文件或聊天。
2. 安装仅到测试群 `1565922092518613064`。应用需有 bot、applications.commands 的相应安装权限；按测试频道需要授予查看频道、发送消息、嵌入链接和附件权限，不授予管理员权限。实际安装尚待操作及验证。
3. 复制 `content.config.example.json` 为 `content.config.json`，填写你本人的 Discord 用户ID（1237241595674361962）。用户ID不是身份组ID。本版显式用户白名单，配置变更后重启加载。
4. 在已完成配置的受控环境设置 `FC_ENABLE_LIVE=1`，运行 `python content_bot.py --config content.config.json`。启动会同步测试群命令，正式群ID在代码和配置校验中拒绝。未配置显式开关、Token 或运营本人ID时拒绝启动。

尚未创建新应用或改变 Discord 权限，也未读取旧 Token。提供新应用配置和运营本人ID后，下一步是测试群端到端验证：草稿→预览→本人发布→玩家查询、报名→重复报名→取消→报表。

## 运行边界

- 不申请 Presence、Members、Message Content 特权 Intent；仅开启 guilds。
- 每用户每30秒最多8次命令（单进程内存限频）；进程重启重置。不是面向5万人正式上线的负载验收。
- SQLite 是独立试点库；单进程、单测试群，不应多个进程共享作高流量服务。
- 当前没有活动改期/关闭命令、内容定时发布、数据库备份任务或自动清理策略；在正式灰度前补齐运营生命周期。
- 玩家可取消报名但不会删除历史ID；正式上线前确定保留期限和删除流程。
- 此候选在本地独立目录，尚未纳入 FS-Workbench 仓库提交或发布流程。
