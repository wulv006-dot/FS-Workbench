> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

> revision3增量：NBA依赖write_contract.py、门户依赖fc_read_scope.py；完整候选变更及仍阻断事项见REVISION-3-REMEDIATION/DECISIONS。下文revision2合同作为历史接入背景保留。

# 候选运行接口与安全接入合同

全部为待批准接入契约，不是本轮已经绑定的生产路径。原线上功能与认证保持。

- NBA：server.js/api_security.js/p2pah_api.py/ocr等部署映射保留/opt/nba-reprice/backend；默认127.0.0.1:8765，NBA_DATA_DIR默认用户家目录.local/state/fs-nba-reprice，显式配置须在NBA源码目录外，Python/Node共享。不自动搬旧凭据。token模式须既有ACCESS_TOKEN+OPERATOR_NAME或OPERATORS；缺失拒绝，映射到三admin才可写。proxy模式只能既有回环nginx覆盖X-Auth-User/X-Auth-Role，必须另核对有效nginx配置，不凭注释称可信。读GET登录身份，写POST/JSON/admin/WRITE_READY=true/确认NBA_PRICE_APPLY/有限正价格，Origin出现时必须在配置白名单。候选前端逐次弹窗，自动无确认写不被允许；未来是否采用此交互需发布前确认，未改线上自动化。
- IGGM：sites及三个core都依赖url_guard.py；每次连接/重定向校验并pin数值IP；禁环境代理；CookieJar正常行为保留。只有iggm/aoeah/u4gm自身或子域、http80/https443；新站点另评审，不能通过任意category URL放行。
- MLB：/opt/mlb-online/mlb_server.py/static_path.py与/var/www/mlb-online/index.html共同映射；已有nginx登录保护和X-Remote-User须现场验证。候选前端不再携带内嵌Basic凭据，所有API同源会话。静态根须由受信任进程维护；组件校验不是对可同时改目录的root提供race-proof保证。
- 部署hub：server依赖bundle_policy.py；客户端保留单文件下载兼容，内嵌由同一策略生成的代码（SHA头部），禁止手改漂移。P2PAH_DEPLOY_CONFIG/P2PAH_HUB_CONFIG显式指定仓库外配置，默认工作目录/var/lib/deploy-hub。不创建/移动真实配置。静态包路径/后缀/内容/ZIP先校验；同源HTML/JS仍只给可信受权发布者，后续origin隔离由架构阶段评估。
- 门户：auth_portal.py读取已有签名密钥、登记组与三admin policy；外部FC服务不作为内部身份桥。登录html/status不改。cookie密钥、账号/组、FC外部门禁仍外置；不能运行候选就宣称既有角色迁移通过。
- FC：fc27_cloud_browser/repricing_dom.js映射宿主/opt/fc27-cloud-browser/repricing_dom.js，现有shell bind到容器/opt/repricing_dom.js；preview_backend.py bind为/opt/preview.py，root quote JS映射/opt/repricing_logic.js，既有CDP和fc27-cloud-session:1镜像外置。preview/cache shell含既有权限和Docker操作，仅保存，未执行、未验证有效部署。现有队列/锁与unknown不重试保持。
- Players：fc27_players_cloud/source_manifest.json明确cloud.9的45源；自动/全局WRITE仍默认false，批准指定HTTP例外和手动新卡/图片开关不扩大；仅当前manifest字节匹配，真实currentsymlink/容器/媒体后端和锁读bind待现场验。源码中DATA_ROOT可配置，真实数据不入清单。
- 任务台：server SCHEMA是内联，不缺独立schema；web三件套来源本机当前规范。seed示例只给空结构，不收真实成员/任务数据库。三级权限与守护三admin仍是现有合同，未新建角色/帐号。
- fs120/range/Google：source-manifest历史规范路径继续保留；Order与Admin分系统类别ID不得合并；120min/60sec、Google09/300、周报Mon02不变。准确区间测试现在直接加载release/source并校验镜像SHA；这不是实际Linux加载或下一自然周期证据。

已确认存在但尚非候选完整运行闭包：FC activity/gate外置服务、P2PAH会话受控运行配置、Google授权、有效nginx/systemd/drop-ins/镜像与库数据。旧dashboard-collect/publisher刻意不纳入或恢复。

## revision3准确运行增量

NBA Node与Python共享显式仓库外NBA_DATA_DIR；新增writer.lock只flock/Windows文件锁，不删除、不清现有业务锁。HTTP可携32hex requestId；旧客户端缺ID由服务器生成新ID，因此它们不具跨请求去重保证；新客户端/自动执行合同必须稳定复用确认计划ID。每次Node都有不同.plan-transport文件、wx/600，传入不可变planJson/hash；Python验证其admin actor/确认/价格，再锁完整生命周期。receipts/{ID}.json先pending，完成原子回执；同ID同hash返回回执不再写，不同hash拒绝，pending/timeout状态未知绝不自动重试。未知状态不等于零写入；written=false可能部分成功，审计writeOutcome区分。可信CLI单次write_one/apply_prices也被同一生命周期锁覆盖，但不冒充HTTP逐计划授权；CLI write必须使用绑定envelope。配置、已有文件ACL/链接及锁目录可信性需现场另验，不自动搬凭据。

门户仍/verify原入口，内部签名+live组优先按原policy；仅无内部登记时、ungrouped FC verifier、严格原FC只读URI可问既有8896 gate。FC-only永远readonly、只X-Fc27-*、无内部Auth组；写/未知URI/内部dashboard/docs/tasks/营销/Gallery拒绝。FC gate本身仍外置、没有运行或修改；过期/禁用/未登记由其verify决定，不把用户名当签名验证。四共享脚本问题保持发布阻断，不授权透传私有JSON。有效nginx必须覆盖/清除来自外部的身份头；所有candidate mock不等于生产可信proxy已验。
