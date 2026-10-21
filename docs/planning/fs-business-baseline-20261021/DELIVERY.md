# 业务基准与工具修订交付

2026-10-21。最新继续教学交付见[TEACHING-RESULT.md](TEACHING-RESULT.md)和[两套定价策略](PRICING-STRATEGIES.md)：Admin恢复后今日真实查询已读回，限定新场景五项判定及完整条件策略通过复核；原失败保留，整体泛化与经营收益未验证。下文保留初批次代码/发布及教学时点证据，不把PR或文档当上线。

## 代码与发布

| PR | 合并提交 | 正式PR fast | 范围 |
|---|---|---|---|
| 260 | 38b1094a0676c2c3792f57fd1c8c32a18b16ee76 | 39538522076 success | 业务基准、渠道映射、原工具/输入/只读预览与小幅UI |
| 261 | 3dc15db0334ed7f96ac4271f6abc65b2794c65c5 | 39539022445 success | 精确location改alias，保留旧不可变入口 |
| 262 | 65a0aa6ae0f312190e7f53c5ce736b87748b0118 | 39541825306 success | 归档复算保留原采集时间 |
| 263 | 9fb41c8e8f755e1942d3432fb4a33a412856d679 | 39543221168 success | 已为.99的高价套餐不再误降整美元 |

活动文件逐项见[SOURCE-MAP.json](SOURCE-MAP.json)。使用原冻结publisher、准入/发布锁、CAS、备份、两FS服务重载和回退；未新建发布框架，未重启Admin服务，businessWorkerTimerActions均0。

| 实际备份/发布ID（UTC） | 目标/保护 | manifest SHA256 |
|---|---|---|
| nav-20261021T035838Z | 16/387 | 317adb95b644dca1822c305e53b9c751baa7b63f7a7dc9e1c1cb78a8c2a00627 |
| nav-20261021T040536Z | 1/402 | e0071160cf9f50f8db5faeeb6bdfa989688c97747fda91645ec3fb1a9c9543c7 |
| nav-20261021T042040Z | 1/402 | 45c2ad989d7f7fb3f1ab1510b1406075cf2e2163af67a374d934c4dd3216c657 |

最终04:40:22Z独立只读核对最后目标与402保护全部匹配，fs-business-range/fs-hermes-fc active。原引擎、automation.json revision38/SHA02dbbb76…、采价周期、开关、利润底线、writer与售卖链保持。历史manifest未修改，退役publisher保持退役。

此前等待的DY原日报c10ef…44385171自然FAILED/source_timeout、task_id=null；没有取消、清状态或重发。随后发现运维Admin unit变化，旧staging在inspect阶段拒绝、apply-intent未创建。核实仅镜像tag变化后保留当前unit d500bbf5…，另建新manifest及staging；不据旧基线覆盖运维修复。

## 实际变化和入口

- 用户八条链路、两项确认、金额/游客/生命周期合同和尾价偏好汇入[当前业务基准](BUSINESS-BASELINE.md)。.99允许幅度按成本/毛利计算，10.09只是示例，四项预算是本次保守控制而非用户逐项给定阈值。
- 373码原表未修改；推广分类与原source/站点分开。分类在私有数据丢码前完成，模型不接触原码；未命中、无码、源未保留分列。不把分销标签认定G2G/ELD，不据码证明因果ROI。
- 原ES工具、schema、数据专区细分控件与Hermes提炼链接通channel，复用原窗口私有导出，无新登录、导出或timer。旧会话未保留码的问题通过主机既有原档读取解决，不以旧host源码重建活动会话容器。
- 真实wulv工具入口读取原渠道档案，原捕获时间2026-10-20T16:00:51.825244Z已在页面读回。复算时间单列，缺原时间保持未知。其范围仍是原ES原状态，不冒充主站总盘、实收或净让利。
- 客单候选/历史只加原Order全状态精确sn复核链接，真实打开后status=all且sn对应，有原查看详情入口；无邮箱进入URL，无订单修改。生命周期与原阈值不改。
- 流量页GA4/GSC/Ads结构和源没有修改；表单、布局、主题及共享样式复用。真实浅色查询/状态和链接已验；本批没有另做暗色/窄屏完整视觉回归，不拿旧V2视觉测试冒充本批新证据。
- 只读模拟附加尾价预览不改变基线/主候选/writer。原价已.99的缺陷由Astra本地反例发现并修复。服务器运行源的虚构案例199.99保持、22.21/C18不凑21.99、22.20/C18可凑21.99均通过；不是实际报价或收益验证。市场过期时未绕原合格快照门禁制造完整模拟。

