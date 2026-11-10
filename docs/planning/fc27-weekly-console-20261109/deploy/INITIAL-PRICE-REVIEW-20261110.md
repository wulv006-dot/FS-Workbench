# 首次取价与发布确认修复 · 2026-11-10

最终结果：代码修复已合并、部署并核对真实入口；用户明确批准草稿32后，已沿原工作流安装新映射并正式发布为33，发布回执已读回。月最佳首项、三页默认空购买清单、三平台价格与10%优惠显示均已实测。

本轮修活动页面价格刷新和周更预览入口，并按用户追加要求取消三页默认购买选择、将October月最佳SBC准备为首项。保留当前公开版本31，不重新取品；仅通过原编辑器准备置顶草稿，真实交易策略安装及活动发布仍保留最终确认。优惠券、主站购物车及计划不变。

## 现场与根因

- 用户原运行 `cb68516a-b529-4d84-9f5e-2b857559ca36` 保存30成功（2026-11-10 07:14:46.352 UTC），交易候选 prepared/can_publish=true，但发布确认没有完成 review 落盘。真实纯预览稳定复现 `INVALID_FC_LAYOUT`：历史 dormant SBC routes 被原样传给预览投影；正常发布会先走原布局规范化，故两入口行为不同。
- 当前31来自原 center publish `d357867f-ec2b-4ab4-ba7b-8bf31765a785`，时间08:33:44.212 UTC，是现场后续操作，不是本轮修复发布。公开指针为 `campaign-preview-31`。现役服务及策略先只读核对，不重放该操作。
- 页面首次仅读取一次公开配置，原价格缓存未就绪/已过期时不带有效报价；后台缓存随后恢复不会触发页面重取。点击 Review 会重新读配置，才出现价格。原到期定时器也只重画旧配置。隔离测试可复现该路径；无法重建用户首次打开瞬间的缓存。08:42:04 UTC现场缓存为ready、release/hash与31匹配，不能据此断言此前一直ready。

## 最小改动

共享 pageSeed 复用原 validateFcLayout，覆盖 workflow makePreviews 和 center 私有预览；只规范临时投影，不回写或删除历史草稿。回归保留9核心、18搭档、禁购和无落盘边界。

页面缺有效原生价格时自动重读原公开配置，采用1/3/8/30秒封顶退避间隔，持续缺价时以30秒间隔等待原来源恢复，ready后停止；报价到期重新读取。隐藏页暂停重试，返回后恢复；核对忙碌时延后，过时响应不覆盖新请求。读取失败不回填过期或跨版本报价，核对/提交期间保持原交易保护。

三页推荐卡仍展示，初始购买清单均为0；用户主动选卡后才可核对，SBC主动选择代做才加入服务。切换核心清除搭档购买选择，已选搭档换人保持该位置的主动选择意图。SSR同步空清单及未选择按钮，避免脚本执行前出现旧默认购买状态。

原编辑器设置默认核心时同步将其移至sbc首项，其余顺序、搭档/备选及缺省页面选择保持。目标为普通SBC `model-266-1327-45542393`（LALIGA POTM October）。另外只读确认普通Gabriel `45490809` 和该新SBC在现役旧策略中没有真实admin商品/报价合同，新未安装核价候选已含三平台映射；该缺价须经原确认安装，不能靠前端重试或等待缓存掩盖。

## 验证与交付状态

