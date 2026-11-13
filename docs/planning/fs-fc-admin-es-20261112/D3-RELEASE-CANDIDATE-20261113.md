# D3 页面、导出与数据批次候选

渠道看板的表格、日趋势和 CSV 共用同一次聚合响应。日期、站点、游戏和派生渠道由服务端确认。导出使用页面持有的汇总 CSV，携带事实定义、归因版本和来源修订。切换筛选时暂不能导出上一范围。付款时间待核的订单留在区间汇总，日趋势标为部分覆盖，CSV 记录未分配数量。筛选某一已知渠道时，同日归因未知会留下范围缺口。已有优惠码、推荐人及优惠券视图继续使用原入口。

FC 三个经营入口的明细和分类趋势 CSV 绑定页面当前缓存快照，保留完整明细和原分类优先级。对应缓存被替换或不存在时，返回 409 并提示更新明细。缓存仍匹配时，即使需要后台刷新，导出也使用当前展示版本，且不启动采集。原未绑定的 CSV 调用仍按既有合同运行。复购主卡显示 Admin 原生率，已验证的本地区间人数及口径在指标详情显示。现有 D1 线上组合尚未接入可验证的同范围本地复购数据，候选在缺覆盖时显示暂缺。Order 发货统计继续用于经营主毛利，渠道页面单列同订单核算。

## 同批载荷与来源

[逐文件清单](evidence/d3-release-candidate.json)记录 Git 候选源、拟安装目标、内容字节及 SHA256。已本地组装并重读 `.agent_runtime/es-d3-20261113-candidate.tar.gz`，逐成员核对索引、内容和 Python 3.9 语法。归档为源文件候选，保留原 Git 相对路径，统一使用 LF 文本字节。它还没有现场 CAS、生成后的组合文件、生产镜像或批准 manifest。

| 层 | 同批装配与既有依赖 |
| --- | --- |
| D0 归档 | `/opt/fs-hermes-fc/es_order_structure.py` 和同目录 `order_attribution.py` 同批。现有 session 以 `Dockerfile.session` 同时装入 `/usr/local/bin/es_order_structure.py` 及 `/usr/local/bin/order_attribution.py`。保留原 `coupon_channels.py`、映射 JSON 和 `admin_discount_analysis.py`。183 历史隔离镜像已证明两种路径的导入；原 session 基础镜像构建尚未执行。 |
| D1/D2 range | `/opt/fs-exact-range-20261001/` 的 `admin_scope.py`、`daily_archive.py`、`live_summary.py`、`site_summary.py`、`summary_bridge.py`、`admin_summary.py`、`range_api.py` 和四个 `order_facts*.py`。依赖原 `supplement_fields.py`、Hermes 目录的 `channel_effects.py` 与 `channel_source.py`、D0 host reader，以及原只读 Admin 8912、已有用户归档发布记录和成本缓存。 |
| D3 渠道 | `index.html`、`channel.js`、`channel.css` 使用清单中的新静态目录，和后端 `order_facts_api.py` 一起切换。原 `/dashboard/channel-effects/data.json` 转发 `/channels`。保留现有管理员校验、同站会话和受保护路由，只调整本页静态指向。 |
| D3 经营 | 三份独立 `business.js` 及其对应现有壳和 CSS 用同一不可变版本。`fc_detail.py`、`fc_dashboard.py`、`fc_detail_reader.py`、`fc_detail_model.py` 沿既有 FC 经营部署映射，同批接收带快照参数的请求。原 `fc_detail_config.json` 及现有订单后台会话继续使用。 |
| D4/D5 消费 | SEO 源码增量在清单中按 `/opt/fs-seo/releases/{seo-package}/mmoexp_google_data/seo/` 记录，D2 共享依赖先就绪。连接器沿现有 `fs_mcp_connector` 包装配 catalog。知识候选沿 [D5 检查点](D5-KNOWLEDGE-20261113.md) 原收尾入口。 |

原渠道 [`deploy/release.py`](../../../releases/fs-dashboard/channel-effects-20261021/deploy/release.py) 和原经营 [`deploy/fc_dashboard_release.py`](../../../releases/fs-dashboard/dashboard-refresh-20261025/deploy/fc_dashboard_release.py) 指向既有受控 publisher。现有适配器的目标集合和历史 manifest 不能直接执行这份合并源包。获准的实际发布窗口须从现役路由生成本批增量、为本批目标采集 CAS，并沿原 publisher 用精确清单、备份和回退。`range_api.py` 与 `admin_summary.py` 在清单标为 `git_merge_input_only`。按 [MASTER 现场组合记录](MASTER.md#35-现场组合版本是发布保护对象不拿旧目录整体覆盖)，实际制包须用本轮增量与届时现场组合源码三方合并，保留现有管理项目、campaign 周报、desktop RPC、受会话校验的实时订单、邮箱导出及认证接线。清单的 SHA 对应候选文件字节，现场 `beforeSha256` 尚未读取。

SEO 现有 [`prepare.py`](../../../mmoexp_google_data/seo/prepare.py) 的 `INITIAL_ESTIMATE_RELEASE_USES_NATIVE_SUMMARY` 合同会拒绝启用订单来源的配置。当前归档保留源码增量，实际 SEO 包仍须沿原 [`release.py`](../../../mmoexp_google_data/seo/release.py) 适配其已有受控配置和原夜间入口。没有生成 SEO 正式包或改变运行计划。正式 CI、生产基础镜像和组合源码、现网读回、SEO 自然夜间、云端连接器及模型消费均未验。

## 本轮验证

- Windows 原隔离单测：渠道事实、原生桥接、路由和 API 相关回归 43 项，日期未知增量加入后直接 API 15 项通过。FC 详情、商品分类和小时投影 58 项通过。以上零失败、错误或跳过。
- 183 Python 3.9.18：渠道 API 15 项通过，隔离包 SHA256 `4cb1e6c292fecf61b92d1d4ae2706659fe7c7f7ec7875ee3dc714a56fd30e20c`。FC 缓存快照绑定与原全量 CSV 2 项通过，隔离包 SHA256 `ebb23dd0d2d481f8fc27ddaca9ea74fa05399c07951707bf57d04472082027f1`。两个隔离包均断网、只读、未挂生产目录，零跳过。
- 新旧渠道 Playwright 通过，覆盖同筛选趋势、原快照导出无新增网络请求、刷新后版本变化、范围不匹配、部分、空结果、权限、深浅主题和窄屏。FC 三份实际业务渲染脚本的浏览器验收通过，覆盖保留逐单导出、同筛选快照和 409；三个入口各通过 29 个原生指标场景。原壳校验首轮遇 Windows 工作树 CRLF，改由原 Git LF blob 作为临时只读输入后，固定 SHA 和三个原壳路由回归均通过，壳源码及断言未改。
- 先行测试复现旧 API 缺日期趋势、未回显派生渠道，以及旧 FC API 拒绝导出快照参数。FC 页面随后通过实际受保护读取封装识别其 409 错误，不重试旧快照。新旧入口测试均使用本地合成数据。本轮没有发起生产查询、导出、发布或改价。

## 在途筛选的导出一致性修复

独立复核指出：旧日期查询在途时编辑日期，旧响应返回后会把 renderedQuery 错设成当前输入，导致旧范围 CSV 可导出。主控用真实页面延迟响应先复现失败，再将记录改为本次已核验 applied 查询。只补一条在途编辑回归，完整现有渠道页面回归通过；没有新增门禁或取数。该修复须进入本批渠道资产，旧 D3 归档不代表最新页面字节。
