# MMOEXP FC27 Community

MMOEXP 独立 FC27 Discord 应用的维护源码。机器人运行在 187；FS `/bots/fc27.html` 是独立控制台；183 仅承担固定公开来源新闻采集。此仓库不保存生产配置、Token、用户数据或发布账本，Git 合并不触发自动部署。

已实现内容包括分类私密报价、EasySBC 更新后的分类入口、金币五档报价、俱乐部身份和新闻采集/发布。报价使用网站实际折后售价，Boosting 展示起价；每次查询时间由 Discord 客户端按用户时区呈现。新闻默认每 6 小时检查、每轮自动最多 6 条、EA 优先、自动去重，187 失败可切 183；人工发布不限量且允许重复。

`player_catalog.py` 是待整合的只读技术模块，`binding.py` 是独立的绑定候选。真实客户订单查询尚未接入；不要把文件或单测存在等同于正式功能开放。

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