- 后端10项相关回归通过：私有参考价、9核心/18搭档及dormant route、原禁购/无落盘、workflow HTTP。
- 首屏无价的原代码红测复现；修后三view推荐卡自动恢复通过，前4次仍无价、42秒后ready无需点击，初始合计始终0；主动选卡后计算真实选择。报价到期按新原价更新。ready后不继续重试；核对忙碌期间跨到期不追加请求、不重绘选择。测试金额均为隔离fixture，不是经营报价。
- 原native-model三平台交易fixture、fc-published/read guards、native-page59及英文检查通过，语法和diff检查通过。没有真实加购或付款。
- 三页空选择及SSR、主动选择/取消、原平台交易/未知原ID、生成物一致性和原编辑器默认核心前置回归通过。设置默认核心后，保存请求和实际草稿仅更改defaultCore与sbc顺序，原四组合升级回归保持。
- 最小生产范围为activity.js、production-server.mjs、products.js、4个公开HTML及110项static manifest（只更新activity.js与4HTML的5项哈希）。构建源与fragment/validation生成物同步入Git，它们不在现役公共静态清单且原生产入口不引用，不虚构新部署路径。复用原publisher锁/CAS/备份/回退；仅重启受影响的dashboard与runtime，使后台入口和启动缓存的公开JS同时生效。原producer自然预热可能短暂缺价，须实际等待自动恢复。

正式CI、部署读回及真实入口结果将在同一记录补齐。原失败页面截图及当前31元数据位于本机 `.agent_runtime/weekly-console/` 和 `initial-price-review-20261110/`；完整业务配置、策略与凭据不入Git。

## 已部署与实际入口

PR969正式CI1863成功；主分支期间前进至6830ac2，旧合并因behind被拒后正常同步，CI1865成功并合并为34fe321。CI1862的唯一失败是测试时钟在并发环境漂移509ms，越过299ms有效期余量；固定测试时钟后精确断言保持，生产代码未为此改变。冻结7个生产源字节与最终CI head逐一一致。

原publisher将精确8目标部署为 `nav-20261110T091222Z`，备份同名。manifest SHA `2c871a0f950389336b3e48394a289aa3fb31c8218f8532f6de5fb416d9e5a375`；8after匹配，45保护项中44保持，唯一center变化是随后原UI保存32。dashboard/runtime新PID18772/18791，marketing仍817，未执行Nginx/range/Hermes/timer动作。原价格producer于09:13:13 UTC自然ready（启动约48秒），无手动刷新或旧价回填。

实际SBC新页先缺价，随后不点击平台/商品按钮即恢复Doku/Senne价格；清单始终0、合计0、核对禁用。Weekly/Trio实页均初始0；Trio主动选Jude后1项、取消后0项，未加购。公开31仍缺9个未安装策略的模型，不能把cache ready当成所有商品已可买。

原编辑器一次保存置顶草稿32：operation `6e489e22-6888-4702-aa9d-b98b6c8bc8c0`，October第1项/defaultCore一致；64模型和其余草稿hash `770e70b80be69b1645ce18fa06060790a532aabcc5c33c5fe26dbcc212652b3a`保持，公开31/旧policy保持。原run `cb68516a-b529-4d84-9f5e-2b857559ca36` 的真实审阅现已成功，可预览三页及进入最终发布确认，未自动发布。

私有预览确认October已默认选中、Gabriel有新鲜参考价，但菜单顺序仍受page.product_keys影响，暴露第二处关联遗漏。`projectFcCatalog`仅将已通过page/role/platform过滤的SBC核心按fc_layout.sbc稳定前置，保留未排序的原成员和其他页面规则。私有/公开同入口及过滤反例13项回归通过；该单文件补丁的正式CI/部署和最终菜单首项须继续核实，不将默认选中冒充顺序已正确。

## 菜单补丁与版本32审阅

PR973 / 正式CI1867成功，合并39f82d0。单文件原publisher部署 `nav-20261110T092718Z`，manifest SHA `f90a55f2b8826e6a649ae9c830f0b83b8bf08402fd2e1635379aeda3131fa00b`；presentation after `97bc32d012c0bf8a35b965e010a9341d77d06f8e0a32c6ae86552b659efe5514`匹配，52/52保护项无漂移。dashboard/runtime PID26702/26721，marketing817保持，静态manifest不变。重启后第一次管理页GET超时，正常重载恢复；没有重放草稿保存、安装或发布。原producer于09:28:11 UTC自然ready并匹配公开31。

