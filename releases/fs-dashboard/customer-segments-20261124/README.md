# 客户分层共享模块

用户分析和客户维护共用此模块计算客户阶段、累计消费价值档和首单后 24 小时复购。计算规则见[共享口径合同](../../../docs/planning/users-cohort-maintenance-20261124/SHARED-CONTRACT.md)。

共享源码的部署目标为 `/opt/fs-hermes-fc/customer_segments.py`。运行时配置读取 `/var/lib/fs-customer-segments/segments.json`。

- 配置包含 `version`、`stages` 和 `tiers`，两个映射均按游戏 ID 字符串设置覆盖值。未配置的游戏和档位使用内置默认值，「全部」固定使用 30/60/90 天。金额门槛支持 JSON 数字或十进制字符串。
- 每次查询或每日运行开始时调用一次 `load_config`。文件缺失时返回版本 0 和来源 `default`，有效文件的来源为 `file`。小数金额以十进制字符串保留精度。
- 用读到的版本作为 `expected_version` 调用 `write_config`，新版本须加一。已有配置归档到同目录的 `history/<version>.json`，随后原子替换配置。版本冲突时重新读取配置。
