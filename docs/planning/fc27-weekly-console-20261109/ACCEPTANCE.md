# 验收记录 — 2026-11-09

## 当前结论

运营台代码与隔离功能验收完成；没有部署到FS生产。真实Sol provider、游戏更新自动输入、自然周更、三页真实可售/优惠/成交链路仍未验收。批准记录不会执行发布等生产动作。

## 已通过

- 新增周更、推荐、原ID恢复与HTTP权限测试：30/30（Windows Node24.22.1），包括真实center seed到三页任务上下文、CSRF/角色拒绝、原中心无发布写入、provider不可用和超时、版本/内容去重。
- 183隔离Linux容器：Node24.22.1、Python3.12.3，禁网、1CPU/1GB、只读挂载源码、专用临时结果目录。原活动Node测试首轮347项通过；因测试包缺目录fixture/Playwright引用而失败的4个文件，补齐后5项全部通过。没有放宽断言或删除测试。
- 发布器/包装/保留策略32项通过；后台模块先受包缺少sales_auth和catalog_probe源码影响，补齐后复用231项通过证据，catalog_probe单独3项通过（对应完整234项）；统计进程隔离4项通过。
- 原活动浏览器检查及新增周更检查共15个脚本：14个183通过；provider54硬要求Chrome，183镜像没有该浏览器，改在已装Chrome的Windows同源码检查通过。未在187生产跑测试。
- 周更浏览器14类场景通过：空、失败、只读、三页、周次维护、审批不执行、暂停恢复、刷新后的原ID恢复、历史比较、URL筛选、Hermes开关、SBC请求及未接provider、深浅主题、390px窄屏。此测试使用隔离API fixture；HTTP集成测试另核真实production-server代码与原center。
- pr_fast自检通过；新浏览器脚本已加入原campaign-analytics组，不新增workflow。
- 独立代码审查重现的两个问题已修复并补回归：平台code与aid严格一致；当前release不能套给其他活动版本的旧周次。

## 环境失败与限制

Windows默认Python缺tzdata，初次保留策略/知识收尾检查报错；业务保留策略已在183通过，知识收尾复用已安装runtime的tzdata后完成。知识plan无受影响正式条目、无重启、无Notion发布；其104项测试有7项既有平台跳过，不声明该套零跳过。知识变更ID `KL-1010e70a0b002cf438835d1f`。

Hallmark渲染检查工具缺puppeteer-core，使用现有Playwright实际截图替代。旧共享样式的扫描提示未通过修改全局CSS消除；本次页面沿FS令牌，未改变其他页面风格。

## 生产只读核对

管理服务与公开运行服务均active，weekly.html不存在。production-server/index/products线上字节与main 2b0f735一致。operations.html有线上独立差异，本批完全不改。源版本/目标/候选哈希见RELEASE-CANDIDATE.json；该清单未批准，不能直接宣称已上线。

## 明确未执行

GitHub正式CI与PR状态以PR实时记录为准，本文不预先宣布通过；无合并或生产部署。没有优惠券写入、活动发布、定时启用、回退、社区消息、订单/支付或真实付费模型调用。

真实Sol现有8940/8941入口要求Hermes宿主签发的任务身份/admission；活动后台尚无对应可信任务上下文。不能借report/pricing上下文或固定owner调用。provider接口已实现并严格保持unavailable，后续需在共享Hermes能力入口接入获准campaign任务身份，再验证模型实际使用和自然周期。

## 证据位置与重跑

本地：`.agent_runtime/weekly-ui/`截图、`.agent_runtime/weekly-console/`测试打包及知识plan日志。183：`/tmp/fs-fc27-weekly-20261109-check/results/`原始结果；失败日志保留，后续通过证据分别记录，不涂改首轮结果。

直接回归：`node --test releases/fs-dashboard/campaign-analytics-20261023/app/analytics/tests/weekly-*.test.mjs`；浏览器：`node releases/fs-dashboard/campaign-analytics-20261023/app/tests/weekly-console-browser.cjs`（使用现有Playwright）。正式CI继续走tools/pr_fast.py的受影响campaign组。
