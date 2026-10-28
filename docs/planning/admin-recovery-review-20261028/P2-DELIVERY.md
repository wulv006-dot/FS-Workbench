# P2 看板候选与精确映射

当前为候选，尚未声明正式 CI、合并、发布、在线自然周期验收。维护源为 `releases/fs-dashboard/dashboard-refresh-20261025/source/` 的本次清单；逐文件见 [P2-SOURCE-MAP.json](P2-SOURCE-MAP.json)。P4 正接续 `range_api.py` 并发修复，最终提交后须刷新该文件候选 SHA，不能覆盖其改动。

销售六卡与曲线统一同网站、游戏和支付日期的 Admin 已付款全部订单，`pay_status=1 / order_status=''`。原 Order 完成统计保留为带来源标签的参考，不再代替默认销售。退款保留在原付款记录群体中；三版本已有 `refundAmountUsd / refundOrders` 独立维度继续沿相同筛选显示，不新增推算，也不把成本子集当全部付款分母。实际毛利仍为已核完成单整单 CNY 收入减同订单历史成本，覆盖不外推。

当日 TTL 600 秒，历史更正周期保持。summary 与 RPG native 缓存带新付款合同；旧完成单归档不改写。缺少可核付款 cohort 的旧 RPG 快照不能被改名 seed 到新 key；非 RPG 原 native key、`native-closed-v2` 统计合同及原归档排程保持。`daily_archive.py` 仅替换 range 活动文件，Hermes 另一兼容副本不在此映射。

Admin 全部使用现有 8912 API。`summary_bridge`、native collector、supplement reader、FC 产品 reader 不再依赖 8767、容器登录、BATOKEN 续期或 OCR。Order 8768 取数保持。`admin_summary / catalog / collector / supplement_reader / fc_product_reader` 是从实际活动文件接入当前维护清单，不能因 Git 新增误记为服务器新文件。

## 实测与回归

- Aion2，2026-10-27 00:00 至 2026-10-28 00:00：主站全部付款 186 单 / $17,689.92，全站 192 单 / $18,114.27；原完成单分别 181/187。候选真实 direct API 入口及 24 个趋势点合计与对应六卡相等。
- P2 完成时看板 Python 119 项、前端合同 29 项、三版本浏览器回归通过；随后 P1/P4 改动需由最终组合检查另记。证据在本机 `.agent_runtime/admin-recovery-20261028/p2_{aion,paid_candidate,native_paid_candidate,direct_candidate}_*evidence.jsonl`。
- P4 接续后 Linux 该组 124 项与专项真实 HTTP/flock 并发 5 项通过，证据为同一本机目录 `p4_full_linux_evidence.txt / p4_concurrency_linux_evidence.txt`；该结果不代替后续 P1 最终修改及正式 CI。
- 产品聚合接口在本轮诊断时两套 API 均业务 401：`/admin/stats.productSalesByEs/index`，签名 `stats/productsalesbyes/index`。范围仅 FC 产品排名/该分析入口，保持 unavailable，不绕回 8767；后续权限恢复另行验收。
- 另行只读核对两套账号 `/admin/index/index`：均明确列出 `goods/goodsMould/recalcFc27Price`。主线及备用真实模型列表 1327/9627 均为 955/955、5 页完整；真实 category POST 未由本检查执行，仍待原 Players 工单验收。权限元数据不代替真实写入回执。

## 原发布器与清单

2026-10-28 只读核对四个当前活动文件仍位于 `/var/lib/fs-navigation-formal-static/business-filter-layout-20261025-cad1dca27f17/`，其当前 nginx alias、SHA 与 P2-SOURCE-MAP 的 `activeRoute / activeTarget / beforeSha256` 一致。新四个静态文件使用独立版本目录，沿原 nginx 文件只替换这四条 alias，不覆盖旧静态版本。P2 部分为十个已有后端文件、四个新版本静态文件和一个生成的 navigation.conf；合并 P1/P4 发布时按各自精确映射取并集。

现有服务器发布入口是 `/opt/fs-release-stage/business-filter-layout-20261025-v1/filter_release.py`，同目录已有 `actual_release.py / release.py / release_navigation_base.py / shipping_readiness.py / approved-manifest.json`。它使用原 CAS、锁、备份、回滚及 fence，CLI 只有 inspect/apply/rollback；该目录没有 prepare 入口。

原本机清单生成脚本实际位于 `E:/WorkBuddy/大超服务器/business_dashboard_refresh_20261025/stage/prepare.py`：读取 `baseline/current.json` 与此前 `approved-manifest.json`，生成候选 SHA、beforeSHA、保护清单、四静态 alias 替换、适配器与 zip。这是旧日期/范围的硬编码生成脚本，不能原样执行覆盖旧包；本次应复用其现有清单格式与生成步骤，套入本次已提交的精确文件列表。原 filter 阶段本机可核目录为 `.agent_runtime/business-filter-layout-20261025/.agent_runtime/release-stage-v1/`，包含完整既有适配器、候选和 approved-manifest；`filter-stage-inspect.py` 为其既有验证入口，不是 prepare。

本次未重新实现 publisher。宿主 range 模块导入只需对应 range reader 更新，不重启 Hermes 模型 worker，不改原 timer。`fc27-p2pah-session.service` 临时恢复候选不在 P2 清单内，最终退役由主代理单列验收。

## 数据暂存的 observer 保护路径