原run正常重新审阅32成功：review `94351c89dff881ea3f5904e383cfe2017be27f098a77b96c7bdf0199a978abc2`，proposal `a6b1cf45-6351-494f-b099-e9dbdcedf539`，can_publish=true/blockers=[]，到期09:39:09.387 UTC。候选新增9参考价格模型、27商品、9报价合同及39绑定；旧1650绑定原序列逐项保留，新增均为FC27三页/new_items/FCSCOUT10/10%。这些是已核候选，不冒充已安装。

09:34:25 UTC补充核验：旧355商品值及映射完全保留，23旧合同仅catalog_version刷新、选项与映射不变；新增9模型各有PS/Xbox/PC合同，27份USD参考价均fresh、最早到期09:43:48 UTC。政策顶层仅admin_reference_prices/native_catalog/native_checkout的上述增量，其他值不变。完整小摘要在`sbc-order-projection-20261110/review32-proposal-summary.json`，没有重新准备提案或写政策。

真实三页私有预览均完成加载，初始清单0/合计0/购买禁用、各4包。SBC菜单第1项且默认项均为LALIGA POTM October，核心仍9名；普通Pedri/Gabriel参考报价可读。Weekly/Trio各3张现配置球员报价可读，未更换用户本期取品。预览仍禁购，不能把原价参考显示当成实际核销成交。

09:35前的候选阶段未执行真实发布：已向用户展示截图并请求确认草稿32，当时公开仍31、策略仍506a9a…。证据含`draft32-sbc-ready.png`、`selection-before/after.json`、`live-sbc-cold.json`、`live-sbc-warm-no-click.json`，以及两个独立stage的inspect/apply/postdeploy结果。

## 用户确认后的正式发布33

用户明确回复“确认发布草稿32”后，在原UI一次确认发布，未重跑取品或保存。原run仍`cb68516a-b529-4d84-9f5e-2b857559ca36`；原publish operation `ded31c86-4cc1-4045-acbe-9f162857545f`于2026-11-10 09:36:23.816 UTC成功：

- release `campaign-preview-33`，center/public revision33；workflow completed、原center操作回执和发布readback verified/current一致。
- config hash `753aad63488662a01388cef6efe903f04f77f942420787a2573c29de4e0ee75f`；rule hash仍`5411324c1cc95235b46d17b92a06ce9aaa3ac993507e7f22ec917b66269326c4`。
- policy安装回执installed，当前SHA与已审阅候选`e514c0769b87c6f035fe8ec5eee04377860ba12d491898dd719fc1c900a26a16`完全匹配，原506策略备份SHA核对一致。绑定1650→1689，原记录不变。
- 发布draft与保存32完全一致，64模型保持；31→32仅默认核心和SBC顺序两个字段变化。原三工作单沿本run关联至新版本和回执。
- 原producer自然生成ready缓存33于09:37:22.987 UTC，316个fresh USD产品/77合同，release/hash匹配33；每平台Weekly7/7、SBC31/31、Trio7/7全部fresh，没有以31回填。

真实公开三页×PS/Xbox/PC共9状态均0件/$0.00、核对禁用、唯一3平台控件且无横向溢出；7张可见卡每页，排除3次已拥有核心后60张价格的10%及美分舍入自检通过，没有Price unavailable。SBC三平台主动选择代做均1项，合计与该核心优惠价一致，切回已拥有后恢复0；未点击原购物车加购。正式SBC菜单第1项/默认均October，普通Pedri/Gabriel均有原价、10% OFF和优惠价。

源文件无额外漂移；52保护中仅policy/center/public三处对应本次已授权原ID发布，dashboard/runtime active、marketing817保持。未新增优惠券写入、社区消息、计划调整、加购、订单或付款；自然周更仍未验。本机证据：`publish32-original-receipt-readback.json`、`postpublish33-source-price-readback.json`（sbc-order stage），以及`published33-receipt.png`、`live33-three-pages-initial.json`、`live33-platform-matrix.json`、`live33-sbc-final.png`（initial-price stage）。
