> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

> revision 2增量：D4必需2源、FC执行闭包4源、Players当前cloud.9清单45源+manifest、任务台web3源、NBA/MLB页面2源及安全helpers已补。以下revision 1矩阵保留历史，具体当前状态见RUNTIME-CONTRACTS/REVISION-2-REMEDIATION及当前manifest；仍非全部模块端到端通过。

# 模块与责任/差异矩阵

责任栏指代码职责，不推定用户或陈超的个人维护归属。`opt`实际21个子目录包括历史发布任务，不能未经分组核对称17个独立活动模块。所有服务器绝对路径来自原包结构，是快照声明而非当前运行进程证明；本机路径/SHA/时间见JSON矩阵。

| 包内模块 | 代码职责/可观察入口 | 整合取舍 |
| --- | --- | --- |
| auth-portal | 8895统一登录/会话/verify；auth_portal.py和login/status模板 | 新增静态源码；配置/账户外置；保持原登录UI不生产改动 |
| fs-access-policy | URI/方法读写分权 | 来包4admin拒绝；候选用本机3admin原样源码 |
| d4follow | app/core/engine/gates，Aion2竞品及ARPG改价/成本 | 新增25个核心源；配置、patch、历史、作业输出排除；不混经营Aion2 |
| deploy-hub | deploy_client/deploy_server，包上传/发布 | 新增两文件静态快照；部署/写入口待独立审查，不运行 |
| iggm-web | 采集app/core/runner/sites，static/templates | 新增12源，保留相对结构；安装shell/bat排除 |
| nba-reprice | Node server + P2PAH/OCR/fetch工具 | 新增4源；cookie/captcha/log/启动脚本排除 |
| mlb-online | mlb_server及上传处理 | 新增server源；实际config和XLSX排除，前端/部署完整性待补 |
| mmoexp-taskboard | taskboard_server，SQLite协作台 | 新增server源；seed运行内容不导入，禁止改db。前端/tests/schema完整性待本机对应源只读补齐 |
| fc27-cloud-browser | FC队列/采集/报价/写守卫/session服务 | 原171已验源优先；58相同副本含部分此模块不再复制；宿主旧alias排除 |
| fc27-activity-api | 活动读取接口 | 原件待审，不擅加新运行入口 |
| fc27-gate | 原有会话桥接 | 原件待审，不能据cookie桥接存在称真实角色已验 |
| fc27-ops | 旧日采集/分析/API后端 | 不迁入活动采集链；原统一快照/FC前端规范源保留 |
| fc27-player-tool | 九历史版本cloud.1–cloud.9 | 全留raw；后续只收当前规范45源及验证runtime映射，不自动最高版本号取代活动版本 |
| fs-dashboard-release | 受控HTML发布网关 | 90cf…与原候选相同，保留原规范文件，不重复复制 |
| fs-exact-range-20261001 | 精确区间及历史安装/准备脚本 | 0a03…相同，保留当前规范文件；其它历史/安装入口隔离 |
| fs-supplement-release-20260930 | 旧补源扩展collector/readers | 新fs120真源保留；旧collector不替换当前统一口径 |
| fs-date-theme-fix-20261001 | 历史日期/主题部署任务 | 保留171现有测试/规范代码，包内deploy/rollback不执行 |
| fs-range-read-state-20261001 | 历史范围等待状态部署任务 | 当前read-state源保留，不按历史整包恢复 |
| fs-permissions-release-20260930 | 历史权限准备/部署/验证任务 | 全raw，仅源码比对，不运行修复/账户脚本 |
| mmoexp-weekly-report | 周报适配器/生成器/UI | 与171匹配部分保留原样；public运行JSON和verification实际数据排除 |
| dashboard-collect | 已退役旧builder/publisher/兜底链 | 全隔离，不入活动候选；缺publisher不当P0修复指令 |
| var/www静态源 | hub/docs/sites/nba/mlb页面，FC运营HTML | FC已匹配规范保留；其它页面待关联后端和脱敏检查，不全当构建产物 |
| etc/nginx/systemd | 运行路由/启动/计划配置 | 只生成静态单位矩阵；不得将包文件当有效units/启用状态，未导入自动部署 |
| 新fs120/home/Google | 包缺失而当前171有规范源 | 从171保留；采集120/UI60/Google09与300/业务对照60均不改 |

## 来源说明

- 冻结v2是171文件审核候选，不等于完整服务器部署包；当前工作树有进一步10:36根规则与历史/运行材料。
- 来包是带运行痕迹的服务器路径快照，不是完整干净源码或可直接提交的基线。
- 独立候选以171规范源为骨架，加49静态源码；保留原树和路径。新增源码尚需完整runtime/auth/数据语义验收，不能因AST通过称功能可用。
- 合并不存在共同Git祖先时，本轮用三份文件/功能快照比对，不使用unrelated-histories/ours/theirs，不改本地历史。
