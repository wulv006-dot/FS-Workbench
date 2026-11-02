# 第四包：受限query job/cache与只读现场核验

## 可运行宿主组件候选

新增source/range_jobs.py、tests/test_range_jobs.py。无常驻线程、timer、网络客户端或自由SQL/URL入口；现有宿主显式构造Engine并注入jobs/subscriptions/cache、锁、真实authorize和固定adapter。当前fixture为进程内字典，不声称已完成生产持久化或重启恢复；不自动注册API/Hermes。

仅支持已规划fresh详情。host传可信固定watermark/source_contract；每次submit/status/page/cancel和每个源页调用前后重新核grant、permission_epoch和policy。HMAC缓存key包含统一filter_hash、真实grant、watermark与来源合同；同scope/epoch10订阅复用一条分页链。单订阅取消不取消他人；全部取消时在页边界停止，晚结果不发布或缓存。未验证的frozen/local方案不走源。

规划窗口与scope原样下推给固定adapter；源响应必须保持watermark与字段白名单，重复ID不同内容/循环cursor/结构漂移失败。执行请求/行/累计字节硬预算；超额partial、complete=false，不返回伪完整下载。无total时不编百分比。完整结果最多8MiB，本候选cache总额默认2MiB、最多32job/1000订阅；与Hermes既有10MB外层保持余量。更大需求须后续artifact宿主，当前不支持。adapter解析单页的内存/HTTP上限仍需原宿主约束，本组件只约束接收后的累计结果。

只有证明完整的空页可作为业务空；故障不负缓存，完整空结果TTL最多30秒。缓存到期重新规划同窗口，不拉整库。signed结果游标绑定订阅/job key/结果generation，并在每次续页复验身份。page是已完成有界结果分页，不是user_query.members或export的数据库keyset改造。

新增9项测试通过；独立包全30项通过（Windows/Python3.14.7 SQLite3.50.4、无生产数据/网络）。覆盖单链、单/全订阅取消与晚结果、撤权、缓存隔离、signed cursor、预算、429、完整空、漂移和缓存MISS同窗。没有异步HTTP/持久化、重启恢复、退避Retry-After、真实source分页稳定性或真实授权验收；保持未接线、未启用。

## 独立审查修复

a29050a：Facts.read显式BEGIN覆盖facts与dirty两查询；真实SQLite/WAL交错测试在第一次SELECT后另一连接publish20并清dirty，reader仍返回旧10且dirty/complete=false，避免不存在的旧10+clean组合。新增同event多币种幂等测试，event主键纳入currency。日事实相关7测试通过。
源失败只保证旧值保留，不持久化刷新失败；adapter必须返回最近刷新错误/旧水位，不能把read.complete解释成最新刷新成功。第三包未生产初始化；已有旧候选fixture表若保留，需要隔离重建/显式迁移，不能假设CREATE IF NOT EXISTS改变旧schema。

## 固定c079b3b云Linux回执（父任务独立验证）

useranalytics265/265与tiered14/14通过，0failure/error/skip；Python3.13.5 SQLite3.46.1，真实POSIX改名竞态通过。包hash与78源码manifest跑前后不变，禁网络/子进程。test_completed_extension_freezes_inventory_and_keeps_previous_proof_input有未关闭SQLite连接的ResourceWarning，未掩盖。此回执只覆盖c079b3b，不覆盖第三/第四包、a29050a或生产SQLite3.7.17。

## 187只读现场证据

2026-11-01 15:07:29 UTC，沿用户指定Invoke-Server187.ps1、固定主机指纹，host=play187 uid=0；Python3.9.18 SQLite3.7.17。未打开数据库、未采集、未迁移、未删除或修改生产源码。

| 目标 | 文件数 | 逻辑字节 | 分配字节 |
|---|---:|---:|---:|
| /var/lib/fs-user-analytics/backups/2026-10-29 | 3 | 11623456188 | 11623469056 |
| /var/lib/fs-user-analytics/backups/2026-10-30 | 5 | 12638681929 | 12638703616 |
| 合计 | 8 | 24262138117 | 24262172672 |

29日：customers.sqlite3=11623451648、config.json=4508、identity.key=32字节。
30日：customers.sqlite3=12638675968、config.json=4508、identity.key=32、manifest.json=407、restore-check.json=1014字节。无所见symlink；所有文件硬链接计数1。
主库customers.sqlite3=13352433664字节；现identity.key32字节；两者独立于旧备份、root/0600、非symlink。扫描3207个可读fd无两目录引用，2个fd不可读；已知6源码/配置和2unit未发现两完整目录字符串。非全文件系统依赖扫描，未解析recipe图，不能据此保证全部依赖为零。
30日manifest为fs-users-private-backup-v1、data_version1943；存在fs-users-backup-restore-check-v1回执。本轮只确认小回执存在/合同，未重做恢复或验证签名。29日无该回执文件。
文件系统free103821090816字节，used98601402368字节；本轮实际释放0。只读详细JSON在任务目录server187-readonly-result.json及server187-receipt-result.json；不含密钥内容、客户事实或敏感配置值。

## 清理条件结论与04剩余差额

精确目录/文件/占用已复核；日常打开引用未发现但扫描有边界，旧恢复能力取舍仍需写入删除清单。当前候选未发布、真实恢复替代/recipe依赖未验，故清理前置条件尚未全部成立。没有删除命令/自动清理任务；永久删除须父任务当时确认。接受部分历史损失，不加全历史零损门槛。
后续：活动源码hash比对与真实adapter能力、scope/date的API/UI/Hermes接线、轻facts真实指标对账/原timer锁、job持久化恢复与artifact、有界数据库成员分页/流式导出、源可再生证明/pins/缓存policy、恢复与灰度验收。任务2/3/4/5目前均为独立候选部分实现，不是04整体完工。