现场 `/opt/fc27-cloud-browser/fc_observer.py` 是独立只读身份使用的账本投影模块，SHA `f53ec6e199dd6e1592d3e50151d859ffb9a1d7a3a97ec51e83eebd89a696de84`，继续按正存在哈希保护。它不是被退役的旧价格观察器，不能删掉或误设为负存在。

原退役合同在 `fc-pricing-v3-20261026/RETIREMENT-MATRIX.md`：真正的旧路径是 `/opt/fc27-price-observer`，以及 `fc27-price-observer.path / fc27-price-observer.service` 两个原单元文件。2026-10-28 已只读确认这三处均不存在且不是链接；数据发布适配器在原全部 guards 后追加这些负存在检查。只读投影仍在正保护中；没有复活或删除任何 observer 文件。

`ef208b1` 的 31 目标暂存包已通过原 publisher inspect（sourceCAS/protectedCAS/退休检查，mutations=false），尚未 apply。最终计划为 32 目标、6 NEW：第 32 项仅是兼容包 `releases/ops/shared-admin-direct-20261028/source/fc_shared_admin.py` 到原 `/opt/fs-order-session/fc_shared_admin.py`，把既有 RPG Admin 缓存传输切到同一 API；before `a676388f…`，after `c6eaf379…`，原 owner/mode 保持 root:root/0644。FC 独立 adapter 不在此发布目标中。共享分页性能方案未通过实测，已撤回；`channel_source.py` 仍以现场 SHA `ce01980e11158b1ff11617b8229957ed3b5ae7065df75b12b37f9661b6bfe3ea` 正保护，不发布或覆盖其两处现场热修。

原 31 目标 manifest 的保护集合还包含 FC 的 execute/restore、worker、pricing_sources、runtime/dispatch 两份副本及独立 helper。后续 FC 修复发布会改变这些保护 SHA；数据包不得沿用旧基线盲放行。须在 FC 部署后重新读取当前 CAS，以最终提交引用原 30 个数据源码及新增单个共享 adapter 的 Git blob，重生成数据 manifest，再通过原 inspect。FC 专属源码不属于数据包的发布目标。既有 RPG 容器仍可能持有旧 inode，待其自然退出并核实无旧加载后再退役 8767，不为本包中断或重启 RPG。当前候选、正式检查、发布状态由主代理最终交付记录更新。

## 日期与归档保留候选（尚未发布）

逐笔月限修复仅涉及 `order.Order/index`：cohort长窗口复用现有28日窗口并逐片分页；FCDetails长窗口直接走已有按日路径；FC历史价格窗口候选按同样窗口保留秒边界。原生汇总继续整窗，未缩减客户指标或界面日期选择。新 `test_order_date_windows.py` 已确认未被Git忽略，10项离线检查通过，包含3项FC调用组合；正式检查需与这些源码共同提交。

现场 `daily_archive.py` SHA `0652062c39e3bede009d24c31811ab5e1a937f1a572d7193b9d0b12ede87452e` 原写入/读取/清理均受三个月业务日期截止限制；`archive_jobs.py` SHA `de24cb028101cfcd6a615dbb9f5fb7500c508a612ab75c380035fb516b9bbf22` 的 scheduled 分支真实调用 `prune(False)`。10月28日03:37/03:44 UTC已有清理回执，截止7月28日、删除对象0；索引最早native/summary/marketing为8月1日，不能据此推断更早档案曾被删除。

用户已授权修复为一年保留。候选复用原日期函数，保留默认三个月 `cutoff` 供自动补采，新 `retention_cutoff` 只用于归档写入/读取/清理及回执元数据。已有对象/索引/来源时间原样，不执行清理、不自动补采十二个月。离线新增一年边界、闰日及真实history候选保持三个月的组合检查；当日600秒和完整源归档规则保持。当前仅源码候选，本轮未在服务器运行prune或发布此修改。

## 三份活动归档模块与最终34目标候选

最终数据候选为34目标、6 NEW：原32目标追加营销 `/opt/mmoexp-marketing/custom-range/daily_archive.py` 与独立Hermes `/opt/fs-hermes-fc/daily_archive.py` 两个已有文件。它们当前同SHA `aa33c6fb…`，仅使用旧 `daily-archive-20261021/source/daily_archive.py` 的18行保留期局部补丁，候选SHA `28374ee3…`；新版range仍使用 `dashboard-refresh-20261025/source/daily_archive.py`，不能互相覆盖。精确三份映射及各进程证据见 `COMPAT-ARCHIVE-TARGETS.json`；没有新增archive_jobs目标。

候选文件名分别为 `source/daily_archive.py`、`source/marketing-daily_archive.py`、`source/hermes-daily_archive.py`，同一旧源只复制到后两处。原发布适配器保留CAS、锁、fence、未知任务及回滚，nav精确目标保留既有0600，其余目标继续644断言。营销沿原重载链额外重载已活动 `fs-marketing-range.service`；原8935端口 `/range` 无X-Auth-User必在query前返回401，此只读契约已核，可用于重载后监听/鉴权读回，不能冒称经营采集验收。Hermes模型worker不为本补丁重启。

本候选源提交/正式CI、暂存检查和实际发布分开。FC日期代码不属于数据34，已由主代理通过独立2目标发布；最终数据baseline必须在该发布后重取全部保护SHA，不能沿用旧manifest。
