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
