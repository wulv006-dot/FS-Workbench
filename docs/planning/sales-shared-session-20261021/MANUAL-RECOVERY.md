# Admin 单会话恢复与旧登录入口废弃

2026-10-21 上海时间。用户明确授权切换临时 wulv 账号、人工填写验证码、先恢复 Admin，并明确旧独立登录入口直接废弃。该后续授权覆盖早前冷却停服安排；旧失败证据保留。

## 已确认的生产结果

- 14:55:44：人工提供的图片验证码仅提交一次，8767 ready=true、login_attempts=1、consecutive_failures=0。凭据只经受限 stdin 写入服务器配置，没有进入代码或本记录。
- 15:00:44：下一轮自动会话检查后仍 ready，login_attempts 仍为1，没有再次进行密码登录。
- sales、NBA 通过各自真实客户端 GET `/admin/index/index`，均 code=1，身份为 wulv；MLB 与商品包 verify_identity() 均为 True；SBC whoami() 身份为 wulv。
- Players 按生产容器原 UID992/GID987，通过原 Unix socket 共享桥及其后台身份检查，无异常。该客户端 verify_identity() 成功时无返回值，不用 bool(None) 判断失败。早前诊断探针误用了缺少GID987的用户和返回值判据，没有修改生产ACL。
- 8767 active/enabled；SBC active/enabled。旧 `dashboard-collect.service` 已由原单位文件替换为 `/dev/null` 符号链接，LoadState=masked、inactive。旧版systemd显示UnitFileState=bad；屏蔽以LoadState及链接读回为准，不能称仅disabled。
- SBC 另一版2FA补丁曾恢复独立登录方法；本次在其当前版本上重接8767，保留其他方法及google_code调用签名，禁止独立login、loginGoogle和refreshToken请求。webapp已有会话缓存废弃逻辑保持。
- 原认证probe main已经废弃；NBA/MLB/商品包/sales/旧dashboard认证方法均消费8767，不恢复独立登录。旧代码与受限备份仅供审计，不作为备用认证方案。
- `fc27-cloud-worker` 现场已由其他执行方恢复，未覆盖其状态；`fc27-ops-worker` 核实队列仅14成功/1历史失败、无queued/collecting_order后恢复active/enabled。没有重发旧失败或清理队列。

## 活动来源与受控变更

| 对象 | 精确版本 |
|---|---|
| 保留的原2FA镜像 | `fc27-cloud-session:2fa-file-20261021-v1` |
| 补丁输入服务源码SHA256 | `4923240a166b232f3c019c80341017eda1bca237aaf9e36c4020c1042a3499c8` |
| 新镜像 | `fc27-cloud-session:manual-wulv-20261021-v1` |
| 新镜像ID | `sha256:08c82bdf70d914a0f3b85863ef52ceda3a74ed921fdbd97dc3c7f16a46ddcea9` |
| 活动服务源码SHA256 | `27ab5e9b6f263ec711dd61a7cc6348dab755289241c3cc75a4ba8a60143e7100` |
| 主unit SHA256 | `5878b34a962d320ce06a74092f82e082fba2d79bc3d6cdf147b187a7538448bb` |
| SBC 输入SHA256 | `ceb98846749432f25e8b11bf7350d47e0bea53d19b257e45d7c96f632bff9ca9` |
| SBC 输出SHA256 | `9c96deec225595950633e9ef0157e0c6ebd7cc20ec466527c788b16282ef2f33` |

镜像构建只基于原2FA镜像COPY补丁后的服务源码及manual_captcha.py，入口不变。保留_finish_google_login、_accept_login_payload、refresh、serve；登录路径去除OCR识别，只有收到对应challenge的人工答案才发送一次登录。空等待仅轮询本地0600输入文件，不请求登录或重复获取图片；过期、错challenge拒绝消费。验证码由人工输入，未使用OCR或模型识别。

新增systemd drop-in `/etc/systemd/system/fc27-p2pah-session.service.d/manual-inbox.conf`，启动前创建两个独立0700 `/run` inbox目录，避免重启后临时目录缺失。Google口令收件箱与旧账号隔离；没有复制旧口令。

操作ID及服务器受限备份：

- `/var/backups/fs-admin-wulv-manual-20261021-v1/`：原unit、原配置、receipt；配置原件仅服务器保留0600，未导出。
- `/var/backups/fs-admin-retire-20261021-v1/`：当前SBC原件、旧daemon单位、receipt；目录0700、原件0600。

变更通过原SSH入口、同一全局发布锁、精确SHA/CAS及单次操作回执执行；不重放已有操作目录。两个部署脚本重新执行应先检查原回执，不能换ID盲重放。新目录仅存补丁生成器/辅助代码及脱敏材料，未导出原完整服务源码或生产配置。

## 检查与边界

本地11项测试通过（原8项+3项人工验证码流程测试），覆盖等待不增加登录次数、人工值单次消费、错challenge与过期拒绝、2FA及refresh方法保留、共享token更新、不可用时失败关闭、独立Google登录封锁。镜像内真实Python编译通过；上述消费者为真实只读身份检查。正式CI/PR/合并状态以独立Git回执为准，不以这些检查代替。

未触发业务价格、上架或订单写入，未复验wiki球员价格，未清除旧失败。销售数据与自然30分钟周期未验。sales定时同步继续disabled/inactive，因为它仍需Order会话；这不是保留旧Admin登录作为备用。当前未发现可向sales提供Order cookie的统一服务，未创建新Order认证服务或自动提交其验证码。

风险：wulv为临时共享账号，其他客户端再次密码登录可能使8767会话失效。现有会话可按原refresh续期；进程重启或需要重新登录时，将等待新的人工图片验证码，Google 2FA若需要也须对应用户提供。本次未以重启破坏刚恢复的会话，重启恢复未实测。

后续更换账号需只更新8767受限配置并完成一次人工验证；消费者无需各自改凭据。不恢复已废弃daemon、认证probe或独立登录代码。回退仅针对本次精确文件并保留新失败证据、数据库、队列、锁与审计；若回退到带独立登录的旧代码，相关入口必须继续屏蔽。
