# 客户分层共享模块

用户分析和客户维护共用此模块计算客户阶段、累计消费价值档和首单后 24 小时复购。计算规则见[共享口径合同](../../../docs/planning/users-cohort-maintenance-20261124/SHARED-CONTRACT.md)。

共享源码的部署目标为 `/opt/fs-hermes-fc/customer_segments.py`。部署时预建配置目录 `/var/lib/fs-customer-segments`，权限设为 `0700`。活动配置文件为该目录下的 `segments.json`。

- 阶段按上海自然日计算。已知末购付款的上海日期晚于观察日时会抛出 `ValueError`。
- 调用方先排除金额未知的订单，统计未知笔数，再把已知金额的累计值传给 `tier`。默认门槛为 $500（高价值）和 $1,000（超高价值），恰好达到门槛即进入相应价值档。
- 配置包含 `version`、`stages` 和 `tiers`，两个映射均按游戏 ID 字符串设置覆盖值。未配置的游戏和档位使用内置默认值，「全部」固定使用 30/60/90 天。金额门槛支持 JSON 数字或十进制字符串。
- 每次查询或每日运行开始时调用一次 `load_config(path)`。文件缺失时返回内置配置、版本 `0` 和来源 `default`。活动配置文件的版本必须为整数且至少为 `1`，有效文件的来源为 `file`。小数金额以十进制字符串保留精度。
- `write_config(path, config, expected_version)` 要求 `config["version"] == expected_version + 1`。活动版本与 `expected_version` 不一致时抛出 `ConfigVersionConflict`，调用方重新读取配置后再决定是否提交。首次写入用 `expected_version=0` 提交版本 `1`，并归档内置配置到 `history/0.json`。以后每次先归档活动版本到 `history/<version>.json`，再原子替换活动配置。归档已存在且内容一致时，可重试原写入。
- 活动文件替换成功后，若目录同步失败，`write_config` 抛出 `ConfigCommitUnknown`，其 `.version` 为提交的新版本。调用方先用 `load_config` 读回，核对版本及完整内容。按读回格式比较，阶段阈值使用列表，金额小数使用等值的十进制表示。一致时可确认新配置当前可读，落盘状态仍未知。读回原版本且内容一致时，可重试同一写入。读到其他版本、不同内容或读回失败时，先核对现状再决定。
