# 注册新增接线：合成 Linux QA 驱动

仅准备并静态检查，集成未运行，production_ready=false。本驱动与旧的43+4、7项合成单元测试分开计数，不重复它们。

## 冻结输入

源码checkout固定2152c8c9ea2fd68be3876349299d490d38903404；原candidate-manifest.json按实际SHA校验，含19项候选/说明/模板/测试条目及15项既有runtime依赖。必须是干净的真实Git checkout，拒绝链接、越界、额外候选文件与修改/未跟踪/忽略的输入文件。模板仍是模板；本驱动不把config/example当现场配置。

原薄入口的47项reviewed-root、21生产载荷声明及live-config不再是此新驱动输入。原始文件和历史manifest保持不变。旧full_nginx代码的闭包是总计10文件，包含master，不是master另加10份include；本次完全不使用它。

## CLI

只做驱动静态检查，不需要源码checkout，不导入候选、不监听网络、不调用Nginx：

    python3 -I -B tests/registration-release-delta-qa-20261007/linux_delta_entry.py --driver-check

实际集成必须在已获准、已具备Linux / Python3.9.18 / SQLite3.53.4 / Nginx1.26.1（auth_request及SSL模块）/ openssl的隔离环境中执行。绝对路径绑定到实际工具和独立源码checkout；输出必须是不存在的新JSON路径：

    LD_LIBRARY_PATH="$QA_SQLITE_LIB_DIR:$QA_PYTHON_LIB_DIR" "$QA_PY39" -I -B tests/registration-release-delta-qa-20261007/linux_delta_entry.py --source-root "$QA_SOURCE_CHECKOUT" --nginx "$QA_NGINX" --openssl "$QA_OPENSSL" --output "$QA_RECEIPT"

此命令不安装依赖或获取源码。使用同一个registration-target39-manual-qa.yml时，只有main上的手动触发、明确免费额度确认才可运行；默认registration_delta仅运行一次新增集成，显式runtime43_multiprocess4才会运行原工作。驱动取已合并github.sha，源另checkout固定2152c8c9；两个checkout均关闭持久凭据、submodule和LFS。准确Python及私有SQLite构建步骤复用原workflow；官方固定commit的Nginx仅在本次私有前缀构建，缺依赖就失败，不安装全局包。集成在独立network namespace中只启loopback，并使用独立PID namespace和对应/proc视图，随后降回runner UID/GID。namespace init或外层unshare退出时，剩余脱离会话子孙也随该PID namespace清理。

## 合成范围和时限

2747字节固定Nginx fixture只连接父进程预绑定的loopback端口；目录、日志、PID、TLS证书、用户数据及成员全部是自有临时夹具。fixture不含现场include、不读取生产config、不证明完整生产Nginx兼容。

保留六个实际Python worker及原断言：缺store/insecure启动拒绝；四admin/native editor/注册viewer；真实method/URI、可信user/role/groups覆盖；直接伪造头拒绝；readonly POST；旧FC cookie退役；敏感FC分析；verify503；注销/撤销跨恢复保持；DB和witness原字节保留。原“完整master/includes解析”断言仅替换为“合成fixture原生Nginx解析”。执行前后再次核对固定源码。

主执行上限120秒，外层另留15秒用于自有进程组清理和失败收据。控制器捕获TERM/INT进入finally；仅清理自己登记的独立进程组，先并行TERM、有界等待，再KILL仍存活者，清理失败即FAIL。driver-check的PASS仅指静态合同，不是Nginx/认证/目标版本执行通过。

本次衍生驱动另修复原薄入口两处控制问题：HTTP包装函数与模块同名造成的UnboundLocalError；默认SIGTERM导致finally不执行的脱离会话子进程清理风险。未修改任何业务候选源码、角色政策或权限边界。

## 必须继续标未验

当前cloud只有Python3.12.14/SQLite3.53.1，缺目标Python3.9.18/Nginx，所以本次未执行集成。生产实际systemd loader、UID/ACL、正式TLS、合法真实角色、全部现场Nginx/includes、fresh CAS和发布锁仍独立待验。production_nginx_verified=false、production_ready=false。只保留去凭据JSON收据；不记录Cookie/body，不上传合成DB或证书；不接生产、不部署、不修改Git权限。
