# 受限发布候选

`release_navigation_base.py` 是既有 publisher 精确字节，SHA256 为 `1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de`。桥仅在加载时插入首次新文件白名单、session apply、session restore、依赖安装顺序及首次写前只读接口维护stop及成功后manual整包回退拒绝六处接缝；沿用原发布锁、CAS、Hermes admission、任务互斥、备份和逐文件回滚。额外取得现有营销 collector 锁；第一文件替换前受控stop只读marketing range，固定unit/dropins、KillMode、ControlGroup并确认inactive/MainPID0/cgroup无残留。允许在途只读请求失败，不称完整排空。原collector及timer不停止、不更改。

`prepare_release.py` 接受私有读取的 SOURCE-MAP 与 dependencies、最终冻结 commit 和全新的输出目录，生成独立代码候选、发布器及 `approved-manifest.json`。始终 `releaseReady=false`；缺少真实基线列入 `baselinePending`，不能通过 inspect。目标固定20项，无夜间 source_snapshots 或 timer 载荷。

```text
python publisher/prepare_release.py --repo <候选仓库> --output <不存在的stage目录> --source-map SOURCE-MAP.json --dependencies <私有runtime-release-baseline.json> --source-commit <本次冻结40位commit> --admission <私有admission-baseline.json>
python <stage>/publisher/release_navigation.py inspect --manifest <stage>/approved-manifest.json
```

nightly.py、source_snapshots.py、实际已恢复enabled的schedule及恢复回执均只作原SHA保护，不恢复早期暂停状态。三timer沿实际active/waiting/enabled保护。停止结果UNKNOWN则零文件替换、不盲start；只有完整成功或逐文件完整回滚后start并以匿名401检查就绪，不触发采集。

inspect 只读核对现场文件、保护源、运行状态、旧image、原image tag和私有档案目录边界。`apply` 对 false 明确拒绝；后续实际受控发布须使用最终manifest原字节SHA及新release ID。不能重复执行已有release ID、镜像build intent或UNKNOWN导出；先查原journal/attempt。

image构建仅复制三个py，基于精确本地image ID，`--pull=false --network none`，断言必需build ARG，不下载依赖。新unit仅新增私有持久mount及独立新image tag，原网络/权限/凭据挂载保持。启动后核三个源码SHA、实际image ID和唯一可写档案mount；原tag不改。

技术事务失败或中断journal的恢复沿原publisher先恢复代码与unit，再启动原image。保留原xlsx、聚合缓存、未知attempt、数据库、队列、旧/新image与发布journal；不会清理证据换取重试。

已达到`applied-awaiting-actual-http-role-acceptance`的成功发布，manual rollback入口默认拒绝20文件整包退旧，避免恢复Order主源、错误品牌归属和Top先截断等旧口径。页面问题按既有受控UI路径仅退本次UI；后端问题保留第0批合同并作前向修复。成功后确需退旧基线，须另有明确例外范围；当前没有默认可执行整包退旧入口。该门禁不影响apply内部失败恢复和未完成事务的恢复。

当前检查为本地合成CAS、回滚和image命令合同；真实Linux锁、Docker构建、实际权限/业务入口尚须现场验证。目录 `/var/lib/fc27-es-exports` 必须 root:root 0700，持久bind；档案512MiB/512文件上限，64MiB磁盘余量，超限拒绝而不删旧数据。
