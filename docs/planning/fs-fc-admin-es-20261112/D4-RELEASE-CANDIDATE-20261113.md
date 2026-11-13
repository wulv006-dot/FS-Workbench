# D4 SEO 订单事实制包候选

原 SEO 构建器和发布校验支持显式配置 `sources.orders = {"enabled": true}`。默认和明确关闭时仍沿用现有 Admin 估算，开启时继续要求 `sources.admin = true`，并将 `order_reader.py`、`order_source.py` 同批写入且核验在原清单中。未知配置、缺源码、缺清单成员均失败。沿用原 publisher 的文件范围、SHA、现场 CAS、配置数据根、锁、回退、SEO 专用单元、权限和夜间计划。D3 的历史候选与归档哈希保持原记录。

用合成站点配置、路由和导航调用真实 `prepare.build`，再用原 publisher 的 `validate` 核验源字节及目标合同。已将这个合成包显式标为 `releaseReady=false`。共 39 个目标，归档 `.agent_runtime/d4-seo-20261113-offline-candidate.tar.gz`，已逐成员重新读取和校验。

| 证据 | 值 |
| --- | --- |
| 合成包 | `seo-daily-602dc30443d33935` |
| tar.gz SHA256 | `18a11c3d1e6789affe50b472d7b58bee0c7347a3fbf32d1eacb910a7b593db64` |
| manifest SHA256 | `184c2877e7b3a3e59ab9993d2912add4598042e16fc513affeb9f8c746e92690` |
| 原冻结 publisher SHA256 | `5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357` |
| `order_reader.py` SHA256 | `0ae899175e90e65a23589b6304da3e74b8a7cb74d1d4191d9260fffe66b316f0` |
| `order_source.py` SHA256 | `3681cf91ed8db8270567e0d0857e7e7d8667cdf6364081d43c6cbac88dfbc2dc` |

该包的两个模块映射到 `/opt/fs-seo/releases/<package>/mmoexp_google_data/seo/`。启用前按 [D3 目标与依赖清单](D3-RELEASE-CANDIDATE-20261113.md)先核 D2 共享运行文件。`NativeOrderFactsReader` 经现有 `/opt/fs-exact-range-20261001` 导入 `order_facts_runtime.collect_many` 和 `summary_bridge.dc_request`，经 `/opt/fs-hermes-fc` 读取已有 D0 `es_order_structure`、`order_attribution` 和渠道取数、核算辅助，经既有 `/opt/sales-dashboard/collector` 路径解析原采集依赖。沿用原 8912 Admin 只读入口、已固定的私有 ES 归档发布及已有成本缓存。此前隔离测试实际执行共享 D2 投影→四游戏单日 reader→nightly Store/snapshot，缺安装模块返回 `ORDER_FACTS_READER_NOT_INSTALLED`，其余原来源继续。

Windows 用原 `pr_fast.units` 跑 18 项通过，含制包 3 项、reader 6 项、来源 9 项，零失败、错误或跳过。先复现旧制包直接拒绝启用配置，再验证原估算候选、真实 build→validate、非法配置、缺失文件和同批清单。Windows 原工作树冻结文件为 CRLF，使用同一 Git 提交的 LF 字节装配临时测试目录。保留原 SHA 断言，借已有时区文件和 UTF-8 测试进程处理本机差异。测试禁用外部网络和业务子进程。

生产现场配置、运行模块和 CAS 未读取，未调用原发布器的 `inspect`、`apply`、`rollback` 或生产取数。正式 CI、部署和下一自然夜间读回仍待实际授权与验证。

183 Python3.9增量仅重跑制包3项，3通过、0失败/错误/跳过。包SHA256 `bf5abe3a9127afe26ee70533cf2254bfb4ebf208eccee064ced15f951215e903`；日志及精确LF文件哈希 `.agent_runtime/seo-prepare-linux-{log.txt,hashes.json}`。使用原Git字节核冻结publisher，与PIN一致；断网、只读、nobody、0.25CPU/256MiB，无生产挂载，没有开启订单来源。

## 固定快照页面

SEO 成交页复用当前 `history` 的版本、游戏和付款日期，显示后台已记录为 SEO 的订单、已知美元付款额、订单及金额归因覆盖。Admin 订单版本、ES 归因发布和数据修订可展开核对。旧 GA4 事件乘 Admin 客单价估算仍在原区块。旧快照无新来源时保持旧展示，已配置但来源失败、归因未知、部分覆盖和已证零值有各自状态。`seo.history` 与 `seo.summary` 原 MCP 路径返回同一现有 JSON，保留聚合字段、覆盖及修订，无新增连接器操作。

浏览器先复现旧页面找不到后台归因区域，再验证已有数据、真实零值、未知、部分金额、失败、旧估算、版本修订、390px 和没有额外 `/orders` 请求。原 model、导航和 8 目标 UI 构建合同、JS 语法通过；保留原 CRLF 文件字节约定，按 `core.whitespace=cr-at-eol` 检查变更。

用既有 `ui-system/modules/seo/prepare-ui.cjs` 组装并读回 8 个合成目标。目录 `.agent_runtime/d4-seo-ui-20261113-offline-candidate`，版本 `seo-ui-855c3d9f0a376ff0`，manifest SHA256 `b40be176d2712a0d7af19bade7c519ee054b25e741b96f8cfaac188f08701991`，`app.mjs` SHA256 `7db6809fc112a8c67374e2e5ae7e2485820bae059dd628468ca52e606f452188`。该样例的路由与保护文件哈希为合成输入，标记 `releaseReady=false`。上节 39 目标归档保留制包验证当时的字节，若实际用 SEO 全包更新，应以本次页面源码一起重建。

## 当前生产页面候选与现场检查

本次按现网 `seo-daily-f63038d3070d3af9` 七份资产逐一核对：只有本轮 app.mjs 的后台归因显示发生业务差分，其余资产使用相同 Git 字节。现役 UI-only 桥接为 `/opt/fs-release-stage/navigation-experience-20261103-repair-v3/release_ui.py`，SHA256 `39b6e5b55c0723fafb11743996a51154c1a01828e9370d06dedaddab7264a957`；沿原 `traffic-source-tabs-20261019-v3` 发布器和既有锁/CAS/备份，不使用仅保护首页的 release_gateway 代替。

生产页面候选 `seo-ui-c9e4111c43b04308`：8目标，manifest SHA256 `710aef6756fc22a68612bb5ce09feecf1cf2d3f7a06c418da89e0310168a05f4`，归档SHA256 `f4bd9e9201c5fadbf1166db61f742474900f8c09df7fbaa5b66839fb7cf7efec`。暂存目录 `/opt/fs-release-stage/fs-fc-admin-es-seo-ui-20261113-c9e4111c43b04308`。原 `release_ui.py inspect` 返回8文件、sourceCAS/protectedCAS通过、mutations=false。`releaseReady=true` 仅表示此候选通过该准备检查，不是已经安装。未执行apply，正式CI仍进行中；之后沿同一manifest和原发布器发布、读回与真实页面验收。
