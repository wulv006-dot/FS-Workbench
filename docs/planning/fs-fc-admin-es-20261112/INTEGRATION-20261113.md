# 连续施工检查点：D2 接线、D3 渠道页、D4 消费链、FC 计算基础

本记录的基线为 `f15ef6c2ac89d940f2311c05316a3333e43a10c5`。用户最新“全线开工”替代旧的小阶段停止条件；仍不扩大生产部署、价格激活、真实写入或平台权限。主控统一整合，子任务按文件隔离；没有第二总控。本检查点不是总方案完成。

## 已完成的候选及证据

| 范围 | 实际改动 | 验证及限制 |
|---|---|---|
| D2 原生桥接 | `order_facts_source.py`、`order_facts_runtime.py`：Admin 原生付款集合、原单号正向哈希、固定 publication 的 D0 归档、既有发货缓存 | Windows / 183 Python 3.9 新增接线与 API 共 27 项通过，零失败/错误/跳过；另有下述真实只读验证 |
| D2 只读 API | `order_facts_api.py` + `range_api.py` 既有 `/channels?mode=order-facts` 分流 | 原管理权限、共享两槽、用户/范围内存缓存；只返回聚合、覆盖与修订，不返回原单号/原始私有行；HTTP 分流为隔离测试，未部署 |
| D3 渠道页面 | 原渠道页默认后台归因；旧码、推荐人及券视图保留；日期/游戏/渠道作用于服务器事实集合 | 新旧 Playwright 均通过；刷新小修后重测直接 UI/API。未知渠道保留收入，缺成本/毛利不补零；未修改经营八主卡；真实页面未上线 |
| D4 SEO 消费链 | `OrderSource`、runtime 注册、版本化指标、原 Store/snapshot 消费；完整空集合与来源缺失区分 | Windows 新增/相关 19 项和原 snapshot/estimate 19 项通过，零跳过；尚未绑定生产 reader，未改变原夜间计划；Linux 未验 |
| F0 部分 | `price_curve.py`：完整原生数组读取与曲线指纹，不从单价重建高档 | Windows 9 项、183 Python 3.9 9 项通过；六个精确 Goods 只读实测均 15 档，原 payload 保留。尚无 compile/quote 语义证明 |
| F2 部分 | `cost_model.py`：TOTAL/PER_BASIS_K、购买/承诺交付基准、同层数量加权缺失比例和成本界 | Windows 9 项、183 Python 3.9 9 项通过；纯合成计算，不代表72h/7d选样、成本组成、上界或0/18/25全域证明已验 |

正式分组登记在原 `tools/pr_fast.py`，没有新增 workflow。dispatcher selfcheck、`git diff --check` 通过。有效 D0/D1/原 D2 证据复用；本次没有宣称全仓、完整 pr-fast 或正式 GitHub CI 通过。

## 真实只读验证：只证明已读取的对象

2026-11-13 经原 187 访问封装与原 `127.0.0.1:8912` Admin 代理，候选模块只在内存执行；没有安装、导出、发布、保存商品或修改价格。依赖源码按 UTF-8 换行标准化编译；coupon JSON 使用原始字节，证据保存对应载荷 SHA，不将候选执行说成生产加载。

**关键修正：**11月11日订单查询未传付款状态时仅返回30条；现役代理不改写响应，追加原调用方使用的 `pay_status = 1` 后为839条。默认集合的具体业务含义未核；不能把省略状态叫全状态。实现明确沿原付款合同请求，分页核总数/ID/次序/日期，身份目录注明原生付款集合而非全状态、非原子快照。

从839条同日全站付款记录选出 MMOEXP `site_id=266`、FC27 `gid=1327`：

- 293个父订单，Admin USD **20,509.56**、Admin CNY **137,108.40**，无缺收入字段。
- 匹配281条发货成本记录，已观察采购成本 **¥103,608.47**。没有整单成本完整证明，293单的实际完整成本及毛利均保持未知；不能用该小计计算已实现毛利。
- 固定发布 `uw_1e37cd11ecac2a6b6468a720ef4fa5b8`，`data_revision=2460`，发布时点 `2026-11-12T04:18:26.082665+08:00`。固定归档 SHA `b335d7e41120cbde5581e4ba75f865cd2c9cd5f86495bfafe34efe25beeaa6fd`。
- 242条归因桥接，51条订单状态修订不同而留为未关联；另11条归档行未在该原生付款目录中匹配，不能说它们均属于所选FC群体。归档旧字段未提供有效渠道，因此293单仍在 unknown 桶，没有拿非空样本放大渠道份额。
- 六个FC Goods：PS 163329309/163329311、XBOX 163329275/163329277、PC 163329343/163329345，ALL/site266 身份各自核对、每行15档。仅验证读取和保留，不验证自定义量、舍入全域、非线性保存、传播或 Order 投影。

