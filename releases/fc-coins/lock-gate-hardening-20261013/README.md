# FC 自动改价常见超时与保护锁补强

**已上线**：2026-10-13 19:51独立读回通过，34项Linux隔离检查无失败/skip；仅更换ALL联动和竞品只读采集两份活动源码。原进程、价格/成本/毛利、配置、调度、锁、历史失败、Player复验退役及Gallery用户OFF保持。没有人为触发采集、改价或故障。下一原自然任务预计21:23:33，尚未验收；新超时分支的效果目前是隔离验证，不冒称生产故障已实测。

## 目标与范围

用户要求调查频繁问题、重新梳理保护锁与门禁并修好规则，后明确范围是FC自动改价台。此次只处理实际FC采集和ALL请求超时；保留未知写入、身份/平台/受保护字段/成本、并发及用户关闭保护。不改FS首页、经营/顾问、RPG、捆绑包、账号权限或业务价格参数。

## 基线与来源

19:25只读统计最近四天50个自然任务：46个现为ready（29 confirmed、17 no_price_change），4个failed（2次门禁写前拒绝、2次采集超时）；其中一个ready是今日12:20写后超时、15:11人工恢复的原任务，因此至少5个任务曾失败/需维护，不把恢复后的ready抹掉失败史。缓存失败单独看回执，不以job ready掩盖它。

今日17:12原自然写价已confirmed/cache-cleared/public-verified；19:13竞品采集超时，19:22原tick重采、19:23 no_price_change成功，未发生新的价格写入。19:25/19:30后原门禁恢复；13把相关原锁当时均无持有者，没有发现死锁。当前资源快照不拥堵，不据此推断故障时没有负载峰值。

真正采集源在宿主 `/opt/fc27-cloud-browser/collector/collect_competitor_browser.py`，只读bind到容器 `/opt/fc27-collector/collect_competitor_browser.py`；旧宿主同名顶层副本不能当运行源。修改前实际容器SHA与fc27_cloud_browser工作源一致。ALL活动基线ec857862与fs_hooks_rpg_alerts_20261009/source相同；历史冻结目录保留，新规范源在fc27_lock_gate_hardening_20261013/source。精确映射见[SOURCE-MAP.json](SOURCE-MAP.json)。

## 验收条件

- 短暂只读超时最多新开读取一次，仍在原95秒wrapper预算；平台/包规格/优惠/身份/HTTP验证错误不重试，失败行不混入成功数据。
- ALL编辑响应TimeoutError时，原POST绝不重发；只有同原ID/payload、原身份/配置/受保护字段及两轮稳定精确GET确认才继续。未落地、第三值、保护字段变更、拒绝、格式错误、读取失败或超时仍needs_reconcile。
- 现有队列/价格/三采集锁内CAS、备份和原子替换；源漂移、锁忙、未知记录拒绝。发布失败恢复代码，不回退账本/配置/队列。
- 实际宿主/容器SHA、权限、保护文件、原服务PID、原下一周期、空队列及门禁必须独立读回。

## 实现与影响

竞品collector仅在已知CDP/新页/导航/读取/点击Timeout且有足够原预算时重新完整读取一次，原失败诊断保留read_retries；HTTP拦截、平台错误、未知异常、关闭页超时和预算不足停止。未扩大上游访问限制或更改报价口径。

coin_all_sync_job保留先持久派发意图；保存POST脱敏HTTP/code/响应SHA或错误类型。Timeout后最多30秒确认窗口、两个稳定GET轮次（间隔5秒），原单个在途请求15秒上限及writer总预算不变。只确认已存在的价格结果；没有POST重试/新ID重放或删除历史记录。确认不了立即保留原未知/部分状态；其它异常沿原保护执行。

使用已有CAS publisher的精确两目标模式，新增三把原采集锁的NB检查；check-only现在明确不替换、不创建回滚包，必须--apply才发布。所有变更保留mode/owner，失败包括第二次rename后异常都还原两源；不用重启服务或容器，后续原python入口直接读取新源码。[统一处理规则](RULES.md)记录正常等待、短暂采集失败、写后确认、未知、锁忙、人工关闭及恢复观察各自路径。

## 验证结果

Windows业务及读取检查通过，7项POSIX发布检查明确不适用；Linux3.9.18最终34检查全部通过，无失败/skip。覆盖未落地POST不得继续、丢响应不得重发、保护字段/来源/策略变化停止、拒绝不冒充Timeout、两次稳定确认、读取重试截止、原ALL合同、锁忙、CAS、check-only、部分rename及健康失败回退。第一次Linux测试缺临时rollback目录失败保存，补fixture并加强断言后通过；生产检查未放宽。

19:51独立验收9项全部通过：两目标/真实容器SHA、全部保护SHA、元数据、原PID/active、空队列/无未确认、原timer及next、三平台门禁和发布回执。范围仅运行版本与当前恢复状态，不把隔离异常测试说成真实后台故障测试。evidence保存本机真实取证，已受gitignore保护，不上传Git。

## 发布与运行

原staging为/opt/fc-ops-monitor-stage-lock-gate-20261013，精确备份及installed/protected SHA见evidence/published.json。发布只换coin_all_sync_job.py与实际bind源collector/collect_competitor_browser.py，原服务PID保持。旧根工程未stage/commit/push，未覆盖其它dirty；原白名单收录源未修改，无无关refresh。候选/测试、发布入口、SHA索引归档在独立任务代码目录及此资料目录。

## 交接与遗留

重复检查只读保存收据与文件SHA。真实发布/回退需重新核当下源、配置、队列及所有原锁，不重放此manifest覆盖新版本；改代码只按新规范source目录，再冻结产物。原真实写价恢复脚本禁止重跑。

原上游请求具体超时原因仍未获后台同时间证据，OD-FC-ALL-POST-TIMEOUT-20261013继续OPEN。补强不保证外站永不超时，也不自动放行无法确认的写入；下一自然周期及新超时分支生产触发尚未观察。GitHub版本回补另有描述/原字节读回，不等同再次部署或新的合并授权。
