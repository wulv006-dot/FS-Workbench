# WOW FOREVER 频道机器人（Blingtron-9000）

Discord 机器人，服务 `WOW FOREVER [MMO]` 服务器（guild `1567427533685657630`），
2026-11-07 接入并上线。单进程、按频道绑功能，部署在 play187。

## 模块

| 模块 | 优先级 | 职责 |
|---|---|---|
| `guard` | 10 | 前缀冒充 / 竞品关键词封禁（品牌 MMOEXP / U4GM / IGGM / LOOTBAR），**优先级最高且可短路** |
| `priceboard` | 20 | `🪙│gold-price` 金币看板：读 183 改价系统台账，单条消息原位刷新，大区/模式下拉 |
| `tickets` | 30 | 工单（未启用） |
| `welcome` | 40 | 四级身份组自选（Region → Faction → Ruleset → Class）+ 入群欢迎 |
| `giveaway` | 50 | `🎁│giveaway` 老虎机：背包弹窗登记 / 优惠券发码，带库存与次数上限 |

## 目录

```
src/                机器人本体
  bot.py            入口：模块注册、事件路由、custom_id 前缀分派
  config.json       频道别名、功能开关、奖池、品牌表（**无凭据**）
  modules/          各功能模块 + base.py 契约
  lib/store.py      state.json 读写（原子写）
deploy/             systemd 单元、同步脚本、台账导出脚本
*.py               运维脚本（建频道 / 发守则 / 清理消息 / 离线自检等，均可单独运行）
```

## 部署

见 **`README_部署.md`**（含服务器路径、systemd、数据链路、回滚点、踩过的坑）。
接入过程与权限核验见 **`README_交接.md`**。

## 关键约束（改代码前必读）

1. **`custom_id` 第 2 段是路由键**，不一定是模块名 —— `wf:role:*` / `wf:price:*` 是历史短名，
   靠 `bot.py` 的 `MODULE_ALIAS` 映射。新增模块请直接用 `wf:<真实模块名>:*`。
2. **`bot.on_interaction` 里不认识的自定义 id 必须直接 return**，绝不能 `response.send_message`
   —— 抢答会让 View 的 `edit_message` 抛 `InteractionResponded`，面板永远刷不动。
3. **`##` / `-#` 只在 embed `description` 里生效**，写进 field 值会原样显示成字面量。
4. **金额单位是「每 1 金」**，不做任何除算；文案单位收在 `config.features.priceboard.unit_label`。
5. **面向用户的文案一律英文**，`_check_no_cjk.py` 可全量复核。
6. 凭据只走 `secrets/token.txt`（服务器）与 `_local_secrets_DO_NOT_COMMIT/`（本机），
   两者都已 gitignore。**永远不要写进 config.json 或代码。**

## 奖池管理（2026-11-07）

在 `config.json` 的 `features.giveaway.admin_users` 配置允许管理奖池的 Discord 用户 ID。
只读取此名单，不把无限抽奖白名单或普通服务器管理员自动提升为奖池管理员。
管理员私聊机器人：

- `!奖池`：查看库存与帮助。
- `!奖池 重置`：恢复配置中的默认数量（当前 10 格包 10 个、8 格包 50 个）。
- `!奖池 重置 20 60`：按配置中限量奖品顺序，设置为 20 个、60 个。允许 0–100000 的整数。
- 同时支持 `!pool` 和 `!pool reset`。

重置只改库存和本轮库存上限，自动刷新公开面板；每人抽奖次数、冷却、中奖、优惠券、
待登记和发货记录保留。变更写入 `giveaway_stock_resets`，重启后库存保持。
上线本功能不会自动补充库存。普通群内消息不能重置奖池。

界面使用单卡按背包/券分组，卷轴先滚动，再依次停下并显示真实奖品。
中奖结果与登记按钮合并到同一条私密消息，保留持久化登记入口；同人动画中重复点击会被拦截。

## 离线自检

以下脚本都不发网络请求，可直接跑：

```bash
python _guard_test.py              # 守卫分类器语料（112 条）
python _welcome_check.py           # 四级菜单逐级解锁
python _pending_check.py           # 背包待登记队列
python _giveaway_rules_check.py    # 次数上限 / 库存 / 固定码 / 面板结构
python -m unittest -v test_giveaway  # 私聊权限、库存持久化、路由、动画与连点
```

服务器上另有 `selftest.py`（需连 Discord，校验角色可分配性与配置一致性）。
