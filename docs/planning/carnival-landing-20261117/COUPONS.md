# MMOEXP 狂欢盛典：优惠券记录

建立日期：2026-11-17。按用户当天确认的清单，用用户本人的 Admin 会话（admin.p2pah.cn，「营销 → 优惠券」）创建，每张都已在 Admin 列表读回核对。

## 通用设置（所有券相同）

| 字段 | 值 |
|---|---|
| 站点 | 266（www.mmoexp.com） |
| 券类别 / 场景 | 1 / 3（活动页领取） |
| 场景业务码 `param_code` | `carnival_202611` |
| 状态 | 开启 |
| 全站总量 `limit_qty` | 0（不限） |
| 可与折扣码叠加 `is_open` | 否 |
| 备注 | Carnival 2026 FS landing page (authorized 2026-11-17) |

时间都是 Admin 的北京时间（GMT+8）。换算：ET 11/19 00:00 = 北京 11/19 13:00；ET 12/2 00:00 = 北京 12/2 13:00。

折扣模式：百分比券 `mode_type=2`，`reduce` 是折后比例（90 = 九折 = 10% OFF）；固定减免券 `mode_type=1`，`attain` 是门槛，`reduce` 是减免金额（美元）。

## ① 首页券（1 张）

| ID | 标题 | 优惠 | 适用范围 | 每人限领 | 有效期 | 槽位 |
|---|---|---|---|---|---|---|
| 1399 | Carnival 10% OFF All Games | 10% OFF，无门槛，不封顶 | 全部游戏 | 1 | 11/19 13:00 – 12/2 13:00 | `carnival_home` |

## ② 神秘商店券（6 套 × 3 档 = 18 张）

每人领取次数不限（`repeat_qty=0`，2026-11-17 用户要求取消原来的 3 次上限并已在 Admin 读回）：付款校验解锁后可以继续抽、继续领。有效期 11/19 13:00 – 12/2 13:00，无门槛，不封顶。

| ID | 标题 | 优惠 | 适用范围 | 槽位 |
|---|---|---|---|---|
| 1401 | Carnival Mystery FC 27 8% OFF | 8% | FC 27（游戏 1327） | `ms_fc27` |
| 1403 | Carnival Mystery FC 27 10% OFF | 10% | FC 27（1327） | `ms_fc27` |
| 1405 | Carnival Mystery FC 27 15% OFF | 15% | FC 27（1327） | `ms_fc27` |
| 1407 | Carnival Mystery AION 2 8% OFF | 8% | AION 2（891） | `ms_aion2` |
| 1409 | Carnival Mystery AION 2 10% OFF | 10% | AION 2（891） | `ms_aion2` |
| 1411 | Carnival Mystery AION 2 15% OFF | 15% | AION 2（891） | `ms_aion2` |
| 1413 | Carnival Mystery WoW Forever 8% OFF | 8% | WoW Forever（1367） | `ms_wow` |
| 1415 | Carnival Mystery WoW Forever 10% OFF | 10% | WoW Forever（1367） | `ms_wow` |
| 1417 | Carnival Mystery WoW Forever 15% OFF | 15% | WoW Forever（1367） | `ms_wow` |
| 1419 | Carnival Mystery Diablo 4 8% OFF | 8% | Diablo 4（456） | `ms_d4` |
| 1421 | Carnival Mystery Diablo 4 10% OFF | 10% | Diablo 4（456） | `ms_d4` |
| 1423 | Carnival Mystery Diablo 4 15% OFF | 15% | Diablo 4（456） | `ms_d4` |
| 1425 | Carnival Mystery POE 1 & POE 2 8% OFF | 8% | POE 1（157）+ POE 2（552），多游戏绑定 | `ms_poe` |
| 1427 | Carnival Mystery POE 1 & POE 2 10% OFF | 10% | POE 1 + POE 2 | `ms_poe` |
| 1429 | Carnival Mystery POE 1 & POE 2 15% OFF | 15% | POE 1 + POE 2 | `ms_poe` |
| 1431 | Carnival Mystery MapleStory CW, ARC Raiders & COD MW4 8% OFF | 8% | MapleStory CW（1333）+ ARC Raiders（925）+ COD MW4（1335），多游戏绑定 | `ms_mix` |
| 1433 | Carnival Mystery MapleStory CW, ARC Raiders & COD MW4 10% OFF | 10% | 同上 | `ms_mix` |
| 1435 | Carnival Mystery MapleStory CW, ARC Raiders & COD MW4 15% OFF | 15% | 同上 | `ms_mix` |

多游戏绑定按 Admin 规则：订单里所有商品都要属于绑定的游戏，券才可用。

## ③ 黑五商品券（8 张在用）

领取后 1 天有效（相对时效），每人每张最多领 10 次（每场一次），无门槛，不封顶。券绑商品不绑数量（例如 FC 1000K 的券买 2000K 也能用），不分平台。槽位都是 `bf_items`。

