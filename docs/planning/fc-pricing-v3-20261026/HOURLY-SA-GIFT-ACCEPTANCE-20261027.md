> 历史记录：本文旧全目录、全套餐或全整数K门槛仅对应当时合同；已被2026-10-29用户确认的100K购买+赠5K双20基准覆盖，不用于当前定价。当前Saudi破线归1、英国系数1及冲额底价规则见[现行合同](DUAL20-NO-BUDGET-CHANGE.md)。原数字、版本、错误及回执保留。

> 后续修订：用户已撤销ItemD2R礼包等值假设，现按实际100K。当前两模式与单次基础价验收见TWO-MODE-SIMPLE-ACCEPTANCE-20261027.md。以下仅保留原时点证据。

# 每小时、沙特缺价与礼包等值验收｜2026-10-27

## 当前生产与验证

PR542 merge5695cb53beceb7906c789b58ca960abfef3737dd，正式CI40432627081/job121953723527，234项FC检查通过。原publisher nav-20261027T013200Z备份发布12个目标，manifest SHA10bb839e1b057813d38b625c9b71109434f8a27f069d51b9c690b36d3763d9a5；包SHA144d765ee4a8396a7b2e5d22f52b66f9aa22dcaac09cde6f3c84b5a42ae8bd7b。09:37:05生产91/91目标SHA与该commit一致。

09:04通过原页面保存采集/执行间隔60分钟，政策revision42；09:34服务器读回原计划ACTIVE/revision2/60分钟，下一自然10:04:33.702206。发布保持该排程与原22:30截止，没有新建计划或手动追加业务写价。

## 用户新增口径

- 沙特对应平台没有可核、同轮有效的Arab-UT普通报价时，保留原因，以regional_follow_global/SAUDI_MISSING_QUOTE_FOLLOW_GLOBAL将授权地区系数设为1跟全球价。已有规则按原写入链修改；原来没有规则、系数1的真实继承使用全球完整财务基准，不虚构独立地区舍入或均值。全球Lootbar/ItemD2R、成本、汇率及双20仍须合格，不能借此使用假Arab报价或跨平台复制。
- ItemD2R Bonus Pack按用户指定的初始假设，参照同平台同档Lootbar赠送K估算金币等值。原100K、raw bonus0和金额不改写；比较投影保存actual_coin_bonus_k、等值bonus/delivered、gift_equivalence_assumed及版本user_lootbar_same_tier_v1。已有明确非零金币赠送不再加一次。资格标识包含假设版本，原历史证据和实发金币训练标签不重写。
- 我方价格卡使用原catalog_floor分别计算未优惠及七日真实优惠平均20%基价下限，包含完整套餐/赠送/整数K及舍入；成本沿原Console共同池、PC独立、CNY/USD。展示原成本时间，卡片是全球基价参考，地区与实际执行仍完整联合证明。

## 同一真实冻结源复算

原snapshot cfd497f9-3f43-550f-84df-5182b1ff7d5b，来源实际时点07:14:25；新旧真实输入不重采。修正口径后READY，45个完整双20候选，所选为两个地区步骤后一次base，现有writer即可；PC财务底价兜底明确保留，不能称全部达到低竞品5–10%。这些是历史输入验证，尚不是新鲜来源或生产执行成功。

较早按Item无等值赠送的输入曾验证存在十步路径，但这不是当前新口径所必需的生产改造；没有将额外多次base保存直接塞入旧运行器，也没有放宽中间状态检查。

## 真实页面读回

登录页已显示我方三卡采购成本、含赠套餐成本、未优惠红线与七日平均红线，数据明确为07:14源。PS/Xbox分别为$0.0476/K、105K成本$5.00、全球两底价$6.46/$7.03；PC为$0.0536/K、105K成本$5.63、两底价$7.24/$7.89。这些只记录原时点数据，不作为现在新售价建议。

Item原套餐$8.14/$8.15按100K+5K礼包等值分别显示约$7.75/$7.76每100K金币等值，并明确“含礼包估算”。PC Arab卡显示缺价跟随全球，没有假价。页面实际60分钟、下一10:04，无错误。原Hermes全文换行与深浅主题修复保持；窄屏设备实测仍未完成。

## Hermes正式教材5与实际加载

PR543合并62072935eb080f6e1e858da802deefb3ba6d9620，最终head824ea1908d8f52e54b4af2c4004ad434239c5414；CI run40434119135/job121958760329，234项FC及87项知识检查通过。原publisher nav-20261027T014800Z发布17个明确目标，17/17实际SHA一致，businessWorkerTimerActions=0，未新增业务写价。

发布manifest SHA `bc0ec49eaf8aca4fb945eb7361f0a429d6f133c66695687d79a6e65bdbb3bf1b`；目录 `knowledge-releases/fc-pricing-v3-20261026-5/index.json` SHA `d551167fb46ae698d0ef01d637c1c0d88689261b9a42fd9b7f8f00e7ea5a99f6`；完整基准 `490229771a5949a35108b842007667fb5cc414763cedcd26123ce0d2dbcf3654`，加载政策 `8e7d124c4736d2da83d485a39f8f63c155e7d4bc600f4a4cadc044972af93cc2`。

正式wulv/FS/fs数据任务实际选择available、13条、26724字符、含fc.pricing.v3，选择SHA `f61ba98eb503a9056213b1dbc2fc60af8fe778d7baf3eb18368d7bb5df3e7e6b`。原13条路由及其他模块规则保留；教材包含60分钟、Saudi缺价跟全球、ItemD2R礼包等值估算和成本/双红线说明。Notion原页3ff9a8a7-9c4e-81bc-8a4f-eb15aab87a5a、同同步编号FCV3-RULESYNC-20261027-01已定点更新且无警告。实际装载不是模型已完成新规则复盘，今日没有追加第二次模型。

以上凭据私有保存于apply-knowledge5-6207293.log、knowledge5-current-live.json、knowledge5-selection-live.json；原发布回退journal及目标备份位于 `/var/backups/fs-navigation-20261006/nav-20261027T014800Z/`。

## 自然轮仍待验收

10:04自然轮的新鲜采价、候选、实际后台执行、缓存及公开读回须单独取得，不把本页或READY当写价成功。Hermes新教材和规则同步使用下一知识版本独立记录，不调用第二次今日模型。首轮03:10、UK04:07、原失败/UNKNOWN、两个旧自然INFEASIBLE及历史现金/地区/成本缺口均保留。
