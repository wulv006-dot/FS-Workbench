# P1 候选与读取验收（2026-10-28）

状态：候选已修改并本地检查；本文件不证明 CI、合并、部署或生产进程加载。发布精确文件与候选 SHA 见 `P1-DIRECT-API-TARGETS.json`。不修改 Price 原价展示、实际售价或财务计算。

- FCDetails 原进程改为宿主 reader 子进程；reader 复用现有 p2pah_auth.Session。
- ES 复用原 durable root、导出锁、原始文件校验及归档；明确菜单401/403为 permission_denied/not_generated，其余结果未知仍保留原 attempt，禁止重复生成。当日档案600秒到期重刷；128容量仅可回收有完整原始证据、无窗口attempt/last_attempt的派生投影。
- cohort、capability、商品订单与私有客户读取改用原 API/原 collect/原 PrivateReads；权限、投影、客户key不变。商品模型保留540秒原预算；整日客户扫描保留850秒总预算和单请求10秒，改20条小页、1500页保留原30000行读取上限；总量、唯一ID、重复冲突与完整分页验证不减。跨线程新HTTP客户端假说未改善，已撤回，不纳入候选。
- 毛利与成本缓存修复见本轮合同：仅持久化 orders/cost 两个source都complete才冻结；0单合法完整可复用；成本失败仅补成本。8931历史统计7天，当日600秒，refresh强刷。summary合同升级不应无谓使毛利缓存失效；旧精确v1键回退沿原target。

## 真实隔离验证

全部候选实读均以 socket 拒绝8767，不调用模型，不写价、不写客户配置。

- FC reader昨日373单、当前积压1008；paid_complete=true，missing_days=[]。耗时191.401秒，未降低原900秒能力。
- 主站 cohort 373单/4页完整；PrivateClient 原key与history成功，精确测试邮箱0单完整；真实目录PID169531477商品订单available/昨日0单完整。
- native_loss available；product_sales被原API菜单拒绝（denied/source_denied），不借8767绕行。
- 用户确认：**付款记录保留，退款单列**。386条原生付款记录继续保留，13条退款独立描述，不把退款从历史付款记录删除，不把373成本覆盖子集伪装成全体付款分母。实际毛利API标记 `membershipBasis=paid_non_refunded_subset`，原三份看板脚本的实际成本覆盖说明明确“已付且未退款”，不改变毛利公式、售价或原生付款数。
- 373与386不是站点差异：相同昨日、game1327、pay1，本地日期与原UTC日期两种原生请求均site266/all返回386/$26268.37；订单列表严格site266/gid/pay1为373。原ES档386行由已完成324、问题订单39、已支付10、已退款13组成；同日日缓存386条中refunded=false恰373，核实了含退款/排退款分母差。原ES订单号与该缓存的尝试关联未匹配，未据此声称逐单同群；保留独立群体与来源，不混分母。
- Private scan复用昨日ALL原始ES档；真实函数抽取比较证明原请求 endpoint/过滤/排序/page1/limit100 与成功cohort完全相同，没有for_update或缺筛选。单独同范围20条页请求0.216秒、134304字节、20/373、scope全部匹配；完整扫描的20条第一页仍在10.012秒ReadTimeout（扩大到60秒和跨线程新客户端的假说均未解决，均已撤回）。保留 unavailable，不声称扫描闭环，也不泛化为所有Admin源不可用。新6001行/301页回归证明小页不截断旧300页以上的完整群体。
- 今日ALL ES单次 `/admin/order.OrderExcelByEs/downloadsMake` 返回明确菜单拒绝：permission_denied/not_generated，可在授权后沿同窗口接续；未生成/下载新Excel。原receipt `f66ef7872df9681966e19e23e1b76b290dc8b133fb1b81a3887091fd7b935b5a.json`，无unknown attempt。随后只读复用P2菜单遍历：8912 `/admin/index/index` 当前wulvapi/code1/superfalse，菜单不含downloadsMake/orderExcelByEs/makeExcelByEs，exportRequests=0。没有第二次生成请求。旧窗口原始档案复用与字段/哈希校验通过。
- 容量单槽整理只移动一个可重建派生JSON至 `/var/backups/admin-recovery-review-20261028/es-projection-cache/`，备份SHA校验通过，所有raw/manifest/33个attempt保留；脱敏manifest记录原路径/backup/SHA与完整原始证据。

