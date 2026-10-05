> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# 旧经营页发布链与恢复事实

当前恢复版为20261005-restore-v7，2026-10-05 11:31:56北京时间受控发布，HTML SHA1d6a6084d9c505f19cb12c9e856c652feb53af9a2f2f54e61c9a638b6e416f5a。11:31:56不是新未知覆盖，也没有直接scp页面。约11:56再次SHA/账本核验，11:59真实wulv会话分别GET门户与完整经营页均200，只有后者有v7 marker，registry确有两处经营页入口。

直接写入链已实证：dashboard-pipeline.service依赖dashboard-collect.service；先执行/opt/dashboard-collect/p2pah_unified.py，再执行publish_to_server.py。journal的_SYSTEMD_UNIT=dashboard-pipeline.service/PID28839在09:19:30.370093北京时间记录向/var/www/dashboard/index.html写605172字节，与incident文件SHA/尺寸/mtime吻合。实际builder模板去掉DATA/PROFIT/LOGOS/WORLD并统一换行后与incident代码完全一致。此前只据mtime/SSH不足以归责；当前证明了程序链，不证明哪个人启动。

同次[OK]日志列出22个成功目标：index.html、dim-daily.js、data.json、profit.json、9个series_*.csv、9个hourly_*.csv。不要把终端汇总“21”当精确文件数量。publisher用copyfile(tmp)+os.replace写根目录；data.json现场是普通文件，旧symlink说法不代表当前状态。本次未修复旧root别名或更改其它数据文件。

旧pipeline.timer定义每天12:15，fallback.timer每天18:15，均Persistent=true；dashboard-collect.timer当前不存在。两个timer在09:13:47启动；其[Unit]直接Requires相应service，激活timer会拉起service，这足以解释首次启动立即运行，而无需假定开机补跑。当前boot开始于9月27日23:48:04，故10月5日开机补跑没有证据。09:19那次具体启动请求人/原因仍未核实，当前LastTrigger为0，不能从它反推Persistent触发。

同事停止情况已独立核实：两个timer日志在11:49:17停止，随后disabled/inactive（卸载后is-active可报unknown），相关四service无运行；本轮没有停用/重启/重新启用它们。120分钟fs-transaction-collect.timer保留，下一13:19:12北京时间；Google09和周报周一02等保持。本轮没有自动反复恢复。root没有crontab；系统cron文件进一步独立核验由并行只读任务补齐，不能声称任意root未来调用已被拦截。

两套源码写入目标不同：合法collector的版本快照在/var/www/dashboard/fs-home/transactions，当前有效10项目/全站Order主源/Admin补缺版本未被旧根目录publisher取代。独立定时验证已确认当前systemd219不识别ReadWritePaths，该配置声明不是有效强制沙箱，不得据此声称root服务只能写某目录。旧root data.json/CSV的消费者及独有长历史需单独确认，不能仅删除/改名所谓僵尸文件。

最小后续方案（未执行、待单独确认）：保持当前两个旧timer状态，禁止旧publisher直接写index.html及根目录数据别名；旧独有历史/维度采集若仍需用，保留到独立legacy目录，经明确字段映射再只读消费。若未来重用timer先移除[Unit]中会立即拉起service的Requires，并分离采集/发布职责。页面发布只走现有guard；保护索引/数据名空间比反复恢复覆盖更可靠。不要删/改名index.html，不删/opt/dashboard-collect，不改部署公钥或账号权限。
