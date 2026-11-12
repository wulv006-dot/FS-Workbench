# MMOEXP Lucky Loot

Official Club 专项活动机器人，独立服务与加密数据。管理入口：https://47.85.224.112/bots/giveaway.html 。

## 运营使用

新建活动默认“一键报名＋机器人播报”。填写活动文案、发布/报名截止/开奖时间、人群、奖品和数量；播报文案支持 `{user}`、`{activity}`，播报频道可单独指定。预览活动、中奖卡与播报后保存草稿，再定时发布。发布后规则锁定，复制可创建下一场。

机器人发送播报，成员账号不自动发言。重复点击不会重复报名或播报。主卡只保留短文案、奖品、时间和按钮；Rules 私密展示资格、券限制，Privacy 跳转公开说明。按钮＋聊天、聊天和口令模式仍可选，默认一键模式不显示无关的聊天设置。

测试开关严格限定管理员及 🧪・lucky-loot-test，正式活动须主动关闭测试、指定正式频道和人群。自动置顶需要该频道的 Pin Messages 权限；不需要 Administrator 或 Manage Messages。现只给新机器人在私密测试频道补了 Pin Messages。

中奖者从 Claim reward 私密提交 MMOEXP 邮箱，优惠券通过原 chenchaoapi HMAC 代理发放至 site266。券1365实际为 $5、无最低消费、游戏1367、每邮箱一次、30天；不是全游戏券。后台待注册、限领、失败、未知分别记录，未知不重新发送。其他奖励由管理员查看私密领取邮箱后人工交付。

## 运维

- 187 服务：`mmoexp-lucky-loot.service`；源码 `/opt/mmoexp-lucky-loot`；Node18.20.8 `/usr/local/bin/node`。
- Token `/etc/mmoexp-lucky-loot/token`，加密密钥 `/etc/mmoexp-lucky-loot/data.key`；仅服务器。状态 `/var/lib/mmoexp-lucky-loot/state.enc`，AES256GCM。
- Unix控制接口 `/run/mmoexp-lucky-loot/control.sock`0600；bot-console 的管理员验证与CSRF在 `lucky_proxy.py` 执行，无新增公开API端口。
- 活动调度每10秒，报名播报队列约每1.1秒一条，留存清理每小时。无需本机运行或额外Codex定时任务。
- 活动记录于领奖期限后30天清理；聊天正文不存储；`/privacy-delete`本人确认删除此机器人本地记录。外部发券记录和Discord已发消息不随本地删除。
- 收件邮箱不会从活动列表或普通状态接口返回。人工奖品仅通过管理员POST recipient按单次记录查看。

## 版本与回退

v1.1改版回退：`/opt/python39/bin/python3.9 /opt/mmoexp-lucky-loot-release-20261112-v11/release_v11.py rollback`。校验文件未漂移后恢复代码，保持当前状态/密钥/Token和领奖记录。

全部新模块退出：`/opt/python39/bin/python3.9 /opt/mmoexp-lucky-loot-release-20261112/release.py rollback`，停止新机器人、移开enabled标记、恢复原console/nginx三文件；同样保留状态。旧原版备份含WB当天Guard控制台修复；不得用Git旧版server整文件覆盖线上。

置顶权限变更回执：v1.1发布目录 `pin-permission.json`。需要撤回时仅恢复其中指定bot/member overwrite的before值；不覆盖整个频道权限，不移除管理员可见限制。

离线检查：`npm ci --ignore-scripts && npm test`；`python3 -m unittest discover -s test -p test_proxy.py`。31个Node行为用例＋6个权限用例通过。Git的pr-fast沿用现有workflow，只为此模块准备已锁定依赖与映射，不建立新workflow。