现场脱敏证据位于项目 `.agent_runtime/admin-recovery-20261028/`：`p1_direct_api_readonly_evidence.jsonl`、`p1_remaining_evidence.jsonl`、`p1_native_period_evidence.jsonl`、`p1_membership_evidence.jsonl`、`p1_final_bridge_evidence.jsonl`、`p1_query_compare_evidence.jsonl`、`p1_smallpage_evidence.jsonl`、`p1_private_scan_page_diagnostic_evidence.jsonl`、`p1_es_menu_evidence.jsonl`、`p1_direct_es_today_reclaim_once_evidence.jsonl`。

## 加载边界

现场 fs-business-range PID11530，启动期载入 FCDetails、HermesService/controller、TrackingController；controller载入fs_evidence/Preparation，build_book载入source_snapshots、capability/fs_reader、ES、product/cohort。上述P1模块是宿主range进程常驻模块，落盘后需由原发布流程重载 `fs-business-range.service` 才能声称新API已加载。fc_detail_reader为该进程启动的独立宿主子进程，下一次启动读新文件。

实际模型容器 `fs-hermes-fc` PID29473 的 `/opt/pilot/hermes_worker.py` 只载入proxy_gateway/runs_contract、模型gateway与skill_bundle，不载入P1数据模块；本批API迁移不要求重启模型worker。任务表读取时所有tasks为终态：CANCELLED3/FAILED28/PARTIAL134/SUCCEEDED165，requests无在途；learning queued92保留，不以其替代模型任务状态。证据 `p1_loading*_evidence.jsonl` 与 `p1_worker_loads_evidence.jsonl`。发布前仍须重新核在途状态。

## 必要检查

在仓库根运行（Python需lxml，使用UTF-8模式）；以下新增直连相关共189项本地通过。退款口径补充后另通过实际毛利28项、原三份UI的29项合同检查。正式CI由本轮主代理执行并单独记录。

```powershell
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/fc-detail-analytics-20261012/tests
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/hermes-generic-data-20261018/tests
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/hermes-customer-tracking-20261018/tests
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/hermes-customer-lifecycle-20261019/tests
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/hermes-data-workspace-20261018/tests -p test_cohort_es_source.py
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/cache-archive-retention-20261025/tests
# 以下在 releases/fs-dashboard/hermes-fc-pilot-20261013 目录运行：
python -X utf8 -B -m unittest admin_order_capabilities_20261014.test_capabilities
```

本轮既有缓存/快照受影响回归（以共享候选最终版本重跑，不替代P2/P4并行变更检查）：

```powershell
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/dashboard-refresh-20261025/tests
python -X utf8 -B -m unittest discover -s releases/fs-dashboard/fc-coins-workflow-20261022/tests
```

今日ES权限未恢复前，不重跑downloadsMake。历史结果未知先查原receipt/attempt/raw，不换root或ID。

## 8767退役前额外现役消费者（只读鉴别，未修改RPG）

- `/opt/d4follow/_stage-p0-20261023/prepare_candidate.py` 是历史生成器；但其旧依赖已进入当前活动 `/opt/d4follow/srv_exec.py`，不能只按stage路径判断退役。`p2pah-srv-exec.service` active/running，实际入口srv_exec；readgold对账与工单两个docker启动点仍注入8767地址，并绑定 `/opt/fs-order-session/fc_shared_admin.py` 到 `/srv/fc_shared_admin.py`。
- 现役 `/opt/d4follow/_p2pah_srv/admin_cache_local.py` 原兼容合同：`SessionManager({}).ensure()` 与 `.token`、显式旧HTTPS base构造、`.request(path,data=...,token=...) -> (status,bytes)`。清缓存传输失败结果未知不重发的原保护必须保持，不能用停用RPG流程替代迁移。
- `rpg-cache-retry.timer` enabled/active waiting；实际 `cache_retry.py` 首选8911，8911不可用时仍走 `admin_cache_local.load_token/clear_cache` 旧分支。这是现役兜底，不是可忽略死码。
- 本次只读证据 `p1_d4_active_evidence.jsonl`；未执行清缓存、工单、调度或价格动作。主代理需在最终8767退役前完成原共享模块同接口直API兼容，包含容器8913地址与旧HTTPS配置归一，不能仅发布FC专用adapter后宣称全局退役完成。
