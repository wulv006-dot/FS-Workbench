# MMOEXP FC27 Community

MMOEXP 独立 FC27 Discord 应用的维护源码。机器人运行在 187；FS `/bots/fc27.html` 是独立控制台；183 仅承担固定公开来源新闻采集。此仓库不保存生产配置、Token、用户数据或发布账本，Git 合并不触发自动部署。

已实现内容包括分类私密报价、EasySBC 更新后的分类入口、金币五档报价、俱乐部身份和新闻采集/发布。报价使用网站实际折后售价，Boosting 展示起价；每次查询时间由 Discord 客户端按用户时区呈现。新闻默认每 6 小时检查、每轮自动最多 6 条、EA 优先、自动去重，187 失败可切 183；人工发布不限量且允许重复。

Player 首版已接入名字搜索、精选/推荐、标签、版本及平台选择和私密实时折后报价；是否开放由生产 `player_panel` 配置与实际验收决定。FS 的 Player 标签页可维护精选、允许标签和显式 EasySBC ID/角色/页面映射；EasySBC 模板配置只保存意图，不自动调用第三方 slash 命令。`binding.py` 仍是独立候选，真实客户订单查询尚未接入。

## 维护入口

- [来源、运行路径与回灌范围](docs/SOURCE-MAP-20261108.md)
- [新闻中心运行说明](docs/NEWS-CENTER-20261108.md)
- [183 固定来源采集部署](deploy/NEWS-COLLECTOR-183.md)
- [报价过期与刷新](docs/QUOTE-EXPIRY-20261108.md)
- [欢迎页、俱乐部和提醒验收](docs/COMMUNITY-UX-RELEASE-20261108.md)
- [全游戏 Start Here 引导入口](docs/START-HERE-GATEWAY-20261108.md)
- [Player 适配器接口与未验范围](docs/PLAYER-CATALOG-DEVELOPMENT.md)
- [采集结果导入合同](docs/FUT-COLLECTION-CONTRACT.md)

其他按日期命名的记录只证明对应时点；生产状态应核实服务、活动源码和真实入口。`ops/` 中一次性脚本含固定路径/基线哈希，不能当作通用重复发布命令。

## 离线检查

在独立 Python 环境安装 `requirements.txt`，从仓库根目录运行：

```sh
python -I -B opt/mmoexp-fc-community/ci_check.py
```

此入口运行本模块测试并检查 quotes / 183 worker 镜像一致，不连接外部服务。Linux 不执行 Windows Token 保存辅助测试。FS 控制台测试在 `opt/bot-console` 运行 `python -m unittest test_fc_console -v`。CI 不代替 Discord UI 或生产 API 验收。

首次安装参考示例和部署说明；已有实例只按核验后的文件清单增量部署，保留 `var/` 的消息 ID、去重、订阅和活动记录。不要覆盖真实 `content.config.json` 或恢复旧整包数据库。

## Player 发布边界

- 社区机器人需要 `player_panel.py`、`player_service.py`、`player_catalog.py`、`player_config.py`；报价服务独立目录需要后面三个模块及新版 `quote_bridge.py`。镜像由 CI 检查。
- `player_panel` 配置含 `enabled`、`guild_id`、`channel_id`、`featured_model_ids`、`allowed_tag_ids`、`verified_prices`，可选 `easysbc`。部署者安装已核实的群/频道和逐模型平台核价映射；FS 页面不能修改这些路由或核价范围。
- 精选列表为空时读取 Admin 推荐标记；名称只筛选候选，不替代卡版本 ID。只允许经核价的平台展示 Goods.price；异常、下架及库存合同不符时不报价。
- Player 维护的标签使用已修复 `GoodsTag/index`。保留 `player-panel.json` 消息记录；跨群迁移时应明确核对记录和目标频道，避免重复公开入口。
