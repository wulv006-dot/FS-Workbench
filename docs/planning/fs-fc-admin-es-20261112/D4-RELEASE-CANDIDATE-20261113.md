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

183 Python 3.9.18 制包 3 项通过，零失败、错误或跳过。隔离包 SHA256 `bf5abe3a9127afe26ee70533cf2254bfb4ebf208eccee064ced15f951215e903`，日志 `.agent_runtime/seo-prepare-linux-log.txt`，断网、只读、无生产挂载。

生产现场配置、运行模块和 CAS 未读取，未调用原发布器的 `inspect`、`apply`、`rollback` 或生产取数。正式 CI、部署和下一自然夜间读回仍待实际授权与验证。

183 Python3.9增量仅重跑制包3项，3通过、0失败/错误/跳过。包SHA256 `bf5abe3a9127afe26ee70533cf2254bfb4ebf208eccee064ced15f951215e903`；日志及精确LF文件哈希 `.agent_runtime/seo-prepare-linux-{log.txt,hashes.json}`。使用原Git字节核冻结publisher，与PIN一致；断网、只读、nobody、0.25CPU/256MiB，无生产挂载，没有开启订单来源。