原始私有订单不入Git；仅保存脱敏聚合和来源版本。详见 `evidence/d2-integration-live.json`、`evidence/f0-native-reader-live.json`、`evidence/integration-validation.json`。

## 失败、修复与证据边界

- 187系统 Python 缺 requests；Hermes 容器未挂载 collector 模块。均在取数前失败，未安装依赖；最终直接复用原8912代理的标准库读取路径完成。没有工具自动审批拒绝。
- 初次本地载荷准备错指依赖目录，远程输入文件未生成，未执行；修正到现役基准源后完成。
- D3 复核发现新模式忽略刷新按钮；已修正 `refresh=1` 不进入缓存键，完成后60秒内或共享槽忙时保留当前结果并说明延期；202轮询不反复携带强刷。
- SEO Windows旧依赖使用系统默认GBK，普通 dispatcher 子进程未继承父 `-X utf8` 而导入失败；仅测试启动器补子进程 UTF-8、使用既有 tzdata，原网络/子进程隔离保护保持，未改业务代码掩盖。
- 整理时发现原文件混合换行；保留未改行原始字节，避免整个文件换行重写。没有因额度省略后声称测试通过。

## 续工优先级与真实阻碍

1. 主控核本提交及现场变化，继续 D5 的 connector schema/adapter、知识及 F5 唯一 `business_source.py` 接线。D4 的 `order_reader` 目前是明确注入点，生产 main 尚未绑定；不能把合成 runtime→Store→snapshot 通过当成自然夜间消费。
2. D2 的付款记录是当前读取、ES是固定历史发布；状态修订差异保持，不强拼修订。补可信整单成本完成来源，不能用发货时间窗完整标记代替。
3. F0 编译/报价、F4 非线性保存/传播/Order投影需要原生处理器或已有边界回执：自定义数量/步长/上限、非100折扣、购物车多件、舍入、低档到高档传播尚未证明。不得以真实改价试错取得这些证据。
4. F1仍有100K硬编码：Lootbar/U7/Arab adapters、quantity_scope、registry、coverage键、selective_sources、engine需要统一适配。现有fixture未提供大档响应，不能仅放开一个校验。183入口 `/opt/fs-fc-collector/code/entry.py`，187控制入口 `/opt/fs-fc-control/code`；renderer已有 `/opt/d4follow/_qd_render` 共享RPG目录，必须保护，当前未改部署或routing。
5. 原 publisher 装配须补新模块、D0依赖和前后端同批清单，并做线上组合文件三方差分；没有推送、PR、正式CI、合并、部署、模型消费或自然周期验收。没有激活新定价/新采集，没有恢复暂停报告。

两个并行助手收到明确 `You’ve hit your usage limit`，其后工作不能宣称完成。主控已保存可复核检查点；不把旧“小阶段停止”重新当成当前授权，恢复后按上述依赖接续，不重新盘点或重复有效测试。

## 重跑与隔离环境

新增 D2：`python -B -c "import sys;sys.path.insert(0,'tools');import pr_fast;pr_fast.units('releases/fs-dashboard/dashboard-refresh-20261025/tests',['test_order_facts_source','test_order_facts_runtime','test_order_facts_api'])"`。

FC：同 dispatcher 的 `releases/fc-coins/fc-pricing-v3-20261026/tests`，模块 `test_price_curve_v6,test_cost_model_v6`。SEO：`test_order_source,test_runtime,test_contracts,test_daily_snapshot,test_estimate`；Windows需明确 UTF-8 子进程及可用 tzdata。

183：`/var/tmp/fs-d2-integration-f15ef6c/work`，现有 `python:3.9.18-slim`，断网、nobody、只读根目录、0.25 CPU、256 MiB、128 MiB tmpfs，无生产挂载；27+18项零失败/错误/跳过。测试包SHA `c294328a663a6f2dcf103d0872c973fccd0c059428161fd550621767e48fef3d`。实际生产基础镜像未验。完整本地驱动和日志在工作树 `.agent_runtime/d2-integration-*`，不包含原始订单。
