# FC27 社区机器人源码回灌

本目录是 MMOEXP FC27 独立项目的维护源码入口。Git 合并不自动部署，不应把仓库示例配置覆盖生产配置。2026-11-08 的部署与实际入口验收见同目录新闻、报价、欢迎页记录；Player 和会员绑定模块仍是候选，不能据文件存在判断已上线。

| 仓库源 | 运行位置 / 消费者 | 状态与注意事项 |
| --- | --- | --- |
| `opt/mmoexp-fc-community/*.py` | 187 `/opt/mmoexp-fc-community/` | 社区、内容、新闻、报价 UI；`player_catalog.py`、`binding.py` 不代表生产接线 |
| `opt/mmoexp-fc-community/deploy/mmoexp-fc-community.service` | 187 systemd 单元 | 模板；活动单元及 drop-in 以现场为准，不整包覆盖 |
| `opt/mmoexp-fc-quotes/{quote_bridge,quote_catalog}.py` | 187 `/opt/mmoexp-fc-quotes/` | 受限只读 Unix socket 服务；community 中保留相同源码供客户端/测试使用，更新时两份保持一致 |
| `opt/fc27-news-fetch/worker.py` | 183 `/opt/fc27-news-fetch/worker.py` | 固定 EA / MMOEXP 公共来源采集；与 community 的 `deploy/news_collector_worker.py` 同源 |
| `opt/bot-console/server.py` | 187 `/opt/bot-console/server.py` | 原有机器人功能＋FC27 独立配置及新闻中心 |
| `opt/bot-console/static/{index,fc27}.html` | 187 `/opt/bot-console/static/` | `/bots/` 原入口和 `/bots/fc27.html` |
| `opt/bot-console/dashboard/modules/bots/index.html` | FS `/dashboard/modules/bots/` 页面源 | 独立保留页面源，现场文件绝对路径须部署前核对；不是 bot-console 静态路由 |

本轮只读核实 quotes 的活动 ExecStart：`/opt/mmoexp-fc-community/.venv-ssl/bin/python -B /opt/mmoexp-fc-quotes/quote_bridge.py --socket /run/mmoexp-fc-quotes/quotes.sock`。活动 bridge SHA-256 为 `3b7e392dd01c2f87dbb2e90c5dafdf7d166f7e52055cff4bc13631f851c623cc`，catalog 为 `4241ff40096480c794b6dd7d27c7581c33a5c1ef5b283a4d39092c8e42b11270`，均与本次源一致。该核验不代替后续价格实读，也不改变服务账号/权限。

## 回灌基线与共享代码

集成起点为远端 main `68655b4472dc7350e1e0701d3366aee7eebe5360`。原本地 FS-Workbench 克隆为 `4cdbac68e0c7297a541b15cea1a18ecfd6e1c755`；本次使用独立检出，不改 Harness 已有工作树。

Git 里的 bot-console 比本项目的线上基线旧：线上已有 2026-11-06 品牌表改造，涉及 `server.py`、`static/index.html`。FC 功能在该基线上增量开发；回灌保留这部分已存在的品牌代码，不能把旧 Git 版本盖回线上。此前基线至本次 main 这两个路径没有新提交；仍需在最终合并前刷新 base。

## 不入库

真实 `content.config.json`、`sources.json`、任何 Token/env/SSH 私钥、生产 SQLite、用户绑定/订阅数据、消息 marker、审计日志、缓存、venv、下载的整份第三方 JavaScript、截图和浏览器证据不入库。脱敏示例和源码中的公开 Discord 路由 ID 不等于凭据。

素材按来源清单保留；公开可下载不代表获得额外版权许可。Lucide 的许可随文件保留，第三方游戏图标来源和授权边界见素材文档。生产 Discord emoji ID 和图片 URL 属运行配置，需由运营单独配置。

## 检查与发布边界

`pr-fast` 新增 `fc-community` 组：在隔离无外网运行阶段执行 Python 单测和 FC 控制台单测；原有 bots 合同继续运行。Windows 本地 Token 保存辅助测试不放进 Linux 组；不会把排除项记为 Linux 通过。CI 不连接 Discord、Admin、Order 或生产 SSH，不验证真实界面、订单归属或现场服务状态。

`ops/` 是此前受控的一次性发布/验收脚本，含固定 staging 路径和源哈希；留作恢复依据，不是可反复运行的通用部署器。新发布先核对活动源与配置，逐文件备份、核验后更新；保留数据库、消息 ID、去重账本和共享服务。历史文档的原价口径已经被用户更正，实际报价始终取折后售价。