| ID | 标题 | 优惠 | 绑定 |
|---|---|---|---|
| 1513 | Carnival Black Friday FC 27 1000K Coins 18% OFF | 18% | FC 27 货币类 → 子类目 9623（金币），PS/Xbox/PC 通用 |
| 1443 | Carnival Black Friday WoW Forever 10G Gold 20% OFF | 20% | WoW Forever 货币类 → 子类目 9991（金币），不限服务器 |
| 1445 | Carnival Black Friday ARC Raiders 500K Coins 18% OFF | 18% | 商品 105267633（ARC Raiders Coins） |
| 1447 | Carnival Black Friday MapleStory CW 1000K Mesos 20% OFF | 20% | 商品 165167189（MapleStory CW Mesos） |
| 1515 | Carnival Black Friday FC 27 Lamine Yamal 20% OFF | 20% | FC 27 物品类 → 子类目 9627（球员），PS/Xbox/PC 通用；注意所有球员都能用 |
| 1455 | Carnival Black Friday MapleStory Gloves Attack Scroll 20% OFF | 20% | 商品 186209371（Gloves Attack Scroll: Intermediate） |
| 1457 | Carnival Black Friday POE 2 Divine Orb 1000+500 18% OFF | 18% | 商品 186208657（Divine Orb 1000+500 Free） |
| 1459 | Carnival Black Friday Diablo 4 Resplendent Spark x100 20% OFF | 20% | 商品 170070065（Resplendent Spark x100） |

**已作废（2026-11-17 用户要求不分平台）**：1437/1439/1441（FC 金币 PS/Xbox/PC）、1449/1451/1453（Yamal PS/Xbox/PC）已关闭（状态=关闭，领取数 0），并移出 `bf_items` 槽位。

## ④ 黑五满减券（5 天 × 4 档 = 20 张）

全部游戏，每人每张最多领 2 次（每天两场各一次）。有效期是当天 00:00 ET 到 23:59:59 ET（北京当天 13:00 到次日 12:59:59）。

| 日期（ET） | 满 $60 减 $5 | 满 $100 减 $8 | 满 $150 减 $12 | 满 $250 减 $20 | 槽位 |
|---|---|---|---|---|---|
| 11/27 | 1461 | 1463 | 1465 | 1467 | `bf_vouchers_1127` |
| 11/28 | 1469 | 1471 | 1473 | 1475 | `bf_vouchers_1128` |
| 11/29 | 1477 | 1479 | 1481 | 1483 | `bf_vouchers_1129` |
| 11/30 | 1485 | 1487 | 1489 | 1491 | `bf_vouchers_1130` |
| 12/1 | 1493 | 1495 | 1497 | 1499 | `bf_vouchers_1201` |

标题格式：`Carnival Black Friday <月-日> $<减> OFF $<满>+`，例如 1461 = `Carnival Black Friday 11-27 $5 OFF $60+`。

## ⑤ 扭蛋券（6 张）

无门槛，全部游戏，每人限领 1 次，有效期 11/19 13:00 – 12/2 13:00。按累计实付档位顺序发放。

| 顺位 | 累计实付达到 | ID | 标题 | 优惠 |
|---|---|---|---|---|
| 1 | $1 | 1501 | Carnival Capsule $1 Coupon | 减 $1 |
| 2 | $100 | 1503 | Carnival Capsule $5 Coupon | 减 $5 |
| 3 | $300 | 1505 | Carnival Capsule $12 Coupon | 减 $12 |
| 4 | $500 | 1507 | Carnival Capsule $18 Coupon | 减 $18 |
| 5 | $800 | 1509 | Carnival Capsule $25 Coupon | 减 $25 |
| 6 | $1,000 | 1511 | Carnival Capsule $50 Coupon | 减 $50 |

## 沿用的旧券

| ID | 标题 | 说明 |
|---|---|---|
| 1395 | FC27 Event 10% Coupon | FC 三个活动页的统一券，槽位 `fc_weekly`、`fc_sbc`、`fc_trio`，本次不改 |

## 配置状态（截至 2026-11-17）

- **券**：共建 59 张（1399–1515，ID 按 2 递增），53 张在用，6 张分平台的黑五券已关闭。
- **狂欢节配置（TempActivity，`code=carnival`）已保存并读回**（用户授权）：
  - 槽位：原有 `fc_weekly`/`fc_sbc`/`fc_trio` → 1395 不变；新增 13 个槽位（共 16 个），见上面各表「槽位」列。`bf_items` = [1513,1443,1445,1447,1515,1455,1457,1459]。
  - 消费档位：`[1,100,300,500,800,1000]`（原 `[1,10,50,100,500,1000]`）。
  - 档位配券：`[1501,1503,1505,1507,1509,1511]`，与档位一一对应（Admin 要求两者数量一致，否则整份配置不能保存）。
  - 开始和结束时间仍是 11/15 00:00 – 12/2 00:00，按确认在 11/19 北京 13:00 前再改成 11/19 13:00 – 12/2 13:00。
- **5 个游戏专属码已改结束时间并读回**：开始 11/19 00:00 不变，结束改为 12/2 13:00；都开启、都是 10% OFF。

| 码 | ID | 适用游戏 ID | 开始 | 结束 |
|---|---|---|---|---|
| VZKZT | 6319 | 1307 | 2026-11-19 00:00 | 2026-12-02 13:00 |
| TFLNV9 | 6321 | 1309 | 2026-11-19 00:00 | 2026-12-02 13:00 |
| KSPX1 | 6323 | 927 | 2026-11-19 00:00 | 2026-12-02 13:00 |
| RYQ3F | 6325 | 897 | 2026-11-19 00:00 | 2026-12-02 13:00 |
| YHCAKJ | 6327 | 743 | 2026-11-19 00:00 | 2026-12-02 13:00 |

## 主站读回（2026-11-17，`/ajax/carnival/coupon`）

- `fc_weekly`：1395 可领，FC 三页不受影响。
- 绝对时效的券（首页券、神秘商店、满减券、扭蛋券）在开始时间之前显示 `unavailable`，到点才能领。
- **`bf_items` 的 8 张商品券是「领取后 1 天」的相对时效，现在就显示可领**。页面上要到 11/27 场次开始才露出入口，但知道槽位名的人可以直接调接口提前领。用户 2026-11-17 决定保持开着，不提前关闭。
