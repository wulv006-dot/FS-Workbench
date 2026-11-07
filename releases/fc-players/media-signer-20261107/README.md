# 球员图片上传预检修复 · 2026-11-07

现役cloud.19固定引用的官方`uploadAuth-4cd714b6.js`已返回404，两个60人图片任务在首次上传前失败为`IMAGE_UPLOAD_PRECHECK_FAILED`。本次仅更新已审查的官方资源URL及SHA，版本为cloud.20；保留完整模块哈希校验，不动态信任新资源、不落盘认证原文/材料、不改变上传端点或签名算法。

当前官方首页→`index-95ac99da.js`→`uploadAuth-ac6fbfe3.js`的依赖链、默认TLS/无重定向GET及SHA已从同生产容器只读核实。静态核对仍为毫秒时间戳与公开签名算法，字段及`b2c-api.p2pah.cn/upload/file`端点保持；完整实际上传回包尚未测试。新固定模块SHA为`c0d52ec2c4b3e0eea0ab57331135e5bec5eed714b7e3171c3969dc4bbd95b5d2`。

原成功测试增强：旧URL模拟404，新URL才返回合成模块；固定时点核时间戳、合成签名和multipart原字段/PNG，不打印签名或请求体。旧源码准确复现预检失败，补丁后18项Windows回归及183/Python3.10.12、Pillow9.0.1隔离Linux回归全部通过，无跳过。Linux正式测试无网络、1CPU/512MiB、无端口、只读根及挂载；临时容器已释放。hash变化拒绝、POST仅一次、超时UNKNOWN、附件保留/原ID读回、授权/CSRF/重复确认保护保持。

首次正式CI `42331643075`失败保留：新发布器目录未登记测试映射。已在原pr-fast增加该目录的实际测试映射，执行本release两项固定manifest/51基线与原wrapper等价检查，并复用原发布器成功/回退仿真；没有忽略文件、跳过必需检查或放宽原断言。后续正式CI以PR #887最终head为准。

发布复用原10/29 publisher和cloud.19窄适配方式，51源基线逐SHA匹配。实际运行delta只有`player_web/media_client.py`和`VERSION`；固定manifest、两次CAS、deployment.lock、SQLite在线备份、原子current切换及失败回退保持。ENV、UID992:987、只读/内存/共享价格锁、既有人工权限、600秒按需退出及其它服务保持。Docker沿当前已装镜像无网络构建，不新增依赖。新release目录沿既有.gitattributes保原始字节，发布器依赖固定Git原始blob而非Windows换行转换副本。变更运行文件、前后SHA及publisher依赖见SOURCE-MAP.json。

原任务只读对账：`559abeea45014d0bb8a8c8fa0d35b891`、`12d5036171db49f9bac4e8449e2bdb70`两图片计划是相同60模型/PNG/原icon范围，均1个not_started+59个planned，未派发上传POST；不能把两个计划都补跑成重复上传。`942d57f3cbff4e0da38291a7dc0b5c9d`上新任务已有60人verified，仅24076/24078因原来源PlayersType不明阻断；已完成者不重做，不通过猜类型或删除检查将其视为软件修复。

