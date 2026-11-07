# FC 双向定价上线验收

截至2026-11-07 23:45（UTC+8）。源码已合并、上线与首轮确认分别有据；尚不宣称稳定增利。

## 实施与发布

- PR902合并ce69e68a63590726700ac6c6d77b83d37012f452；固定载荷fc888038cbba0fc98fe14f0c6d1910d7b3bcc68e，正式CI42385866583成功。
- 主发布nav-20261107T153150Z：25目标、141保护项SHA一致，5个原服务active。原publisher备份/锁/回滚保留，未覆盖Sol共享入口。
- 两角色固定工件原子更新并健康；ArabUT gen13/v3、consume、每60秒最多8请求、并发1，原拒绝/冷却及历史记录保留。183原uid999、spool0。
- 知识发布nav-20261107T154100Z：33目标、83保护项及8条原加载路径available。新v3知识20261107-bidirectional-v2，财务合同仍fc27_dual20_d9_d2_v2。

## 原计划与首轮

原计划5cecacfd-19f7-584a-8845-16adbef9b13d保留ID和历史，rev1→2，ACTIVE；smart_started_at=2026-11-07T15:36:56.589500Z。所有5项资源归属同原计划rev2；无未决操作。

迁移自动首轮job为smart-strategy-migration:5cecacfd-19f7-584a-8845-16adbef9b13d:1:initial；23:40:01原操作a7dc24c8-40a9-546f-a475-c3c30e2b6c8e为COMPLETED，原步骤CONFIRMED、PUBLIC_CONFIRMED。双20通过，pricing_scope=100k_package_only。本轮A基准，Console和PC均A；这是启动轮，不冒称后一自然轮。

此轮已确认套餐基价Console $8.09、PC $8.93（购买100K另赠5K）；地区21三平台系数1。Console未改价沿原物理窗，新版本assignment按23:40确认计入；PC新窗从实际确认开启。该数字仅记录当轮，不是未来固定报价。

同轮ArabUT：183接受回执150c54401343437c8750097987232030，snapshot88aebd83-fa1e-5e83-b37e-02c37c8367da；23:38主机100K无赠USD8.37/Normal，PC100K无赠USD9.44/standard，PC原delivery=null保留。平台、币种、原SAR字段及来源时点都有回执，不把主机价复制给PC。

独立小时outcomes首任务23:39完成updated，版本绑定rev2/v2；实际查询完成、无非范围时间缺口，当前新试验样本0。下一自然轮固定为2026-11-08 00:36:56，未随首轮完成延后到00:40。

## 验证与边界

183采集127项通过；业务Linux349项通过，输入装配失败修复后仅补测受影响项；Windows三个Node相关用例通过。根因修复覆盖跨小时完成、原revision幂等迁移、退款编码保留和跨日迟到成本。真实wulv页面加载新角色、PC独立标准与原60分钟开启状态。

共享Sol与日报/月报暂停由“优化FS经营指标读取与展示”唯一维护，PR901/903线上回执已协调；本任务FC复盘独立固定验收请求fc_pricing_270fe220e40958f28dd7c154dca8ba18已提交，未重跑旧daily，不调用改价。实际模型回执待补。

后续自然小时轮、48小时有效对照、收益方向及长期可靠性尚未完成；订单/成本迟到必须继续按原样本回填，不将首轮0样本写为策略有效。

## 证据位置

本机任务.qa/fc-smart-bidirectional/的apply-main.log、readback-main.log、apply-183.log、apply-187-role.log、activate-collection.log、natural-initial.json、collection-initial.json、knowledge-readback.log、sol-review-submit.log。生产原备份位于/var/backups/fs-navigation-20261006/对应发布ID；原业务与模型回执保持原ID。

知识收尾KL-2001022625084b2d3b0f4f25取代未执行的早期候选KL-ad9ccbb8d6393819be0b0513；同一有效变更记录完成原两Notion页摘要追加，人工正文与历史保留。

## 后续读回（2026-11-07）

PR904正式CI42387875545成功，合并01e8fc5e16cca8ea71b28f7b4f582ce76168db72；单JS静态发布nav-20261107T155100Z完成，1目标和85保护项读回一致，仅nginx校验/reload。真实页面显示Lootbar主锚、Arab-UT次锚（主机Normal/PC标准）、ItemD2R辅助，原60分钟运行及23:40公开确认可见。

原FC Sol验收turn e54c0c7270ec411c885bca010d65bc89、native run_a89d2d8969fd44f4a53db4c1f6adec0e已completed。13次实际provider调用全部succeeded、response_model=gpt-6.1-sol、Responses/high及供应商回显一致；输入1,355,534、输出11,518，合计1,367,052 tokens，实际费用未核。3次知识读取有具体条目回执；未逐条复核返回revision/hash，不把准入pin当全部内容应用证明。

复盘正确区分11/6背景361单/$23,527.80、旧3247条绑定与新版本有效样本，未以影子预测认定增收。但state/read_quote返回400、ES结构503，缺当日同单毛利与A/B/C完整证据，故完整业务读取未验收通过。定价400由本任务排查，ES503交共享经营指标任务沿同turn原事件核对；不重发模型，不因此改参数或降低自动化。

## 真实入口发现的读取修复（待部署）

- Lootbar原run已验证USD且price_basis为“当前无券商品价”；coupon_excluded=false表示原站没有当前券，不能改成true。server_quote_job在验证后投影漏currency，导致新锚点严格校验拒绝。只保留已验证的币种字段，SAR/缺币种仍拒绝；历史报价不作新报价。
- 正常state约3,787,169字节，30个完整operations本身约3,345,695字节，超过原native1MiB限制。review-state仅把operations换成含原operation_read指针的摘要，原完整state/明细能力与上限保持；state/sprint_target及授权execute内部状态读取一并修复。
- 模型read_quote缺path、state多path现在返回明确invalid_arguments及所需字段；保存smart快照没有daily候选时返回available_modes，原SHA/身份错仍拒绝，不临时重算或冒充原日快照。
- 旧11/6复盘未记录actual_profit_summary，明确not_recorded；不补零、不重跑旧daily。
- ES503由并行经营指标任务独立修正原生请求误分流至旧Advisor，双方保持共享模型配置不动并串行发布。
