# 检索与默认文案增量验收

2026-11-09。PR942，源码412c185707ce3afd02811c79f807ac66c78cfb7e，合并d960de3983216e2887672451a296d796d820867e；正式CI pr-fast #1816 / 42585377655成功。

- 现役Search上限128字符，旧长查询本地失败。按真实长度拆完整姓名组，保持12次Search、8次Fetch、180秒；不增加预算，不把缺失原文当完整市场覆盖。
- 独立研究测试50.15秒，31人全部进入查询，12次Search/8次Fetch；取得4份垂类原文，查询长度98–122字符。仍有社媒及逐人覆盖缺口，status=partial。
- 清理SBC/Weekly默认旧人名、固定系列、获奖和化学保证；Trio中文动态取当前姓名。人工copy与自定义title保持，后台精确旧默认标题显示Player Trio；不删除真实商品版本Star Performer等事实。
- 相关48测、Hermes正式test_core356测、文案/SEO12测、英文和商品编辑器浏览器回归通过。知识收尾104测通过、7个平台适用跳过，affected_ids为空，无Notion正文应用。
- 发布nav-20261109T082600Z，备份/var/backups/fs-navigation-20261006/nav-20261109T082600Z；8源文件+1派生清单，38个现役保护项。原publisher/锁/fence/CAS/原ID保护，9文件SHA读回一致，3服务active。无业务worker/timer操作，无nginx重载，无公共配置发布或写券。
- 静态清单110项，仅Sbc-Companions.html、Weekly-Scout.html、activity-content.js、analytics-config.js、index.html五项改变。三FC页与共享追踪脚本HTTP200且保持共享追踪引用。
- Chrome管理下拉Player Trio、SBC默认正文与标题已读回为通用新介绍；保留人工可编辑字段原值。原草稿19的Scout/SBC/Trio图片均真实加载，标题换行时图片与按钮对齐。
- 新operationId fa02f31d-36b2-46a5-9365-ec8bf8852c2d已从真实FS入口发起，用于验收修正后的资料→Sol→草稿链；最终回执待下节补充，禁止盲目重发。

## 边界

原周日12:00 Asia/Shanghai计划revision1保持开启，授权operationId88540366-c0d6-4df1-afc0-0c3d4d56da7f。自然周更尚待11月15日；手动成功不冒充自然运行。
公共配置仍preview模式；本次未真实购买、核券或发布公共活动配置，不能称交易已验收。

## 最终真实 Sol 验收

- 原operationId fa02f31d-36b2-46a5-9365-ec8bf8852c2d成功，task 0ac575971acd447befa4493d4f619f4c，run campaign_f249fff333fd7f25b3a9044ae207a3ae。草稿19→20，当前20与原保存回执匹配。
- 模型请求/供应商回执gpt-6.1-sol，high回显；单次调用输入8404、输出4968、共13372tokens。费用没有账单证据，不按token冒报金额。
- 真实冻结输入包含4份外部原文来源和摘要上下文；model-input-proof.json记录来源和正文哈希，不输出提示词或会话。
- 24条选品＝Trio3、Scout3、SBC18；9核心各2名不同搭档，共享池全局18人。23项合同检查全通过，完整Newest池及普通版事实、三平台身份、主站Popular顺序、图片来源、公共配置/其他页面/人工文案/优惠/万圣节未变均已核。
- 新Trio模型ID 45490817、45490797、45490829；Scout仍43167707 Kane、43167389 Mbappé、44921285 Yamal。实际模型按当轮证据选择，不固定名单或卡系列。
- 外部证据partial：4份vertical、31候选，34项缺口（31逐人覆盖、1原文失败、1身份/赛季未匹配、1原文预算）。未取得有效社媒覆盖，不能称完整市场/社媒验证；草稿继续标记provisional并供人工复查。
- 首次自然周更、真实订单结账、真实优惠券写入和公共活动配置发布均未执行，不以此次手动草稿成功替代。
