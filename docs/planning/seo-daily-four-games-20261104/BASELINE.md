# W0现场基线与口径补充

核查日期：2026-11-05，北京时间。唯一技术方案为 SPEC.md（seo-daily-optional-ai-r3-elastic）；以下是现场事实及用户本轮补充，不是另一套方案。

本文记录W0当时的只读边界和样本；后续用户另行允许了已展示的SEO候选合并、安装及读回。现役发布、正式30日覆盖和自然周期状态以ACCEPTANCE-20261105.md为准，以下“尚未”不覆盖后续记录。

用户已明确允许本次187/183只读核查。该授权不包含生产部署、改服务或业务写入。所有生产访问均使用既有本机入口；没有改变白名单、网络、凭据、共享服务或FC自动化。

## 当前维护源与现场

- 私库 wulv006-dot/FS-Workbench，施工基线051f784d65b239f572cd40b319b0e1c71cad0644；草稿PR #811，分支codex/seo-daily-four-games-20261104。Git基线不冒充部署版本。
- 已读取当前AGENTS、HOTFIX、OWNERS、SOURCE-MAP及UI规范。现场原历史工作区有他人改动；本任务在独立目录施工，未覆盖它们。未启用子任务。在途其它草稿#793/#589/#586未触碰。
- 新模块维护源：mmoexp_google_data/seo 与 ui-system/modules/seo。Google受控身份复用 details.collect_details.credential；直接Admin汇总复用现役 site_summary.collect。基础不经过Hermes进程、模型SDK、Key或健康检查。现役纯FS帮助文件位于含hermes名称的历史目录，不意味着要启动模型进程。
- 187：Linux3.10，Python3.9.18，SQLite3.7.17，systemd219。现役range_api.py SHA256 6cce30f18d285793dff36420b6d781ab751aed463308e05d22f7ff56cb8c46dd；Google collect_details.py 1bd3e06231235696623a5bee18c1329093ef4b2d8b263f92fc6fcdf76aedf1d7，与Git维护源有局部差异，没有用旧文件覆盖现役来源。
- 现役native shell含workspace-native-20261006-37fe775358df；formal路由SHA256 28165bbd11393696a11a6f9e20df650e605fde122bc6f97d208e4056a026a9b2。current.json中的旧gateway记录不是整站活动版本。候选仅追加SEO精确路由/导航项，保留原文件与其它业务资产。
- 现有FS鉴权入口127.0.0.1:8895；SEO路径继承unified-business的view/edit权限。服务不信任客户端身份头，回查原FS Cookie会话；设置保存校验同站Origin及配置revision。没有新增成员角色或放宽权限。

## 四游戏真实绑定及源日期

站点固定266 / MMOEXP主站；游戏ID来自现役配置与Admin样本，不纳入卫星站或G2G/ELD。商品范围为对应主站游戏目录和gid下商品；未额外限定平台、服务器或商品类型。WowForever只使用独立gid1367。

| 游戏 | 实际Admin gid | 主站页面路径 | 已核实来源 |
|---|---:|---|---|
| FC27 |1327|fc-27|GSC、GA4、Admin原生汇总HTTP200|
| D4 |456|diablo-4|同上，不含D2/D3|
| Aion2 |891|aion-2、aion2|同上|
| WowForever |1367|wow-forever|同上，不泛化全部WoW|

GSC sc-domain:mmoexp.com，统计时区America/Los_Angeles。小样本查询10/28—11/04，四游戏各有6个真实源日10/28—11/02；11/03—11/04没有伪补。GA4 property541418940，时区Asia/Shanghai；日期、主站Host、Organic Search及四游戏落地页过滤已实读。GA4仍为provisional，后续夜间允许小范围修订。

## 用户确认的成交预估

GA4已有自然搜索购买事件，但transactionId实际为空，无法关联具体用户、订单及实收金额。曾拟将Admin订单标识用于外部筛选，被自动审批拒绝且未执行；随后仅读取固定站点/渠道/页面条件下已有GA4数据并在本机比对，确认标识为空。正常SEO流程不发送Admin订单或用户标识给Google。

用户2026-11-05明确要求暂用预估，并直接拉现成Admin客单价。因此基础流程使用：GA4 ecommercePurchases × 同日、同游戏、主站Admin原字段customer_price。没有重算客单价或建设新订单追踪。customer_price沿用后台原值，含义为付费客户均额；金额明确标“预估”，不称逐单核验收入或实际精确漏斗。缺任一来源留空，不补零。

| 统计日2026-11-04 | GA4购买事件次数（初步） | Admin客单价USD | 预估成交额USD |
|---|---:|---:|---:|
| FC27 |25|58.73|1468.25|
| D4 |8|19.50|156.00|
| Aion2 |7|147.95|1035.65|
| WowForever |0|0.00|0.00|

Admin原生汇总付款筛选pay_status=1、site=266、对应game；不是空来源订单自动归SEO。该价格没有用总额除订单数替换。GSC点击与估算成交额保持各自来源、日期和单位。

## 调度与资源候选

187为4核，RAM约15.25GiB；只读时可用约10.2GiB，磁盘可用约114GiB。FC pricing现有cgroup生命周期峰值约768MiB，现有保护未改。现役营销日更00:10，交易采集下个时点03:06，未发现必须调整03:20的具体冲突。没有创建四套定时器。

采用 config.187-calibrated.json 候选：基础独立进程、单并发、CPU最多1核、nice10；内存警告512MiB、弹性运行到2GiB、软件应急3GiB，给宿主保留6GiB可用；基础unit最终应急4GiB，仅作用于SEO。磁盘4GiB警告、16GiB运行区、24GiB应急，宿主保留40GiB；备份/恢复临时空间按当前实际体积动态计算且至少预留2GiB。响应64MiB为异常保护，连接15秒、无数据90秒；有进展的整体任务不受240秒硬限。采集收尾预留10分钟，发布截止06:30。上游真实限流与权限错误仍遵守。

这些是根据少量样本和宿主余量确定的有限候选区间，不是整夜生产压力验收。代表性真实样本在183禁网容器处理后：快照135168字节，基础数据/快照/验证备份共396522字节；69项测试及样本恢复峰值32364KiB，1.165秒。没有据此把样本峰值写成上限。Windows与Linux事实hash一致：2e06d1c0c6fc7df89171940062350b096dd3dd0837744295187f7eb780c32859。

基础数据、控制、AI目录分别隔离。默认事实35天，快照当前/上一份，备份两份验证后轮换；临时候选在互斥维护中清理。报告逻辑删除与物理占用分开，不宣称SQLite删除立即缩小文件。没有全FS VACUUM、主库重建、drop_caches或共享服务故障注入。

## 权限、采购与未验证项

- 无新付费供应商、采购、充值、套餐或模型消费。本次仅使用已授权数据读取。既有Hermes供应商、Search/Fetch能力和费用账本尚未完成增强层接线，AI未启用，不借余额推断消费授权。
- 独立SERP、页面URL清单尚未配置，页面如实显示；不模拟排名，不用DeepSeek研究替代Google固定条件名次。
- 30天正式初次回填、生产独立timer、登录真实入口、生产资源/日志峰值和自然周期尚未验；183的Debian及SQLite通过不自动证明187旧SQLite兼容。
- 生产合并/安装需另获授权。本次只读授权不包含部署。基础发布候选和相关测试继续完成，不以可选AI缺口停止施工。
