# 球员图片上传预检修复 · 2026-11-07

现役cloud.19固定引用的官方`uploadAuth-4cd714b6.js`已返回404，两个60人图片任务在首次上传前失败为`IMAGE_UPLOAD_PRECHECK_FAILED`。本次仅更新已审查的官方资源URL及SHA，版本为cloud.20；保留完整模块哈希校验，不动态信任新资源、不落盘认证原文/材料、不改变上传端点或签名算法。

当前官方首页→`index-95ac99da.js`→`uploadAuth-ac6fbfe3.js`的依赖链、默认TLS/无重定向GET及SHA已从同生产容器只读核实。静态核对仍为毫秒时间戳与公开签名算法，字段及`b2c-api.p2pah.cn/upload/file`端点保持；完整实际上传回包尚未测试。新固定模块SHA为`c0d52ec2c4b3e0eea0ab57331135e5bec5eed714b7e3171c3969dc4bbd95b5d2`。

原成功测试增强：旧URL模拟404，新URL才返回合成模块；固定时点核时间戳、合成签名和multipart原字段/PNG，不打印签名或请求体。旧源码准确复现预检失败，补丁后18项Windows回归及183/Python3.10.12、Pillow9.0.1隔离Linux回归全部通过，无跳过。Linux正式测试无网络、1CPU/512MiB、无端口、只读根及挂载；临时容器已释放。hash变化拒绝、POST仅一次、超时UNKNOWN、附件保留/原ID读回、授权/CSRF/重复确认保护保持。

发布复用原10/29 publisher和cloud.19窄适配方式，51源基线逐SHA匹配。实际运行delta只有`player_web/media_client.py`和`VERSION`；固定manifest、两次CAS、deployment.lock、SQLite在线备份、原子current切换及失败回退保持。ENV、UID992:987、只读/内存/共享价格锁、既有人工权限、600秒按需退出及其它服务保持。Docker沿当前已装镜像无网络构建，不新增依赖。新release目录沿既有.gitattributes保原始字节，发布器依赖固定Git原始blob而非Windows换行转换副本。变更运行文件、前后SHA及publisher依赖见SOURCE-MAP.json。

原任务只读对账：`559abeea45014d0bb8a8c8fa0d35b891`、`12d5036171db49f9bac4e8449e2bdb70`两图片计划是相同60模型/PNG/原icon范围，均1个not_started+59个planned，未派发上传POST；不能把两个计划都补跑成重复上传。`942d57f3cbff4e0da38291a7dc0b5c9d`上新任务已有60人verified，仅24076/24078因原来源PlayersType不明阻断；已完成者不重做，不通过猜类型或删除检查将其视为软件修复。

当前仅候选与上述回归完成，正式CI、合并、生产发布及真实图片上传分别记录，尚不称图片恢复。未生产POST、重启或任务重放。需要发布时沿本清单及当前授权执行；原失败/UNKNOWN、任务和业务回执保留。回退沿本次publisher备份，仅本次模块代码/版本/镜像与原unit绑定；保留数据库及后续合法业务修改，不全库回滚。

私有证据留原任务目录`.agent_runtime/players-repair-20261107/`：`media-public-get.json`、`media-current-*.json`、`media-protocol-proof.json`、`media-endpoint-proof.json`、`live-state-v2.json`、`red-test.txt`、`green-windows.txt`、`green-linux183.txt`、`linux-tests-manifest.json`。不包含真实签名材料。无业务知识、模型、定价或Notion正文变更。
