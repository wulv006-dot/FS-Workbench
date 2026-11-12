# MMOEXP Lucky Loot — 2026-11-12

负责人：GPT；用户陈超授权新独立机器人、Official Club、私密管理员测试、服务器部署和机器人管理入口。后续明确采用点击即报名、机器人公开播报定制文案；长说明移至规则/隐私按钮。没有代理用户账号发言。

## 已部署及验收

play187新服务 `mmoexp-lucky-loot.service`，应用1570345932699074611，guild1041923524601851914。管理页 `/bots/giveaway.html`，原机器人管理页有增量链接。

v1.0首轮真实活动：1人按钮报名并聊天合格，16:40自动开奖并发布中奖消息；用户为中奖人。原5美元券尚未领取，实际发券到账未验证，不能以模拟测试代替。

v1.1：31项Node测试和6项管理权限测试通过（Node18.20.8隔离运行，proxy测试6项实际执行）。真实网页完成预览、保存、确认及发布；用户点击后确认看到播报。API读回：新活动mode=button、合格/报名1/1，机器人公开播报1条、仅提及该报名成员；活动pinned=true；Rules按钮和Privacy链接存在；旧中奖卡已简化，原中奖记录仍unclaimed。

测试频道1570346273330954270只允许管理员和新机器人查看；除bot自身member overwrite新增Pin Messages外，其余权限逐项读回未变。不授予Administrator，不改普通成员的频道访问。正式活动尚未发布。新版交互演示明确标注不发奖。

## 源码与现场边界

独立开发目录 `D:/AI共享工作区/_giveaway_20261112/repo`，分支 `codex/lucky-loot-20261112`；原基线33a21638，提交前fetch最新main8f2a6dee。CodeGraph MCP在本会话不可用，使用实际源码/调用点检查，没有把索引当线上证据。

活动源码 `opt/mmoexp-lucky-loot/`；其中giveaway静态文件和lucky_proxy.py由发布器复制到bot-console。共享server仅新增route hook、index仅新增链接。现网WB 15:48的Guard加密读写桥改动保留在受控发布基线中，不将该他人变更并入本PR，也不从Git整文件覆盖现网server。

`tools/pr_fast.py`沿现有workflow注册core/cards/integration/proxy最小实际检查，新增按受影响目录npm ci。原bot及FC控制台检查由现有映射继续执行。Git合并/CI状态另附最终回执，不把部署等同合并。

## 回退与运行数据

新功能回退：187 `/opt/python39/bin/python3.9 /opt/mmoexp-lucky-loot-release-20261112-v11/release_v11.py rollback`；检查after散列，恢复code/static/proxy，不恢复或覆盖状态、Token、密钥、领奖和删除结果。

新模块整体退出：`/opt/python39/bin/python3.9 /opt/mmoexp-lucky-loot-release-20261112/release.py rollback`，恢复已备份的server/index/nginx增量前版本，停止新服务、移开enabled标记，保留运行数据。禁止从历史数据库恢复已删用户记录。

原发券代理8911，沿用chenchaoapi，不复制API secret。Token `/etc/mmoexp-lucky-loot/token`，AES256GCM key `/etc/mmoexp-lucky-loot/data.key`，状态 `/var/lib/mmoexp-lucky-loot/state.enc`；都不入Git。已核测试券1365实际受game1367限制、每邮箱1次、有效期30天。

发券持久化登记在外部POST之前；重复点击不重复发券；未知与重启在途转人工核对，沿原批次/jobID读取，不盲重发。频道只公开用户ID、奖品和活动信息，邮箱仅私密提交和授权管理员人工交付时按记录查看。
