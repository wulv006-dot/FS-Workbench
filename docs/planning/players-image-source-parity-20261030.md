# FC Players 图片现役修复回补（2026-10-30）

本次修复规范源与现役源码不一致的问题，不重复创建原20名球员、不上传图片、不改生产或FC Coins自动改价。

## 现役与源码差异

发布负责人于2026-10-30只读确认当前版本为 `2026.10.29-cloud.16`，以下实装SHA与10月29日保存源码一致。本次只将这两份已实装修复回补规范源，避免以后构建恢复旧上传模块及错误的UNKNOWN分类。

| 规范源 | 现役目标 | 回补后SHA256 |
|---|---|---|
| `fc27_players_cloud/player_web/media_client.py` | `/opt/fc27-player-tool/current/player_web/media_client.py` | `058651a7ce22cb6efb2f1dbfe8e489c03141bfd7aa5ae4d1bc1df51e2103c255` |
| `fc27_players_cloud/player_web/model_image_service.py` | `/opt/fc27-player-tool/current/player_web/model_image_service.py` | `23eeed7c6f50780bc0c1baea7ecbe2c7d03214a35bf7bc2d4f946176b9dd7040` |

公开上传模块 `uploadAuth-4cd714b6.js` 本次只核HTTP200、11349字节、SHA256 `54a3421c9fc1c47ae2678c69d5112ec8d6f9075bd0dde2ece156d7a55789e45e`；不输出或保存模块内容及签名材料。规范源旧 `uploadAuth-b29e96d2.js` 及其哈希已落后。

## 可复现问题与保留的边界

旧规范源把确定发生在上传POST之前的失败也记为 `needs_reconcile/image_unknown`。临时SQLite与模拟上游复现：两项计划在0个后台POST时，首项为unknown、两个scope均被保留。已实装修复用 `ImageUploadNotStarted` 区分该阶段，记录 `failed/image_not_started`、首项not_started并释放scope；原失败事件保留。

真正上传POST后的超时、失去响应、附件或icon读回失败仍保留原ID、附件回执、UNKNOWN与scope，不自动重试。实际上传成功后仍先取附件ID，再仅写模型icon并逐项读回。

原20张图片批次已匹配、暂存并生成计划，原报错HTTP响应未保存，不能据此确认旧报错原因。23700单图原执行 `35e79a962c184f159d66e82c670155a8` 的历史结果为completed_readback，另19图未执行；本次未重传。

## 原20人配置核对

复用10月29日原20输入与实际验收档案，用当前 `resolve_players_types` 按name＋Version＋IS重算：10个normal、10个Signature，差异0。原实际验收为每模型21属性、393 PlayersType及本卡扩展字段，120商品公式均通过；这不是10月30日重新读取后台模型的结果。原20由用户团队导入，不再新建，也不将它们作为本工具JSON新增的实测。

## 本地验证

- 恢复18项图片匹配、暂存、计划、权限、CSRF、重复确认、上传前失败、POST未知和读回回归。
- 原 `pr-fast` Players组纳入上述两源与图片回归；该组20项Python通过、零跳过，推荐按钮DOM及分派器selfcheck通过。没有新增workflow。
- 两份业务源码回补后与实装SHA逐字节相等。未修改现役manifest、运行版本、数据库、开关、任务、锁或服务。
- 默认本机Python缺Pillow，改用已有Bundled Python完成上述检查；未安装依赖。正式GitHub CI、合并及生产发布不属于本次已完成状态。
