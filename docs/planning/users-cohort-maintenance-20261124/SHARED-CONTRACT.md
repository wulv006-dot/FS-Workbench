# 共享口径合同

一期（用户分析）和二期（客户维护）共用以下定义。任何一期需要改这些定义，先改本文件并单独合并，不在各自 PR 里各改一份。所有时间按 `Asia/Shanghai`。

## 1. 有效订单

直接使用现行用户分析投影 `user_store.py::_normalize_orders` 产出的 `valid=1`，不另写判定：

- `pay_status=1`；`pay_status=2`（含部分退款）不算有效（`refund_policy`）。
- 排除 `excluded_order_statuses`（22、111、191）和已核测试单。
- 范围为 MMOEXP 主站 site 266。
- 金额为 Admin 整单 `amount_usd`，不跨游戏拆分。金额缺失的订单仍按有效单参与复购判定，金额汇总处标「含 N 笔金额未知」，不补零。

两期都读取用户分析私有库里的同一份订单投影，不再各自从 ES 或 Admin 重算有效性。

## 2. 新客 / 老客

客户在全部游戏范围内（站内）第一笔有效订单上的 ES「是否新客户」标记：是 = 新客，否 = 老客；缺失、未匹配或冲突 = 待核，不并入新客或老客。同一付款时刻有多笔时按 `(paid_at, order_key)` 升序取第一笔。

## 3. 复购

`paid_at − 首单 paid_at ≥ 24 小时` 的另一笔不同有效订单。24 小时内的追加单不算复购，也不重置首单。一单多商品只算一单。

## 4. 游戏范围

- 「全部」：首单是站内首单；复购是任意游戏的有效订单。
- 指定游戏 G：首单仍是站内首单（第 2 节），且必须含 G，否则该客户不进 G 的队列；复购是之后含 G 的有效订单。
- 本期不做「游戏内首购（站内老客第一次买 G）」口径。

## 5. 阶段

**单位**：「全部」范围按客户；指定游戏 G 按「客户 × G」，末购取含 G 的最后一笔有效订单。

**观察日**：最近一个已完整关账的上海自然日（数据截止日）。天数 = 观察日日期 − 末购付款日期（上海日期差，整数）。

**阈值** `[A, C, L]`：

| 阶段 | 条件 |
|---|---|
| 近期 | 天数 < A |
| 沉默 | A ≤ 天数 < C |
| 流失 | C ≤ 天数 < L |
| 长期流失 | 天数 ≥ L |
| 待核 | 末购之后到观察日之间存在订单覆盖缺口 |

**配置**：每个游戏一套，用户分析页和客户维护共用。FC27（gid 1327）默认 `[14, 30, 60]`（替换旧 `fc-v1` 的 `[14, 30, 90]`）；其他游戏沿用 `user_config.json` 现有 policy 映射；「全部」范围固定用 `common-v1` `[30, 60, 90]`。

## 6. 价值档（客户维护用）

客户在游戏 G 的累计有效消费：含 G 的全部有效订单整单 `amount_usd` 之和，历史起点为用户分析库 `history_backfill_start`（2026-01-01；FC27 实际数据自 2026-09-08 起）。金额未知的订单不计入累计，客户详情标「含 N 笔金额未知」。

| 档位 | 累计消费 |
|---|---|
| 超高价值 | ≥ $1,000 |
| 高价值 | $500 – $999.99 |
| 其他 | < $500，不进入阶段维护 |

依据：2026-09-08 至 11-23 FC27 共 14,389 人、累计约 $170 万。累计 ≥$1,000 的 155 人（占总消费 14.6%），≥$500 的 556 人（占 30.7%）。用户 2026-11-24 从「单笔最高金额」改为「累计消费」并确认上述门槛。

## 7. 客户身份

两期统一用用户分析现行身份 `exact-primary-email-v1`：一个已核 Admin 订单邮箱为一人，`customer_id` 为库内稳定 ID。订单上的 Admin `uid` 作为附加信息展示，不用于合并客户。发券收件邮箱即该邮箱（二期合同第「发券」节）。

## 8. 共享模块与配置

**代码**：`releases/fs-dashboard/customer-segments-20261124/source/customer_segments.py`，提供：

- `thresholds(gid | "all", config)`、`stage(last_paid_at, observation_date, gid | "all", config, covered)`：第 5 节。调用方须先把订单截断到观察日；末购晚于观察日时 `stage()` 报错。
- `tier(cumulative_usd, gid, config)`：第 6 节。
- `is_repeat(first_paid_at, paid_at)`：第 3 节。
- `load_config(path)`：读取并校验配置，返回 `(config, version, source)`。
- `write_config(path, config, expected_version)`：新版本必须恰好为 `expected_version + 1`，当前版本不符抛 `ConfigVersionConflict`；替换已完成但落盘确认失败时抛 `ConfigCommitUnknown`，调用方用 `load_config` 读回核对版本与内容后再决定是否重试。

**部署位置**：与用户分析、客户追踪同一运行目录 `/opt/fs-hermes-fc/customer_segments.py`（两者现均从该目录导入）。由共享 PR 的发布单独装入，一期、二期的发布清单只引用、不再携带该文件。

**配置文件**：`/var/lib/fs-customer-segments/segments.json`，字段 `version`、`stages`（gid → `[A,C,L]`）、`tiers`（gid → `{ultra, high}`）。版本 0 专指模块内置默认值，不能出现在文件中；文件版本从 1 开始单调递增。首次写入时把内置默认值归档为 `history/0.json`。目录 `/var/lib/fs-customer-segments`（权限 0700）在共享模块部署时预建。

- 写入方：只有二期客户维护页的管理员设置；写入为「临时文件 + fsync + rename」原子替换，旧版本另存 `history/<version>.json`。
- 读取方：每次查询或每日运行开始时读取一次，并把 `version` 写进结果和快照；同一快照内不换版本。
- 文件缺失时使用模块内默认值（即本文件第 5、6 节），结果标 `config_source=default`。

**施工顺序**：本合同定稿后，先在本分支实现该模块、默认配置和单测并合并、发布；两期 Worktree 从合并后的 `main` 拉出。
