# G1 集成交接（进行中）

工作要求 FS-V3-G1-CONTINUE-02；主控01a16d0c-2eb6-77bd-883f-4b1fc5a07010。本文不宣称G1完成。

## 候选与独立审查

原输入/源码映射和接受版本见SOURCE-MAP、SOURCE-INVENTORY及inputs清单。实现整合提交：B8e542c6/b08f34d，Cd0b0e6e/d0f2a93/ad90466，D07e7dc6/21447c6/a1afe57/a9df950，Ec0f2960/f609428。控制器集成ff48d734、5643432、ed3b392；0bc8176合并当前main ede67f6。

Q独立审查ff48d734及0bc8176，发现发布事务恢复、SDK阶段恢复、配置驱动呈现、主题覆盖标题、已拒绝prepare锁死。修复均有相关验证，ed3b392复核中。原publisher固定SHA5548d9c8未改变。

本地97Node/55backend/6publisher已通过，原pr-fast对0bc8176实际运行PASS；之后D跨页与Q增量修复的28相关测试以及FC/Seasonal浏览器通过，最终候选CI待跑。旧Matchday自动测试作为原模块既有回归保留，不代表新增本项目业务。

## 187现场读取

2026-10-24T09:49:57.4959644Z至09:50:00.8659569Z（本机UTC）；远端回执09:50:01.104674Z，exit0。PC-20260909OJLI经原Invoke-Server187.ps1，目标play187，命令摘要 /opt/python39/bin/python3 -，候选模块仅内存加载。共享会话复用，无新登录、未安装代码或写业务。

候选AdminRead/scoped_product/read_product_metadata对site266/game1327商品170014917、163329311真实GET校验通过。安全投影SHA分别fc369adb092dd123551d4aff5220e45fac41f93fdae042cd9c5eb74d99823952与eb7adbd4a14405f9241941c12e809da4b41257a2966cda0b40eeacdce02b1ef3；未输出价格/成本/客户或凭据。这是候选代码真实读证据，不替代安装服务和FS入口验收。

## 主站接入包入口

合同：模块runtime-contract.md、backend-contract.md、P1-VERIFIED-CONTRACT.md及原V3输入主站技术接入合同。

| 对接项 | 已备能力 | 对方必须提供/核对 |
|---|---|---|
| T01 | 独立loopback8949、路径/events/、原页面素材、noindex预览 | 正式域名/HTTPS/入口及允许返回路径 |
| T02 | 原商品引用、规格拒绝、意图持久ID、quote/prepare/lookup适配合同 | 权威报价、同主站会话入车、原购物车保留、整批或逐行结果、超时原ID查询 |
| T03 | native引用绑定、规则版本、精确整数金额样例、live关闭 | 独立活动优惠层、普通码券积分互斥/叠加、限额和品类保护、实际优惠冻结 |
| T04 | 实际paid枚举1、纯归因/多活动去重/未知分摊与退款算法 | 原订单实际活动优惠引用、时区/支付状态、退款稳定ID、行分摊/净额 |
| T06 | 原共享会话、完整分页、商品/券只读、精确原生券路由与单次POST账本 | 非空规格字段；券create/edit/toggle/grant真实回读，未知grant原批次查询缺口 |
| T07 | 可用原后台拉取模式 | Webhook可选，不作为G1阻塞 |

两个任务需各自真实购买闭环才能进入G2完成；10000活动10%再码5%为8550，混单非活动5000再5%为4750仅合同测试值，不是现役金额证据。领取/点击/模拟不计真实成交。

## 发布与回退边界

新服务仅www-data读取公共投影，管理原登录/角色/Origin/CSRF保持；不复制客户Cookie到187或Admin。不改价格/采集/定时任务。应用载荷沿现有锁、SHA/CAS、备份和journal publisher；回退仅本次实际写入文件，保留所有管理状态/操作账本/订单事实。应用发布、Git合并、UI完成、真实后台和G2分开记录。

当前未发布、未创建PR、未写原生券、无真实付款。待补最后候选Q/CI、发布/读回/实际入口及四状态最终结论。
