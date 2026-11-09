# FC27三页正式交易验收

2026-11-09。当前已完成实价、平台身份、原购物车带码、三页共用码和Items范围修复。最终发布版本24及原操作详见下列回执；首次自然周更和支付履约分别待验。

## 当前规则及结果

- 正式URL为 https://www.mmoexp.com/events/Weekly-Scout.html、Sbc-Companions.html、Player-Trio.html。187托管由原主站路径代理，浏览器在www同源中调用原Cart/add并带pending_discount_code到/Cart.html自动Apply；不从IP页面搬会话、另建跨域传码协议或修改主站订单服务。
- 31个选中模型、93个唯一平台商品，三页共有99个页面/平台组合。主站原目录读取的93项商品身份和价格与当次Admin全部一致；公开快照＋原价缓存＋原生绑定的99项检查通过。PS/Xbox/PC分别映射自己的goods_id，PC差价已真实浏览器验证。价格为当次USD，随主站更新，购物车最终金额权威。
- 三页统一FCSCOUT10/Discount6049，配置benefit_refs也统一6049。site266、gid1327、cid=['2']，保留pay90、UID0、原时间窗。Items2覆盖Players、SBC、Packs、Evolutions；Coins顶级Gold1排除。旧FCSBC10/FCTRIO10只兼容已带出的旧链接，亦收紧同范围，新三页不再带出。
- 原生Cart三页独立正例通过：Scout PC 2.06−0.21+fee0.35=2.20；SBC Xbox含核心服务及两搭档64.35−6.44+fee1.98=59.89；Trio PS52.77−5.28+fee1.68=49.17。这些是记录时快照，不是新报价。
- 范围收紧后的同PS三页合并正例：7个不同商品（每周好卡1、SBC核心与搭档3、Trio3），统一FCSCOUT10自动Apply；实际商品总额122.64、优惠12.26、支付手续费3.50、总额113.88。三页连续加入均保留原购物车商品。跨平台组合沿原主站规则，本轮不修改其兼容行为。
- Coins反例：原站100K+赠5K，基价8.31；三枚码逐一返回discount.index.status0/Invalid Code，优惠0.00，总额8.85含手续费0.54。金币未被误打折。所有测试均未下单/支付，原空购物车已恢复。

## 根因与最小修复

新模型原来仅identity preview卡；FC页未消费原万圣节native_catalog/model-options，producer/cache及发布选项仅覆盖seasonal。现按完整ref＋platform精确关联原生商品，保留preview_only/available边界；报价和购买审批独立。真实旧Kane/Mbappe映射缺group，已根据原站93项证据补入配置；报价组合可不含group，加购只用真实product.group，缺失禁买、冲突拒绝。

发布仅投影当前页面选择的native bindings，完整私有策略和历史保留，错误aid仍拒绝。新模型的交易清单可从原周更ID只读查看/下载；候选不自动开通checkout。原ID保存/发布回读先查原回执，不再被长报价刷新阻塞；新操作仍保留原刷新、CSRF/角色和writer。

三条活动码原status0，真实Cart拒绝；按本次用户修复要求，固定原ID账本恢复status1并读回，未新建码或变更九折/游戏/UID/期限。收紧Items时6049原生明确code1并读回cid字符串['2']，因int/string差异原账本曾unknown；只按已核分类ID域规范化做原UUID reconcile，不再POST6049，不改原请求/审计。另两枚只派发各一次，三条最终confirmed。

## 源码、部署与回执

- PR945：2eba92f，正式CI1819/42589361564通过，merge435bbcd。交易/价格/URL主修。
- PR946：216baae，正式CI1820/42591600771通过，mergee79ec5b。真实发布范围和group合同补充。
- 原ID恢复补丁d2739ca/PR948，15项本地相关回归通过；与最新独立主线合并后的head0aa4195，正式CI1825/42596619724通过并合并。
- 初次nav-20261109T090000Z因未恢复原fence会暂停的business-range而激活失败；25文件已完整回退，服务恢复，原journal为rolled-back。明确核完后新尝试nav-20261109T091000Z成功；其后nav-20261109T091400Z三目标、nav-20261109T094600Z单目标成功。每轮原锁/CAS/备份/回退与在途任务检查保持。部署细节见manifest及回执，最终文件哈希和三个服务读回另列。
- 私有策略安装4ee6724a-5edc-4be2-b277-0967d8dd64c1；共同码策略7b442d72-c030-4b4c-871e-c71765d5e568；原值备份及原回执均保留。最终policy SHA16e1681da0b4124766dd64d7184235f03a7ae9349ee8a8f6f058804f7f569572。
- 草稿20发布21原IDcf9ce7d3-4f47-4c25-b180-69f1068a2764；共用码发布22原ID384e93cd-fb1a-4784-b8a2-89a952a0fba4。统一benefit_refs后保存23、发布24，原ID9580fbdf-34c6-49c0-a3a2-f10729d0d51c，回执与公共版本一致。原草稿除三页benefit_refs统一6049外完全未变，人工素材/文案、其他活动及万圣节配置保持。

## 验证范围与边界

相关后端45项、前端18项、原生浏览器、运营台22项、URL21项及编辑器浏览器通过；真实形状追加14＋6项、回执恢复15项通过。正式CI不由上述离线测试替代。Knowledge closeout沿原入口，affected_ids为空时不写Notion正文。

自动周日12:00 Asia/Shanghai计划保持原revision1、原委派与原ID；自然周更尚待11月15日。主站原生购物车/自动Apply实测不等于支付成功或履约完成。FS历史release_id仍使用campaign-preview前缀，交易能力以已批准native_checkout及真实Cart回执判断，不以名字推定已支付。

## 最终完成读回

最终公共发布 campaign-preview-24，operationId9580fbdf-34c6-49c0-a3a2-f10729d0d51c：三页当前benefit_refs均仅Discount6049；所有FC native bindings均仅FCSCOUT10。与草稿20相比，除三页优惠引用按新指令统一6049外，完整原草稿字段保持相等。最终实价快照再次验证99/99页面平台组合可报价并有有效购买绑定，93唯一商品；三码最终cid=['2']、gid=['1327']、status1/pay90，各原范围操作只1条native response，confirmed。

共用码和Items范围均由用户本次明确确认后执行。后续Hermes只生成草稿和审批候选，不自动改优惠码范围、生产策略、公开发布或启动新计划。测试购物车已恢复空，未提交订单或支付。自然周更与支付履约仍未验，不能从上述购物车成功推定。
