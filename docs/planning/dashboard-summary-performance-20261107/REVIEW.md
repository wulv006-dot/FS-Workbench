# 首页与经营汇总读取优化

负责人：Codex；分支 `codex/dashboard-summary-performance-20261107`；基线 `e678f1b`。本次用户要求核对首页空白、30天加载慢与数据存储/读取/计算流程，并优化。本文记录调查和本地变更，不证明上线。

## 结论与证据

1. 首页空白存在已复现的前后端合同错配。2026-11-07 20:36 北京时间，通过用户已登录 Chrome 的真实首页观察：summary HTTP 200、status=available、scopeContractId=admin-paid-order-labelled-supplement-v2；Admin readSeconds=0.47。首页实际加载的 37fe 资产仍只接受 v1，因此显示“经营指标暂不可用”。Order/Shipping 当时 pending，不应取消已取得的 Admin 销售和订单。
2. FC 全部商品核心卡原来由 fc-detail 的 `fc_dashboard.totals` 覆盖；原生 Admin 客户字段则独立显示。用户截图中“客户卡有值、销售/订单待读取”与此代码链路一致。真实当前页面还观察到明细截至18:47、原生客户汇总截至20:35；不能把两者说成同一读取水位。
3. SummaryCache 原先在取得内存原生结果之前调用 derive_summary。30天完整派生最多逐日读取30份归档；即便 Admin 已可用，只要 Order/Shipping 尚不完整，也可能被旧归档或日合计替换。本地失败测试复现了“当前原生值被替换”。
4. 同日追加真实页面验证：FC27、全部站点、全部商品、2026-10-08至11-06，summary返回HTTP200、origin=dated-archive、archive.read=exact_complete_archive，Admin/Order/Shipping均available；fc-detail仍202/pending，销售、订单和毛利卡仍“待读取”，客户卡已有值。该精确区间归档确实已命中，问题位于消费展示；此观察不代表所有游戏和日期归档均完整。

## 当前架构

| 层/入口 | 数据来源与工作 | 主要限制 |
|---|---|---|
| 首页 LiveSummary | authenticated range.json mode=summary → SummaryCache → Admin 原生区间统计、Order参考率 | 旧首页拒绝新合同；当日每次刷新有新的统计截止时间 |
| 通用经营核心卡 | summary_bridge / site_summary / rs_admin；Admin 付款销售、订单、客户原值；Order发货统计人民币毛利 | Admin 与 Order 通道独立；Order与Shipping共享串行资源和原锁，不能用等待Order否定Admin |
| 区间缓存 | SummaryCache 内存按范围/站点/游戏/合同键复用；历史完整响应落 daily_archive | 完整归档条件包含原请求各来源；有每日文件不等于任意范围/合同已经命中 |
| 每日归档 | SQLite目录定位 gzip版本对象；优先完整同范围版本，必要时同合同逐日派生 | 人数和原生比例不可加总；缺一天不伪造完整；Shipping没有在此派生为完整毛利 |
| FC明细/分类 | 按区间缓存原始读取结果；整单商品归属、平台、金额分档、消费、发货关联后聚合 | 必须明细；当前积压混在同一快照，历史范围TTL也受今日缓存上限约束；每次请求仍聚合所选视图 |
| 趋势 | 原有日/小时序列与 profit-history；FC分类趋势来自同一明细归属 | 不能把整体原生数硬分配给分类；缺失日期保留缺口 |

源码依据：`dashboard-refresh-20261025/source/{live_summary,summary_bridge,site_summary,daily_archive}.py`、同目录三份 business JS、`fc-detail-analytics-20261012/source/{fc_detail,fc_detail_reader,fc_dashboard}.py`。服务器归档覆盖率/命中率、当前这些Python模块哈希未读回；不从代码推定生产状态。

## 本次最小改动

- 四份相关外壳对齐现行 v2 合同，首页默认北京时间昨日；标题、卡片日期与无障碍标签同步。保留原手动更新、来源时间、主站及预估利润口径。
- 三份经营渲染器：FC全部商品、全部平台/客户/金额档且网站与时间吻合时，直接展示原生Admin销售、订单及销售÷订单的客单价；毛利使用现有经过范围校验的Shipping投影。明细未完成不再阻塞主卡。
- 指定分类/平台/客户/金额档和当前履约池仍由原明细合同处理，不借整体数，不减少分类/下钻/导出能力。
- 后端先取得原生结果；只有原生未可用、非权限拒绝、非强制刷新时才逐日派生归档。已有完整区间归档优先路径保留；不新增缓存层、表、依赖或定时任务。
- 原客户人数/复购率口径、发货交易时间人民币利润、P0定价/采集、身份权限、原锁及写入对账均不修改。

## 验证与未完成

- 新增回归先失败后通过：首页新版合同、北京时间跨月昨日、明细pending时核心卡、细分不借总数、原生结果不被归档替换、原生pending时仍保留日归档兜底。
- Playwright四个实际首页外壳，模拟数据验证昨日标题、订单/销售显示以及Order缺失不隐藏Admin；通过。
- 三个经营入口各自的原生客户/范围边界和单日小时回归通过；FC连续页面、筛选竞态、真实外壳状态恢复、权限清除、深浅色和窄屏现有回归通过。
- 独立Python归档17项、刷新10项、直接Admin5项通过。并发范围19项中10项通过、9项Linux专属跳过，不能记作完整通过。
- Windows pr-fast实际未通过：219项，1失败、29错误、14跳过；包括缺lxml、Linux os.geteuid/flock/fork和/dev/null符号链接行为。保留检查要求，未放宽断言或跳过门禁；日志在本地 `.qa/summary-performance/pr-fast.log`。正式Linux CI待验。
- 本机项目部署配置SSH连接被服务器拒绝（publickey）；未修改身份验证设置或尝试绕过。已向用户请求当前有效运维入口。183隔离测试、线上归档完整性/延迟基准、生产Python/路由版本核对、发布与真实新页面均未完成。
- CodeGraph增量同步返回 already up to date。尚未合并或部署，线上问题仍不能宣称恢复。
- 首轮正式Linux CI：经营模块219项Python检查无失败/错误/跳过，经营浏览器回归通过；UI历史字节断言因本次有意更新首页合同失败。已将该断言对齐实际后端CONTRACT，其他历史数据处理函数仍逐字比较，新增首页行为回归保留；最终CI状态以PR #896最新提交为准。
- 统一知识收尾plan已使用现成含时区库的Python运行，未识别受影响正式知识条目、无冲突；没有发布知识或同步Notion。

## 后续验收

拿到有效入口后，先只读核对活动目标、归档目录的同合同覆盖、后台读取耗时、缓存命中和独立来源失败。沿现有publisher准备精确载荷、CAS、备份及必要维护范围；生产发布按本次具体清单确认，不重放旧manifest。对昨日首页、全局及FC/RS/其他游戏30天进行冷/热读取实测，核对主卡出现时间与源数值；分类未知及部分覆盖保留。只有证据表明分类重读仍是瓶颈，再拆分历史付款/发货与当前积压的缓存刷新，不能以提速为由冻结当前状态或停用自动化。