8项有意义的定向测试含多组断言，通过本机、正式CI和真实Python3.9；JS模块语法通过，原Nginx配置检查通过。新增时间/已.99反例只复测相关变更。真实HTTPS四个匿名入口在默认TLS验证下精确302到原__auth/access/且next对应，未扩大访问。

## 真实模型和教学

实际模型输入包含当前基准core_contract SHA093d51f6…，冲突旧业务输入为空；保留用户偏好、报告方法、正式经验和旧任务。事实仍来自任务工具，不把当前成本/价格写长期知识。

| 实际任务（短ID） | 行为与结论 |
|---|---|
| 64c1c020… | 实际渠道查询及证据分页；把结构比推成优惠机制，失败保留 |
| 324cb33f… | 实际读规则，但沿用跨任务旧ev，计算绑定失败；不能算学会 |
| 73762a4f… | 重取本任务证据后实际绑定计算；金额份额与核销率分开，反证仍不充分 |
| 42dfd918… | 新会话留出：交付成本、平台触底、保本量及stale拒新报价正确；把尾价预算套主策略，局部通过 |
| 64b0db8c… | 新参数复测纠正研究/尾价范围，实际声明情景计算；仍有单项阈值误当组合边界、采购毛利与广告后利润混用，局部通过 |

提供商出站high/thinking、响应ID、用量、工具和实际输入有回执；提供商未回显档位、backend unknown，不能宣称已证内部最高档。旧V2的max多轮回执保留，本批不重复耗费制造相同证明。不读取或导出私有推理。

用户指定的gpt-6-astra只做一次独立只读评估后结束，未委派施工。完整有条件参考见[ASTRA-REFERENCE.md](ASTRA-REFERENCE.md)，资源目录见[ASTRA-RESOURCES.md](ASTRA-RESOURCES.md)。它没有给具体新售价或声称实测最优。本Work传递核证/计算/反例的方法，再用未见问题检查，未把其答案粘进记忆当作Hermes学会。

学习事件d8430baf…由Hermes本人旧报告及2/2原模拟、2/3可投影记录复盘，单次high已结算；产生L1方法4eb2abc4…、content hash8f6e3d84…。人工审核后原manifest CAS发布成功，新manifest87cfa0ea…。新会话实际输入及knowledge_uses证明该方法被两任务加载；原69fb…方法保留，自动发布关闭。

经验可撤销证据复用原7774e244…的真实发布/使用/撤销。最终又只读核其published、revoked两原账本事件、一次原使用记录，并核本批新任务未加载该撤销版本。旧任务引用保留。**本批新4eb2…保持已发布，没有为了重新演示而撤销/恢复它。**方法生效与全面分析能力、因果效果分别验收。

没有把失败隐藏成模型自评通过，也没有把新虚构场景当真实业务报价。错误阈值、优惠机制归因和广告后利润结论未发布为经验。具体质量缺口见[REMAINING.md](REMAINING.md)。

## 知识废弃、Notion及边界

[Notion完整修订版](https://app.notion.com/p/3ff9a8a79c4e81bc8a4feb15aab87a5a)已写入并读回。旧冲突业务正文删除，替换为完整基准、废弃清单、Astra参考和真实分层状态；无关Codex附录保留。另更新项目中枢、客单和流量三页链接/补充，旧任务历史和未决事项不删、不自动关闭。读回见[NOTION-SYNC.json](NOTION-SYNC.json)。

真实订单、邮箱、财务样本及原始模型可见回执留FS/本机受控目录；代码库及Notion只同步规则、脱敏方法和验收索引。旧客户PLAN标为历史初版，不能再从加入日D1/逐客自动报告推当前要求。E原库无stage/commit/push/remote；不混入并行sales/Admin统一改造。

上述初批次曾读回Admin inactive/运维冷却，原时点证据保留。后续用户告知恢复，本Work只读核到ready，并由Hermes取得今日原生业务available回执，见ADMIN-READBACK.json；没有启动、登录或修改凭据。新鲜市场已更新但可比条件仍partial，仍未推荐真实新售价。自然周期、真实执行收益、分销占比、退款/CB结算及其它端点全链未完全验证。

安全重跑仅本地/临时输入测试：`python -B fs_business_baseline_20261021/test_baseline.py`。真实发布、模型、知识版本与Notion操作先核原ID、attempt、manifest及实际状态，不重跑本批一次性脚本。真实回退机制沿原publisher，本批未执行代码回退演练。

表单核对使用Modern Web Guidance的forms指导，沿用语义控件/原标签和状态；原文“DO use semantic tags like `<button type="submit">`, `<textarea>`, and `<select>`.”，没有新建表单框架或修改全站样式。
