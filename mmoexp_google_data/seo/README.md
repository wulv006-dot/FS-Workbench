# SEO日更基础链 · 施工增量

唯一规格：[seo-daily-optional-ai-r3-elastic](../../docs/planning/seo-daily-four-games-20261104/SPEC.md)。本目录是新增维护源，不是线上版本回执。

## 已实现的候选能力

- 四游戏、北京时间日期与夜间门；源日未结束不当成完整昨日。
- GSC/GA4日级汇总适配：复用 `details.collect_details.credential` 的现有受控身份，不调用旧Reader的160次硬上限；保留主站、游戏路径、自然搜索过滤与来源时区。未验证真实资源及账户权限。
- SQLite逐页提交、固定初始回填窗口、近14天小汇总修订、当前30天缺口续采；空响应保留已有可信事实并标过期。
- 同日唯一发布、文件hash、候选/正式隔离、指针中断对账；查询、来源、规则提醒、分页和导出只读发布包。
- 独立FS控制库：总开关、四游戏开关、CAS与审计；项目generation避免关开后复活旧任务。AI桥仅提供适配合同及隔离测试，生产Provider/账本未接入。
- 独立备份恢复检查、两份已验证备份、35天事实和当前/上一快照保留；弹性磁盘策略区分预警与应急。
- `ui-system/modules/seo/`提供独立加载的前端候选，沿用FS令牌；真实导航、登录宿主和发布入口尚未绑定。

## 执行与配置

`python -m mmoexp_google_data.seo.runtime --config /path/to/private-seo-config.json`

`config.example.json`无凭据，不能直接当作已校准部署配置。`sources.gsc`和`sources.ga4`分别需要现场核实的`resource`、`timezone`，可配置`page_size`。Google账户由原访问层读取，不复制Key。`resource_policy`字段见`retention.ResourcePolicy`，HTTP连接、无进展和应急响应字节及临时空间须由W0实测配置；不能把旧参考值写成拒绝线。

现阶段配置`orders`会明确报`ADMIN_ORDER_LIVE_BINDING_NOT_IMPLEMENTED`；缺配置不会伪造SEO成交。SERP、页面探测、关键词明细、退款修订、人工行动/复查与生产Hermes工具接线仍未实现。现有自动化没有被修改或停用。

`api.Service.handle`由现有FS HTTP宿主调用。`Actor`必须来自该宿主真实会话与当前RBAC，禁止从公开请求头或用户传入的JSON构造；写设置还须通过宿主原CSRF检查。当前没有匿名独立HTTP服务，也没有假定某个生产端口可用。基础进程不导入Hermes，不探模型健康。AI桥只在单独进程按现役FS任务设施调用；尚未安装任何timer。

## 验证

`python -X utf8 -m unittest discover -s mmoexp_google_data/seo/tests -v`

Windows使用项目已声明的`tzdata==2025.2`；Linux使用目标系统时区库。`node ui-system/modules/seo/test_model.cjs`验证版本绑定。浏览器合同另用现有Playwright环境执行`test_ui.cjs`，所有示例数字仅在测试文件中。正式CI复用pr-fast的`seo-daily`组。

## 发布与恢复边界

尚未绑定现场installed manifest、精确CAS、原publisher、登录宿主或资源组，因此当前不提供可直接运行的生产安装命令。补齐这些必要接线后沿原publisher发布。新模块回退仅撤销本次入口与日更，保留SEO数据库、快照、控制审计、AI未知请求和备份；不能用旧整包覆盖其它模块。`backup_verified`用SQLite一致性备份，并在隔离只读连接执行完整性检查；`verify_backup`可复验备份清单。实际恢复需先隔离目标、校验整份清单，再通过原维护流程切换，不能把一次夹具恢复当生产恢复。