代码候选、18项Windows及18项183 Linux媒体回归、2项本release检查和16项原publisher仿真均通过；独立复核无阻塞。运行/测试代码head `466cf716b1e5c71954bb6d594f987c9b411b6027`的正式pr-fast已通过：[run 42332320814](https://github.com/wulv006-dot/FS-Workbench/actions/runs/42332320814)。本记录后续纯文档head仍须满足PR实际检查，不能借用旧绿绕过门禁。

尚未合并、生产发布或进行真实图片上传，尚不称图片恢复；未生产POST、重启或任务重放。发布请求限定为PR #887的cloud.20两文件delta、原publisher和必要Players服务重载，并在原失败范围内用一张图片验证上传与icon读回，不整批重跑或新增上新/改价权限。原失败/UNKNOWN、任务和业务回执保留。回退沿本次publisher备份，仅本次模块代码/版本/镜像与原unit绑定；保留数据库及后续合法业务修改，不全库回滚。

私有证据留原任务目录`.agent_runtime/players-repair-20261107/`：`media-public-get.json`、`media-current-*.json`、`media-protocol-proof.json`、`media-endpoint-proof.json`、`live-state-v2.json`、`red-test.txt`、`green-windows.txt`、`green-linux183.txt`、`linux-tests-manifest.json`。不包含真实签名材料。无业务知识、模型、定价或Notion正文变更。

## 已批准发布与单图验收回执（2026-11-07）

用户明确批准#887合并、原发布器两文件替换与必要重载，以及原失败范围的一张真实图片验收；不授权整批重跑或其它业务写入。PR最终head `da75dd4796b45421923a25fab43229ee52b66df8`正式CI run42332538139通过，合并commit `d4c99f704b7427cf13314e8c9f4f7b903ad20c69`。以下回执更新前文候选阶段的未发布状态。

- 代码与部署生效：原publisher在03:13 UTC完成cloud.20，运行delta仍仅media_client.py/VERSION；当前容器image `sha256:8d75ce1a05b3921d5467606d82821abd309eaa2c370ff2c97d799708cd0a56a5`。实际容器媒体模块SHA `7352ea4308b5f2ec76e8b2c73125791d70d2d979f0c205f051c53103b6907bf9`；Players PID18794于11:13:27 CST启动。按需socket保持active。原publisher的运行容器源码及bind来源核验通过。
- 发布保护：原publisher前后任务、items、events、scope、legacy及Admin账本摘要完全一致，发布本身0业务写入。FC API PID4267与worker PID4264仍为09:21:38启动，未因本次重启；这不替代未来自然轮的长期稳定性证明。
- 单张真实业务：03:16:48—03:16:49 UTC，原失败图片24030.png（SHA b9e1f7372a887eaf85e048ea0b2728b76f3f845142d0185a79ebad00eddac15e）仅上传并绑定模型45490787一次，附件及icon读回16668543。验收计划`0dfffd88b44e43149ff8888a2f01ddbd`、执行`56ca2439fba74da5ba95822d95f1ed0e`，1项verified、completed_readback/done；面板查看结果已显示同一执行与写前icon0/写后16668543。使用现有create_batch/stage_png/prepare_image_plan/verify/confirm/execute_image_plan、原shared_client身份校验与范围锁，不修改原失败计划。持久化`/var/lib/fc27-player-tool/pr887-single-image.json`用于防止重复验收；再次遇到此标记只核原ID，不重发。
- 验收路径限制：浏览器自动化文件选择两次均未取得可用文件，未提交图片匹配或确认；本次真实上传通过维护入口调用现有服务链完成，随后通过FS面板真读回执。浏览器选文件到点击确认的完整交互仍未验，不将服务链成功表述为该交互已通过。
- 范围保持：原559abeea/12d50361两个60张任务及失败回执保持原样；整批未重跑，未新增球员/改价/权限。24076/24078缺PlayersType来源仍阻断。此次不涉及自然定时任务验收，不新增观察周期或调度。
- 回退：本次原publisher备份`/opt/fc27-player-tool/backups/2026.11.07-cloud.20-20261107T031325Z`，同stage入口`/opt/fc27-player-tool/staging/media-signer-20261107/upgrade_media_signer.py`。失败自动回退保留原保护；发布后如需回退，仅核本次源/镜像/unit差异并保留后续合法修改，不回滚SQLite、任务、附件或单张业务回执。

本次追加私有证据在现工作树`.agent_runtime/players-publish-887/`：deploy.log、live-after.json、verify_one.py、single-verification.log、live-verified.json及single-image-verified.png。未新增付费资源；费用无可独立计量回执，不报为已证明零成本。
