> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# 集成审查发现与取舍

本轮证据是用户本机原包和当前工作树/冻结 v2；不是服务器实时审计。新包 Python 仅 AST、JS 仅语法检查，没有运行其源码或部署脚本。

| 优先级 | 已观察问题 | 证据 | 本轮取舍 |
| --- | --- | --- | --- |
| 阻断整包分享 | 包含 cookie 数据行，且混有日志/报告/XLSX/历史 ZIP | `opt/nba-reprice/backend/.cookies.txt`、`.iggm.cookies.txt`；运行数据清单 | 所有留忽略的 raw，原包保留；不能把原包当脱敏源码上传。未核查 cookie 当前有效性，不更改凭据 |
| 阻断旧发布恢复 | 说明要求恢复已批准退役的旧链 | 既有14:05退役与15:25新 fs120自然成功证据；本轮说明读投影 | 旧 `/opt/dashboard-collect`、三个旧masked unit及补丁/发布脚本不导入活动候选，不启用旧timer |
| 阻断权限替换 | 来包4admin而本机规范源3admin | `opt/fs-access-policy/access_policy.py`含fstech；本机 `fs_permissions_unification_20260930/access_policy.py`为wulv/chenchao/DY | 新候选逐字保留本机3admin源码；拒绝导入来包4admin，不改变生产账户/权限。包内auth模块与候选policy仍需独立运行验证 |
| 重要完整性缺口 | 未包含新fs120模块与首页/Google dashboard静态源 | 无`opt/fs-transaction-snapshot`及对应units，无`var/www/dashboard`；原171有已有规范代码 | 候选保留v2规范代码补齐，不用旧fs-supplement collector替换新collector；从缺包不能推出线上缺失 |
| 重要别名冲突 | 宿主采集器与容器采集器同名不同SHA | 来包根层competitor d339…，collector子层13691…与原候选一致；FX子层1db6…一致 | 继续容器已验规范源；只建立路径映射，不复制旧宿主别名覆盖 |
| 重要来源事实 | range与网关、FC榜实包匹配；说明引用staging调用链未证实 | range0a03…、gateway90cf…、FC HTML40ec…；包内service ExecStart直接range_api.py，staging/publish_reader.py不在包中 | 文件SHA一致部分确认；有效unit/drop-in/process调用链仍待现场只读核实，不执行包内install脚本 |
| 重要历史混入 | FC Players cloud.1–cloud.9共387 release文件/主deployment.lock；FC ops旧daily采集代码 | archive-inventory及目录清单 | 不把所有历史release称活动源码；本轮新增候选暂不收入Players，旧FC ops后端不替代统一快照统计。原生FC运营HTML保持 |
| 中等说明差异 | 说明774行/773扫描与实际777项/778文件、3链接未移除不一致 | manifest-verification.json、archive-inventory.json | 实际777项全部匹配，清单自己唯一未列，不能称篡改；说明数字为陈旧，3链接安全排除 |
| 中等兼容性 | 新Python源码含Linux绝对路径/crypt、外部库，host219 unit限制；只有AST通过 | staticPython、units配置矩阵、auth源码 | 不宣称Windows可运行整个后台；runtime/path/依赖明细作为发布前门槛；未安装软件/重启服务 |
| 中等安全待验 | 鉴权依赖nginx受信任header和loopback，auth登录POST未见Origin校验；deploy等写入口需确认全部真实门禁/路径安全 | 新模块源码静态阅读 | 不凭函数名判安全，不改登录页或权限语义；待隔离Linux/真实会话验收。未做攻击请求/改价/采集/账户写入 |
| 低风险清理 | 完全一致重复文件/历史patch/runtime数据混淆维护 | 58归档SHA匹配、完整成员表 | 58个副本不重复复制，保留精确映射；不搬迁原工程、不重写相对/绝对路径、不全库格式化 |

## 六类必保功能的来源区分

| 功能 | 本轮保留来源 | 验收状态 |
| --- | --- | --- |
| FC赠送公式、Xbox及15档策略 | 原171的FC引擎/降幅/同步规范源；来包同SHA引擎作为一致证据 | 既有合成引擎/降幅合同本轮重跑；真实写价未做 |
| 平台恢复、目录/读写权限 | 本机3admin policy、原受控网关及项目根规则 | 静态三管理员断言；真实角色/OS目录权限未验 |
| 经营Aion2与全站v7 | 原统一快照/range/分离私有数据的v7模板，Order826/Admin891 | 已有日期/Aion2状态合同本轮重跑；没有用D4竞品min(G2G,ELD)替代财务统计 |
| FC分类原生商品排行 | 原FC HTML与经营FC分类原生读取源，来包40ec…一致 | 原代码保留；本轮无真实报表/排行榜浏览器验收 |
| 日历、日期边界、范围状态 | 原FC/经营模板与日期/日历JS规范源 | 三组JS离线合同通过；原包旧build不覆盖 |
| 周报1w修复 | 0a03…规范range与已匹配周报适配器 | 59 parser/11周报合成合同通过；历史自然失败/人工成功/下次自然待验分开 |

## 优化边界

本轮只做可证明等价的字节保留与重复副本省略、源码/运行数据分离、路径/来源/验证合同规范化。未删除原文件、未更改业务算法、业务参数、Ponytail、价锁、timer或生产发布机制。新模块尚无可信纯测试入口，未执行包内自测/安装/patch/权限脚本。

原包位于用户指定`新建文件夹`，不在本轮源码上传允许清单中。项目.gitignore的`**/data/raw/`保护解包原件；原始tar.gz是否忽略需独立检查并最小加精确忽略项，禁止整包git add。本轮不执行Git索引/提交/推送。
