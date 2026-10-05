> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

> 当前revision 2覆盖及外部依赖以 [integration/README.md](integration/README.md) 为准。下文保留v2阶段历史背景；portal/任务台/Players/NBA/MLB已补源码，不等于运行验收通过。

# 缺失依赖与最小补齐资料

首版是可离线检查的源码候选，不能在新服务器直接一键运行完整平台。

| 未纳入项 | 实际影响 | 补齐方式 |
| --- | --- | --- |
| 认证portal/gate、nginx保护配置、角色与会话数据库 | 新环境不能复现登录/服务器读写权限；不能以匿名访问替代 | 分别审核非秘密认证源码、示例契约和路由模板；运行密钥/角色数据库继续在仓库外 |
| p2pah_session_service及受控上游访问配置 | Order/Admin采集与Coins写入无法独立运行 | 当前服务作为外部受控依赖；需独立确认非秘密实现/接口模板范围，不能复制会话或账号凭据 |
| 真实业务快照、Google/周报输出、旧PROFIT JSON、业务数据库 | 本地只有模板与合成测试，不显示真实经营值 | 运行时由现有服务器生成/提供；仓库外保留，不上传数据 |
| Players/Gallery、任务台后端及其它未核实游戏模块 | 本候选单独部署会缺模块/API，现有首页入口仍保留原服务器目标 | 逐模块确认真实源/依赖后纳入；没有删除线上模块 |
| 有效部署路径、当前systemd/nginx/容器约束完整安装包 | 目录映射不等于可用安装器，没有自动发布CI | 分开核实非秘密模板与发布身份；保持现有guard发布 |

给大超的最小请求，不要整工程ZIP或Git历史：

1. 他实际维护模块的源路径、逐文件SHA、线上目标、当前是否上线；未上线改动的文件名单及对应源码。提供Git HEAD/分支/remote名称和dirty文件名，避免token URL。模块归属双方明确，不按名字推定。
2. 若其电脑负责旧经营HTML生成/上传，提供活动的build_dashboard.py、ensure_today_published.py、publish_to_server.py、p2pah_unified.py、fetch_dim_daily.py；仅存在且实际使用的文件，不索取凭据/真实订单。
3. 对应Windows计划任务的名称、可执行文件/脚本路径、已脱敏参数与上传目标。须找出写入`/var/www/dashboard/index.html`的上传步骤，停止或替换这一小段；采集可保留，不能停整个数据作业。本机/服务器已知旧publisher停用不证明他电脑已停。
4. 未纳入的模块按第1项逐个补；认证实现若需纳入另走明确源码审核，不提供数据库、Cookie、私钥、密码、运行配置或缓存。

当前已实证云端旧dashboard-pipeline.service/publish_to_server.py直接覆盖，启动人及09:19请求来源未知。上述云端5代码路径/SHA已读核实；同事只需提供其不同版本、未上线改动及仍存在的本地上传动作，无需重复整包。两个旧云端timer已由同事停止并独立核实，本轮未停止或重新启用。未远程操作同事电脑。当前candidate-v2已解决本次线上HTML漂移；根因仍对应原项目OD-18 OPEN。候选没有commit、push、remote或邀请。

旧链实际触发/写集合和最小方案见PIPELINE-INCIDENT.md；当前旧发布服务文件保留，不自动当作候选规范源。
