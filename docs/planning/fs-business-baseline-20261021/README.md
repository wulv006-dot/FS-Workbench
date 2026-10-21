# 业务基准修订与工具接入

当前业务入口：[BUSINESS-BASELINE.md](BUSINESS-BASELINE.md)。旧版本只作历史追溯，不用于新判断。

本批代码维护源 `fs_business_baseline_20261021/`，基于当前活动源码逐文件核对，保留Hermes V2、客户生命周期、多游戏查询、UI和原发布器修复。代码已受控发布并通过真实入口读回；分析能力仅局部通过，收益未验证。分层回执见[DELIVERY.md](DELIVERY.md)，Astra参考见[ASTRA-REFERENCE.md](ASTRA-REFERENCE.md)，剩余见[REMAINING.md](REMAINING.md)。

本批直接变更：

- 在原折扣查询、数据工具原细分控件及 Hermes schema 中增加折扣码推广渠道；373 条映射，来源与站点不覆盖。重用原私有 ES 文件集，字段缺失不当无码，不新增导出、登录、采集器或定时器。
- 新业务基准替代新FS任务中旧Desktop业务长文、旧MEMORY及reviewed-business-20261015旧规则输入。用户偏好、现行报告方法、原纠错方法、正式经验和旧任务证据保留。实际模型输入已验证含当前基准、排除冲突旧业务输入；这一步不等于能力提升。
- 客户候选/订单历史增加现有 Order 精确单号全状态的只读复核链接，不自动访问或改订单，不把供应商关键词当客户邮箱。
- 原定价模拟返回独立 .99 尾价预览：根据报价、交付成本、原底线计算可让利预算，保留 PS/XBOX 联动。预览不改原基线或候选结果、不调用 writer；套餐总价与每 K 参数分开。真实效果尚未验证。
- 复用现有样式、布局和主题，只新增细分选项、解释与复核链接。流量页 GA4/GSC/Ads 的结构及原代码不改。

原部署器的锁、CAS、admission/provider fence、备份与回退继续使用，本批 16 精确目标、8 个新文件，其余活动对象保留保护 SHA。Nginx 仅三个目标 alias 与一个同身份静态资产入口定点调整，原路由保留。Admin 会话容器与认证配置不在发布范围。

定向检查：`python fs_business_baseline_20261021/test_baseline.py`；该组登记到私库现有 `tools/pr_fast.py`，不新增 workflow。货币/零值/缺失/去重、映射隐私、旧档重用、知识替代、尾价预算、权限/调度边界与 Nginx 身份保持均有检查；JS 语法另验，真实浅暗/键盘与后台使用单列。

访问缺口：原Admin会话曾credentials_rejected/503，后续运维改为single-owner并保持冷却停服。本Work保留新unit，最后只读状态inactive；最新项目HANDOFF给出的最早另行考虑验证点为2026-10-22 11:30上海时间，不是解封保证。本批不启动、登录、自动重试或修改凭据。浏览器现有登录态已用于口径核验，已有原导出用于真实渠道查询；新鲜数据恢复另验。

Astra在上述基准、资源和工具核验后完成一次独立参考并结束。本Work随后教学Hermes，实际复盘、人工发布方法和新会话使用均有回执；留出仍有组合约束、利润定义和反证错误，不宣称全面学会。最终[Notion完整修订版](https://app.notion.com/p/3ff9a8a79c4e81bc8a4feb15aab87a5a)及三处关联页已更新读回，冲突旧正文已移除、废弃清单生效，历史证据保留，见[NOTION-SYNC.json](NOTION-SYNC.json)。
