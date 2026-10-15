# FS 集中清理第一版候选

2026-10-15 生产兼容补修：服务器实测 systemd 219，拒绝 OnCalendar 尾随时区；旧候选发布已自动回滚并保留证据。当前 timer 改为 `*-*-* 06:30:00`，发布器新增 `/etc/localtime` 与 `Asia/Shanghai` 的严格匹配检查；保留 `Persistent=false` 和脚本北京时间窗口保护。下面显式尾随时区的说明为初版候选记录，不能用于当前上线。

状态：独立候选，未部署或执行服务器删除。Windows17项中11通过、6因POSIX/符号链接权限跳过；Linux锁/删除/符号链接、实际缓存消费者回归与正式CI须由主线完成。

## 范围与推荐

自动删除仅白名单 `/var/lib/fs-business-ranges/profit-days/[a-f0-9]{64}.json`，保留7天。理由：已核有效`profit_queries.py`仅以7200秒TTL消费这些可再生查询缓存，记录返回完整副本，不输出缓存文件路径。7天远长于有效TTL，保护近期故障排查并限制长期堆积；计算日期和实际利润口径不变。

按有效UTC`capturedAt`判断，不能只按mtime。记录还必须满足已核来源/完整日区间/正确单位/available/最新尝试成功/stale=false/文件名按原key公式吻合/无任何报告文本引用/单链接普通文件。缺失、失败、旧证据、未知schema、未来时间、无时区、路径逃逸、符号链接、硬链接及变化中的文件保留。`.tmp`等未确认用途的临时文件也保留，不把失败上传/写入材料当垃圾。

主准确区间缓存、事务快照、旧前端、报告正文/原文/证据、SQLite、任务/审计、rollback以及其它目录全部保护。主快照133.8MB和旧前端210.3MB只作盘点，暂不自动删除；这些目录有当前指针、报告引用或发布回退用途。此版本不是全盘清理。

2026-10-14T17:38:43.367367+00:00只读盘点：磁盘可用167,115,223,040B/总211,243,667,456B；business-ranges92,114,303B，主cache913份/27,389,521B（423份语义时间超过7天，保持保护），profit-days233份/221,452B（没有超过7天的记录，当前预计删除0份）。来源`live-inventory.json`；这些是本次时点，不是永久容量。

## 来源、锁与发布

已核线上`/opt/fs-exact-range-20261001/profit_queries.py` SHA为`bf133ffa7a9ea55e7ca3f87cd7e45d7aa1a1be2fee543eed34e94b14cd2db2c4`，与`fs_on_demand_20261012/source/profit_queries.py`逐字节匹配。候选只在load/save函数加同一个可重入文件锁，原公共签名、键算法、校验、缺值/失败处理、源请求和其它方法AST保持；读写及清理都持`.retention.lock`，避免检查后新缓存替换被误删。

`cache_guard`支持同线程重入，Linux目录逐级O_NOFOLLOW/dir_fd打开，删除只相对已打开白名单目录。apply重新核引用、元数据、内容SHA及语义过期。只有精确配套writerSHA匹配，且fs-business-range实际进程启动晚于helper和writer发布文件mtime，才允许apply；只换磁盘源码而旧进程未重启不能删除。

发布映射见`candidate-runtime-map.json`：4目标（helper、配套writer、service、timer）。主线沿现有publisher扩限定白名单、CAS、备份和单模块重启，不能只部署helper而漏writer；不新建部署器、不改账户或业务调度。现有helper和timer此前不存在，元数据见`runtime-metadata.json`。

## 计划、审计与重跑

当前真实service候选的ExecStart已包含`--apply`；脚本直接运行仍默认dryrun。安装4文件后不启动service、不启用或启动timer。先通过LinuxQA及精确配套writer发布验收，完成一次现场无`--apply`的dryrun并核对计划和保护范围，之后主线才可enable/start timer；这是本轮已获授权的分阶段发布，不需要再次逐项询问。安装候选不等于清理服务已启用。

服务器已实读`Asia/Shanghai`、+0800；当前timer显式使用`OnCalendar=*-*-* 06:30:00 Asia/Shanghai`，`Persistent=false`，不补跑，计划不依赖服务器默认时区。脚本在上海06:59起拒绝新删除，service超时120秒且KillMode=control-group。LinuxQA须核systemd实际识别显式时区并读回下一次触发时间；TZ环境变量仅用于进程环境，不代替OnCalendar时区。挂起后晚触发时脚本仍按实际上海时间检查删除窗口。

每轮审计保存在`/var/lib/fs-maintenance-cleanup/`，0700目录/0600文件。删除前保存完整metadata计划，并逐文件fsync记录delete_planned/deleted；完成后另保存结果。异常或终止留下原计划及未知结果，不改成已成功或零删除，不删除自身审计。缓存内容、业务数值、凭据不进入审计。

手动预览：`/opt/python39/bin/python3 -B /opt/fs-exact-range-20261001/fs_cleanup.py`。实际重复执行必须保持同配套writer/进程/锁和00–06:59窗口；已删除缓存不再匹配，变化/被引用的文件保留，不按旧计划盲删。此缓存可能因后续合法查询重新生成，不重复模型调用或业务写入。

本地复跑测试：`python -m unittest discover -s docs/planning/fs-revision-20261015/cleanup/tests -v`。`build_candidate.py`会重新生成候选与映射，不是只读验证；当前冻结后不得为查看SHA而运行它。Linux正式QA需完整17项且0skip，再回归既有profit query用例。未执行服务器清理、systemctl安装/启停、Git写或共享源码修改。

## 冻结后只读审计

删除操作只处理固定CACHE目录第一层、精确名称且满足语义校验的普通单链接JSON，不递归。计划与apply分别扫描引用，apply再核inode/device/size/mtime/content SHA和过期语义；读写与删除共享可重入独占锁。脚本默认dryrun、生产service明确apply，执行前仍需阶段门禁。路径逃逸、符号链接、硬链接、失败/缺失/未来数据、被扫描到的引用及变化中的文件均有保护。

审计发现两项边界需主线在启用前核定，未修改候选：引用扫描覆盖REFERENCES中5个已知根和文本格式，不能宣称检查了服务器所有位置或数据库内引用；apply的引用扫描发生在取得cache锁前，而且报告发布者未共用这把锁，因此新增引用与删除之间仍存在竞态，现有测试仅验证plan之后、apply之前已出现的引用。配套writer仍保留原有超过8192份时按mtime淘汰的行为，该旧行为没有7天/引用/单链接语义检查；本候选没有增加这项行为，也不能将整个目录的所有删除都归于集中清理新护栏。首次dryrun预计0删除不是上述并发边界已消除的证明。不扩大首批目录或改原writer业务逻辑。

## 活跃消费者补核

本轮再次只读核实：profit_queries.load重新解析并返回值，get仅返回history.daily；profit_daily.normalise显式投影业务字段。range→fs_evidence→research将记录深拷贝为独立src/ev证据，再完整保存到任务库与evidence.json。已核活跃链路不输出profit-days文件路径或64位缓存key，因此并发新报告不会建立对这些缓存文件的持久依赖；报告读取不依赖缓存仍存在。references是5个已知根的额外保守保护，不是全服务器引用保证。未扩大首批目录，也未修改原8192份容量淘汰规则。
