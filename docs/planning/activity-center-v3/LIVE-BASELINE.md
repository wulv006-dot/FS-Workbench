# P0 现场基线 / P1 读取证据

工作要求：FS-V3-G1-CONTINUE-02。2026-10-24，本地主控同一任务继续，未切换控制入口。

## 仓库

本轮 fetch 成功后 origin/main 仍为 `2c976e7f849b3b7916e006dd6907e633051cb3fb`；本项目起点为 `df93de3d3a55a108f94bb56060457b4ccc9f01ab`。原 E 盘823项既有改动未操作。实现工作树 B/C 分别为任务目录下 campaign-b/campaign-c，独立分支，不占用其他任务工作树。

## 187 实测

2026-10-24 08:54:23 UTC，经 PC-20260909OJLI 原 `Invoke-Server187.ps1 -Action Run -RemoteCommand 'python3 -' -InputFile inspect_campaign_runtime.py`，目标 play187，exit 0。

| 目标 | SHA256 |
|---|---|
| /opt/fs-campaign-dashboard/analytics/production-server.mjs | 60a96a1d49ed6a0cccfb363db1643ca4365b8d7ca3a75f81bd2c59faa7227174 |
| /opt/fs-campaign-dashboard/analytics/store.mjs | de96683c677da2347d19571c26af86dd201592f52d7e38cd8fc199ba3e973f0d |
| /opt/fs-campaign-dashboard/catalog.json | 70baa0a6179f057a7b16afb0e77085da4fd09bc648efbc913ce416f8cbcb728d |
| /opt/fs-campaign-dashboard/host-adapter.js | 37e47dcb2a4cea191e9d18df8b41ef5e953e6b7b47636fcb203032840c60e651 |
| /opt/fs-campaign-dashboard/build-seo.mjs | 7b1f0753862720bd221fab263a710552c77be350af463107e25670a6db243c75 |
| /opt/fs-shared-session/shared_admin.py | 6ab54fdcdf2ae4d95e9ce53dc16869b6f663471c2f04be0b0e784c5374218cdd |
| /opt/sales-dashboard/collector/p2pah_auth.py | 3b33f2c3f79d71f312d06ee0ab8593f977b7b0cacdf2f169d688679e7d815ff9 |
| /opt/fc27-sbc-tool/admin_client.py | dac7ec0009b966775fcea98bc788241bdd0a4881be2cbc8d0e39b97f507e5173 |
| /opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_ui_finish.py | fcab510f397582596e86fa913e7edfa4220ff6b44d679839452f920d63160188 |
| /etc/systemd/system/fs-campaign-dashboard.service | f25c7916609765371a6dfb92d811a49c645794940debc826175599c7014fb10a |
| /etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf | 7b19c9717326dc24ade093e1e8166d9e95537a9f79f2fe8cc21ed26d10235d2c |

fs-campaign-dashboard、auth-portal、nginx 均 active/running。8948 管理端、8895鉴权、8767 Admin、8768 Order 均监听；此时8949未占用，实际发布前仍需复查。没有修改服务、网络、权限、凭据或自动任务。

## Admin 精确读取

首次系统 Python 探针在 import requests 时失败（exit 1），未发出后台请求。只读检查现役 systemd 的可执行程序，确认销售、渠道、SBC 使用 `/opt/python39/bin/python3`；沿用该环境，无依赖安装。

2026-10-24 09:00:11 UTC 使用既有 shared_admin + p2pah_auth Session，仅 GET，各取1行用于结构检查：

| 路由 | 结果 | 观察 |
|---|---|---|
| /admin/market.Coupon/index | HTTP200/code1 | id、title、status、mode_type、attain、reduce、max_reduce、site_id、game_id、goods_id、product_type、生效时间、批次数量等字段存在 |
| /admin/market.Discount/index | HTTP200/code1 | id、code、status、site_id、gid、aid、cid、discount、attain、timestart/timeend 等字段存在 |
| /admin/goods.Goods/index | HTTP200/code1 | id、mid、site_id、gid、aid、sid、cid、unit、min_qty、sku_switch、attr_switch、propvalues 等字段存在 |

整体 exit 0。输出只有结构、类型和状态码，不输出业务明细、会员、券码或凭据。此证据证明读取可达，不证明完整分页、写入能力、状态枚举或成交归因已验收。后台字段语义和精确写动作继续核对。

## 输入及原页面

本机原 ZIP 的9份文档已在前检查点闭环；Library Windows os.setxattr 失败保留历史，现不再重试。Seasonal 原 git 版本5bfa19e051808d6b8033f7eb23132405abc853d4的 dist 22个文件已逐个 SHA 一致复制到本模块 app/seasonal；构建脚本和原测试另存 seasonal-source，后续仅调整运行位置和接入，不重画原设计。
