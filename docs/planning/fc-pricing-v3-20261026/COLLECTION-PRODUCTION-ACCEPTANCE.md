# FC双节点采集生产验收（2026-11-03）

ArabUT已启用183优先、187受控备用，并通过首个自然改价周期：183新报价进入原187计划，Order明确成功反馈与Admin同SKU单位价均核实。ItemD2R尚未恢复，不能称为全来源迁移完成。

本页时间均为北京时间。机器原始证据保留UTC。施工源码只有FS-Workbench，没有183独立仓；183继续作为默认隔离Linux测试机，187是唯一FC写价端。

## 验收结果

| 层次 | 结果与依据 |
|---|---|
| 代码与正式CI | PR765 merge `5e3e5fdcc92d3d93e66a307e40dca9ad20ba994d`；最终head `e33108b66f5ecced98c6dd93fca96b15ee65d2ba`；CI41490594838 success |
| 原FC回归 | Windows635通过、11平台跳过；183固定Python3.9.18隔离118通过无跳过，正式生产源码随后未改 |
| 部署 | 新增独立FC角色+原publisher精确3入口；release `nav-20261102T175000Z`，manifest SHA `900233dade3ab9a3922a8365345cffebbd8bdfd3cbe9a006081d5d1a6c91ab5a` |
| 非业务真实验证 | 183正常3GET、187领取前接替3GET，均完整PS/XBOX；固定ID复读无新增GET/时间刷新；183服务恢复、spool0 |
| 开启 | 用户明确纠正为“启用”后，routing与ArabUT source均consume/gen12；开启本身无外站请求 |
| 自然采集 | 02:25:42，node183，epoch1/attempt1/3GET，PS/XBOX完整；v2投影逐字段等于原报价快照 |
| 自然业务结果 | 02:26:32，原operation COMPLETED；02:28只读复核Order明确成功，Admin PS/XBOX/PC单位价均匹配本次目标 |
| 原能力与隔离 | 原计划revision1/60分钟/价格规则/唯一187 writer保持；12个原受保护单元状态/PID/unitSHA一致，无RPG/profile/凭据共用 |

原计划`d61e30fc-176e-51cf-baee-d5cdae2cc3f4`；自然cycle `cycle:d61e30fc-176e-51cf-baee-d5cdae2cc3f4:1793643822:r0`。报价快照`cb238ce0-1ac1-5fe8-ad84-c21b0484a635`；采集job `c87f567a448e035e98e9060828fc35f962e64e03ac1805e646187703cc3308cc`；观察`2b26d3cebd334993bc34194b673dde3f`，payload SHA `b524056f8425985282ffd381a4b474e7e9eb191f19af5d466b938dc50237e783`。

原187业务operation `c5c3fe46-ebb5-569a-9c9a-5116bda9aa48`，同快照且base step CONFIRMED。Admin按gid/mid/site/aid精确查询：PS/XBOX每K $0.0755、PC每K $0.0765，分别与本次Order每100K $7.55/$7.65一致；这些是该次已执行结果，不是新售价建议。成功不额外等待公开页。

## ItemD2R的实际边界

187最近5轮首document均`itemd2r_cloudflare_403`；本轮自然快照仍相同。用户追问后，在183使用已安装镜像的新非root/只读/0.5CPU/512MiB/128tasks容器，无业务挂载或profile，先完成离线启动和200/302夹具；再执行一次单跳HTTP公开入口诊断。02:23返回403，Cloudflare标记存在，实际请求1，无重定向/重试/其他资源/报价消费。

传输为Playwright APIRequestContext，不能称原生浏览器网络栈或完整三平台采集通过。固定job `9991ba402134683b4857c78e722b0bf32d2e49be72f2a850bcbaff9382d7bf86`，payload SHA `2a71acdb6416a369fde5846f8753bbac4c3aa6981431fc5a861a25b4c4d591a1`；观察已接受、blocked保留、仅此新诊断来源off/gen2。原187ItemD2R与Lootbar实现未改，不把拒绝改成成功，不据此推断183所有合法访问方式均失败。

## 回退与未验

采集角色备份分别在`/opt/fs-fc-collector/code-before-collection-route-6d395242`和`/opt/fs-fc-control/code-before-collection-route-6d395242`。3原入口备份位于`/var/backups/fs-navigation-20261006/nav-20261102T175000Z`。首次发布因默认清单目录错误在写入前失败；核对原状态后按同清单/同ID继续，未放宽CAS/guards或清UNKNOWN。

紧急回退先在187使用已审`set-collection-consumption187.py off --apply`，先关闭routing、再来源off并增代；保留拒绝/冷却、permit、原任务、业务计划和全部回执。当前默认off预览ready/gen13，生产未执行off，不能称生产回退演练已通过。退3文件还须按原publisher及同manifest/原backup执行，满足原FC空闲与在途条件，不在拒绝/冷却期间恢复不受控请求。

本轮结束时新协调账本20次：原10、非业务验证6、Item入口诊断1、首自然周期3；全部10任务COMPLETED、原6失败/诊断回执保留。该计数不包含所有原187外站消费者，不能声称全站统一配额已验收。现场故障仅演练新增183服务领取前离线；在途故障、旧epoch等依据183隔离测试。ItemD2R完整浏览器取价、Lootbar的183独立登录态迁移及生产实际off回退未验。

精简只读证据见[evidence/COLLECTION-PRODUCTION-20261103.json](evidence/COLLECTION-PRODUCTION-20261103.json)。原始日志、一次性工件和完整回退清单保存在本机`E:\WorkBuddy\fc-dualnode-20261102`，不含业务凭据的副本才进入仓库。
