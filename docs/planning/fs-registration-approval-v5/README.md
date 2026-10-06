# FS 自助注册与审批 v5：独立候选入库说明

## 当前结论

本次仅保存可审阅的隔离候选，`releaseReady=false`。新注册账号默认只能查看平台介绍与申请进度；管理员明确批准后授予全局只读候选身份。拒绝、撤销、同名碰撞、身份来源故障均按失败关闭处理。没有接入线上账号、改生产权限或执行真实迁移。

基线为 `bc3b29531cec2fab3fc090385f3d7d126eb9ada7`。只新增 `candidates/fs-registration-approval/v5/` 与本说明目录，全部精确路径、SHA256、字节数和 Git blob 在 `REPOSITORY-SOURCE-MAP.json` 中。22 个候选源码/测试/界面文件保持原字节。包内根文件改放本目录 `package/`，避免覆盖仓库 README、AGENTS 或已有文档。

## 验证证据与边界

- 独立 Linux Python 3.12.14 / SQLite 3.53.1：发现 81 项，79 通过、0 失败、0 错误、2 个 Windows msvcrt 专用项跳过；两个 Linux fcntl 案例均实跑通过
- 独立的只读、身份来源中断、大小写同名碰撞、撤销和导入无副作用探针：172 断言通过
- 17 个 schema 异常拒绝并保持数据库字节；11 个合成初始化进程中断点恢复证据已保留
- 既有 Windows 记录：79 通过、2 Linux 专用项跳过；10 个本机浏览器检查通过。这是历史 Windows 证据
- 本次独立 Linux 浏览器未启动：已安装 Playwright 缺少匹配的 Chromium，新增浏览器通过数为 0。没有安装依赖或替换浏览器，不能把既有 Windows 结果写成 Linux 浏览器通过
- 协调复审报告已静态关闭 RA4-B1，未报新 P1/P2；此前 RA3-F1/F2/F3 关闭结论保留。冻结 REVIEW 中“等待复审”和“未跑 Linux”是打包时点文字，不覆盖后续独立证据
- 14 条只读路由合同是在适配器边界验证，HTTP 示例只实现三个合成业务入口，并非完整生产消费者覆盖

独立 Linux 日志、验证记录及探针在 `independent-linux/`。这些都是隔离合成测试结果；未打包数据库、账号组清单、密码哈希、会话 Cookie、真实签名密钥、经营数据或生产运行日志。三张历史 UI 图已目视检查，显示合成申请且明确标识本地演示。

候选源码中的测试口令和测试密钥均有 synthetic 标记，仅用于临时测试沙箱；Cookie 名称与四个管理员名称是接口/策略常量，不是凭据或账号库。模式扫描未发现真实凭据特征，不声称静态扫描能证明绝无秘密。现有 gitignore 对 evidence 目录的默认排除仍保留，本批只逐个纳入源清单列明、已检查的合成证据，不放宽全仓规则。

## 历史合同与相邻 PR

- 当前已独立读取 PR #2 的 CURRENT-CONTRACT 与 AGENTS 差异：全局门户策略为 wulv / chenchao / DY / fstech，policy SHA256 为 `b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017`。本候选保留此来源常量，没有新增真实账号或赋权
- main 旧三管理员文字和 FC-only 桥是历史基线；本 PR 不修改这些文件。NBA 原三管理员模块守卫保持不变，不能由全局候选推导 fstech 的 NBA 写权限
- PR #1（RPG）head `1466362fc0c8fea1a09ba9610cfb0993486c048a`、PR #2 head `c5e641c82cba3280b3d2cf97179cd5ab260e94b8`、PR #3（checker）head `8eed759b98218615d9857660b35c43a07c5184fd` 均作为只读背景，未修改它们的分支或文件
- 本批新路径没有与三份 PR 的变化文件重叠。checker 的精确白名单尚未包含本批；合并前必须根据届时实际合并树，另行审查并重新生成准入清单，再重跑 checker。不能扩大通配放行或把空 CI 检查当通过

## 复现

在仓库根目录，先验证本批冻结字节：

```sh
python3 -B docs/planning/fs-registration-approval-v5/verify_repository_batch.py
cd candidates/fs-registration-approval/v5
python3 -B linux_validation.py --output /tmp/fs-registration-v5-review-evidence
```

核心测试只需已有 Python 3.10+ 和 SQLite stdlib，独立实跑环境为 Python 3.12.14。测试仅使用自己创建的 fs-registration-* 临时沙箱和回环 HTTP；输出必须放源码目录外，不指定生产存储。不要在未检查环境中安装浏览器或运行 archive.py。

原始独立探针脚本未改动，按原验证布局在隔离临时目录中使用：把完整冻结包解压到 `package/`，将 `independent_probes.py` 放在其相邻目录后运行。脚本只读取该相对候选源码，生成临时合成身份并输出探针结果；不要把脚本直接当生产入口。

原始 `package/verify_package.py` 仅用于未改布局的原 ZIP，不适用于仓库中映射后的 docs 布局。这里提供的 verify_repository_batch.py 验证本批映射后的精确文件集，不替代全仓 checker。

## 合并与发布门槛

共享入口由吴律主导、陈超参与；真正影响到的业务模块仍需逐项 owner 确认。入库、合并、生产验收、上线是独立状态；此候选不能直接部署。

仍需核实完整生产消费者和可信 method/URI 边界、原门户退出 denylist 接线、所有原生账号创建方共用命名空间锁、实时完整名称源、Nginx/TLS/Secure Cookie、ACL 与目录持久性、真实角色负向矩阵、当前现场源码/依赖 SHA、账号迁移与恢复方案、受控发布和回退。真实迁移、账号/权限、服务及生产动作必须在具体范围和时点获得批准。

冻结包中的 uploadApproved=false、gitMutation=false、未提交/未推送是历史打包记录，保持原样以保留证据。当前是否入库以远端 PR 的确切 head 和读回结果为准。没有合并、部署、Actions 新增/启用、账号/权限修改或任何其它 PR 修改。

