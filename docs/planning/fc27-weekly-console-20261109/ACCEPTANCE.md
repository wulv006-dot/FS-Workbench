# 验收记录 — 2026-11-09

## 当前结论

运营台与真实Sol宿主接线代码已实现；没有部署到FS生产，没有付费模型调用。人工输入本期SBC来源后可请求候选的链路已做隔离验证。用户最终确认手动触发，允许Hermes使用本人身份及真实模型进行页面商品更新测试；自动检测/定时不属于本次实施终点。真实模型及草稿更新验收已获授权，待生产代码部署获批后经实际FS会话执行。批准记录不会执行发布等生产动作。

## 已通过

- 最终周更、推荐、provider、原ID恢复与HTTP权限测试：48/48（Windows Node24.22.1），包括真实center seed到三页任务上下文、CSRF/角色拒绝、原中心无发布写入、异步provider、严格终态回执、跨用户去重隔离、原任务查询、迟到响应不回退已完成结果。
- 最终共享Sol宿主17/17在183禁网隔离容器通过：实际Proxy→ModelGateway→UnifiedBudget→OpenAI请求构造，token账本、额度、无工具strict schema、原ID去重、会话撤销、无效输出真实用量、队列失败、重启恢复只影响campaign、原report/pricing账本不变、campaign初始化失败不影响原health。仅外部模型和登录校验响应使用替身；未付费调用。
- 183隔离Linux容器：Node24.22.1、Python3.12.3，禁网、1CPU/1GB、只读挂载源码、专用临时结果目录。原活动Node测试首轮347项通过；因测试包缺目录fixture/Playwright引用而失败的4个文件，补齐后5项全部通过。没有放宽断言或删除测试。
- 发布器/包装/保留策略32项通过；后台模块先受包缺少sales_auth和catalog_probe源码影响，补齐后复用231项通过证据，catalog_probe单独3项通过（对应完整234项）；统计进程隔离4项通过。
- 原活动浏览器检查及新增周更检查共15个脚本：14个183通过；provider54硬要求Chrome，183镜像没有该浏览器，改在已装Chrome的Windows同源码检查通过。未在187生产跑测试。
- 最终周更浏览器19类场景通过：空、失败、只读、三页、周次维护、审批不执行、暂停恢复、刷新后的原ID恢复、历史比较、URL筛选、Hermes开关、SBC关联及缺证/过期、异步原ID查询、有界商品查询/翻页、可选到期时间、真实嵌套task/run/usage回执、深浅主题及390px窄屏。此测试使用隔离API fixture；HTTP集成测试另核真实production-server代码与原center。
- pr_fast自检通过；新浏览器脚本已加入原campaign-analytics组，不新增workflow。
- 独立审查及总控复查修复并补回归：平台code与aid严格一致、当前release不能套给旧周次、宿主回执持久化、跨用户去重、迟到响应竞争、原任务已知未派发与查询故障区分，以及campaign异常恢复不得改动其他任务用量记录。

## 环境失败与限制

Windows默认Python缺tzdata，初次保留策略/知识收尾检查报错；业务保留策略已在183通过，知识收尾复用已安装runtime的tzdata后完成。最新知识plan无受影响正式条目、无重启、无Notion发布；其104项测试有7项既有平台跳过，不声明该套零跳过。知识变更ID `KL-3a472cc012b0e08d4943ff14`。

Hallmark渲染检查工具缺puppeteer-core，使用现有Playwright实际截图替代。旧共享样式的扫描提示未通过修改全局CSS消除；本次页面沿FS令牌，未改变其他页面风格。

## 生产只读核对

管理服务与公开运行服务均active，weekly.html不存在。production-server/index/products线上字节与main 2b0f735一致。operations.html有线上独立差异，本批完全不改。源版本/目标/候选哈希见RELEASE-CANDIDATE.json；该清单未批准，不能直接宣称已上线。

共享fs_inprocess/proxy_gateway/transport/openai_provider/fc_daily线上字节与本分支HEAD基线一致。线上range_api按文本逐行与management-november-20261103/source/range_api.py一致；dashboard-refresh旧源缺实时订单、管理台与Desktop接线，已撤销对旧源的修改，本批只改现役management-november入口。生产原文件哈希单列，换行差异不冒充字节一致。

## 明确未执行

GitHub正式CI与PR状态以PR实时记录为准，本文不预先宣布通过；无合并或生产部署。没有优惠券写入、活动发布、定时启用、回退、社区消息、订单/支付或真实付费模型调用。

真实Sol沿新增campaign任务身份及原Grants/Proxy/额度调用；不借report/pricing上下文或固定owner。代码具备人工会话触发与原ID查询，但部署、真实模型返回、三页真实可售/优惠/成交链路仍未验收。用户最终选择手动触发；自动更新来源与调度身份未接入，现有周二/周五游戏监控不等于每期SBC监控，也不列为本轮已具备能力。

## 证据位置与重跑

本地：`.agent_runtime/weekly-ui/`截图、`.agent_runtime/weekly-console/`测试打包及知识plan日志。183：`/tmp/fs-fc27-weekly-20261109-check/results/`原始结果；失败日志保留，后续通过证据分别记录，不涂改首轮结果。

最终共享Linux结果：`/tmp/fs-fc27-weekly-20261109-check/sol-results/campaign_sol_host.log`、`sol-results.json`；源码只读挂载、网络禁用、容器已退出，无服务变更。

直接回归：`node --test releases/fs-dashboard/campaign-analytics-20261023/app/analytics/tests/weekly-*.test.mjs`；浏览器：`node releases/fs-dashboard/campaign-analytics-20261023/app/tests/weekly-console-browser.cjs`（使用现有Playwright）。正式CI继续走tools/pr_fast.py的受影响campaign组。
