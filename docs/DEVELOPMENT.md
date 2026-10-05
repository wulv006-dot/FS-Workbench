> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

> 当前revision 2覆盖及外部依赖以 [integration/README.md](integration/README.md) 为准。下文保留v2阶段历史背景；portal/任务台/Players/NBA/MLB已补源码，不等于运行验收通过。

# 开发环境与运行边界

首批保留原相对目录，不从旧整个工程继承Git索引。Python运行逻辑与普通HTML/CSS/JS并存；后台主要stdlib，浏览器采集依赖Playwright，Google网络读取依赖google-auth/requests；具体版本按各源requirements与服务器受控环境复核。Windows日期测试须tzdata；本轮隔离依赖固定为tzdata==2025.2。

运行离线候选检查：安装requirements-dev.txt后执行 `python tools/check_candidate.py`。脚本用系统临时目录保存报告/隔离副本，禁止单元测试外部网络和外部进程；只允许测试自身loopback。真实认证、浏览器配置、订单快照和外部私有配置需已有受支持交接，不在仓库内。

配置示例位于config/examples，只示范非秘密结构；均无真实凭据，不自动生成账户/角色、不启用写价或采集。systemd示例保留已批准120分钟/每日09/周一02的意图，不声称每个本地示例等于当前有效生产unit。上生产前必须另核对当前unit及完整依赖。

本候选不是可直接整体部署的包：经营HTML冲突未解决、认证源未纳入、Players/Gallery及任务台后端等仍运行于现有服务器但未迁移。采集器中的p2pah_session_service/会话配置属于仓库外既有受控认证依赖，不能用新账号或伪会话填补。

统一经营HTML模板及仓库外构建见RESTORED-V7.md；缺失认证/运行数据/模块对运行的具体影响见DEPENDENCIES-AND-OTHER-MACHINE.md。不能把离线测试通过当成完整可自托管部署。
