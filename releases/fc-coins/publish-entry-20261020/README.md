# FC27 受控发布入口（publish-entry-20261020）

用户 2026-10-20 要求：发布权只开放**一个固定、受保护的宿主入口**；仓库里的东西只能是调用端，
不能把任意版本的 `tools/*.py` 直接当 root 程序执行；源码写入限定到已批准模块的**具体文件清单**；
`/var/lib/fc27-cloud` 不能整目录可写；`systemctl` 只允许对确切单元做必要动作；
PR 合并、产物属于准确 merge commit、前后哈希都要验证，并明确"什么改动已有发布授权"。

本目录只交付**方案与离线实现**，未申请任何宿主权限，未部署。

## 1. 两个角色，权限不重叠

| 角色 | 位置 | 权限 | 能做什么 |
|---|---|---|---|
| 调用端 `source/fc_publish.py` | 仓库（任何人可改、可读） | 无特权，只读 git 对象 | 离线预检 + 打印宿主命令；**不能发布** |
| 宿主入口 `source/fc27_publish_entry.py` → `/usr/local/sbin/fc27-publish` | 宿主，root:root 0755，一次性人工安装 | 唯一持有 root 的一段 | 重新校验一切并执行替换；**不采信调用端结论** |

调用端没有 sudo、没有 `/opt` 读写、不写 `/var/lib`；宿主入口不 import 仓库、不读工作区、
只读 `git cat-file` 的对象字节。因此"仓库里改了发布脚本"不会改变 root 的行为。

## 2. 精确路径

宿主固定路径（本入口只认这些，全部写死在代码或策略里）：

| 用途 | 路径 |
|---|---|
| 策略（root:root 0644） | `/etc/fc27-cloud/release-policy.json` |
| 宿主仓库检出（root 所有；刷新由 root 单独执行，入口只读它的 git 对象） | `/opt/fc27-workbench` |
| 主分支引用 | `refs/remotes/origin/main` |
| 状态根（既有） | `/var/lib/fc27-cloud` |
| 本次备份（唯一新建目录） | `/var/lib/fc27-cloud/rollback/<UTCSTAMP>-<module>/` |
| 发布收据（唯一新建文件） | `/var/lib/fc27-cloud/releases/<UTCSTAMP>-<module>.json` |
| 队列锁（**先用模块自带 `queue_mutation`**：`O_NOFOLLOW`、不创建、校验属主/权限/`nlink==1`/`0o644`、`NB flock`） | `/var/lib/fc27-cloud/state/automation-tick.lock` |
| 价格写锁（**队列锁之后**再取，`O_NOFOLLOW`、不创建、`NB flock`，同样校验元数据与 inode） | `/var/lib/fc27-cloud/state/price-writer.lock` |
| 空闲判定（**只读**） | `queue/*.json`、`jobs/*.json`、`executions/*.json` |
| 监控读回（只读 GET，既有身份头） | `http://127.0.0.1:8879/monitor` + `/etc/fc27-cloud/monitor-user` |

源码写入白名单：`release-policy.example.json` 里 `modules.fc-coins.targets` 列出的 **37 个具体文件**
（来源 `docs/provenance/source-manifest.json` 的已登记映射，不是把目录整体开放）。
每个目标必须**逐字符等于**策略中的绝对路径，`realpath` 复核、禁 symlink；路径不来自 argv。

## 3. 调用参数（唯一形态）

```
sudo /usr/local/sbin/fc27-publish <module> <release> <pr-number> [--apply]
# 例：sudo /usr/local/sbin/fc27-publish fc-coins natural-recovery-20261020 231
```

- 只有三个位置参数 + 一个可选 `--apply`；多一个参数即 `usage` 退出（码 2）。
- `module` 必须命中策略；`release` 只允许 `[a-z0-9][a-z0-9-]{0,63}`（挡 `../`、`/`）；
  `pr` 只允许十进制。**没有任何路径、命令、单元名、哈希参数。**
- 默认是 check：只校验并打印计划，不写。`--apply` 才可能写，且要求 `euid == 0`。

## 4. 校验顺序（任一失败即停，不写）

1. 策略可读（同一 fd 校验属主/权限）、`version == 1`、模块名/目标名/根前缀/单元动词/入口文件都合法。
2. 发布名合法；`<release_prefix><release>/approval.json` **存在于 origin/main**。
3. `approval.merge_commit` 是 40 hex、**是 origin/main 的祖先**、其 subject 含 `(#<pr>)`（squash 绑定）、
   `approval.pr == pr`、`approval.scope` 与 manifest 的 targets **集合相等**。
4. manifest 取自 **该 merge commit**（不是工作区）；每个 `before`/`after` 是合法 sha256。
5. 每个候选字节 = `git cat-file blob <commit>:<base>/source/<name>`，其 sha256 必须等于 `after`。
6. **授权（同一 fd）**：逐级 `O_NOFOLLOW` 打开授权文件及其父目录（任一级是符号链接即失败），
   在同一 fd 上校验：常规文件、`nlink==1`、属主=策略 `authorization.owner_uid`、权限不含组/其他写、≤64KB；
   读完后用 `dir_fd` 重新比对 inode，防止"先 stat 后读"之间被替换。内容要求 `merge_commit` 与本次一致、
   `scope` 与文件清单完全一致、`authorized_by` 非空、`expires_at` 带时区且未过期，
   且该 merge commit 的**提交作者**在策略白名单里。
7. 每个目标：在策略里、路径与策略逐字符一致、本身不是 symlink、**父目录每一级都不是 symlink**、现场 sha256 等于 `before`。
8. 重启单元 **由真实 import 闭包推导**（`unit_entrypoints` → 模块依赖图），推导出的每个单元必须在策略里授予 `restart`/`is-active`。
9. 空闲：`queue/` 无文件；`jobs/` 无 queued/running、无"auto_cycle 已 confirmed 但未 completed_at"；`executions/` 仅接受已确认终态或完整审计维护证明；未知、缺失或损坏状态一律阻断（只读判定）。
10. **取锁**：先 `queue_mutation`（模块自带协议），再 `price-writer.lock`。
    锁只以 `O_NOFOLLOW` 只读方式打开、**不 mkdir、不 `a+b` 创建**：缺失、符号链接、`nlink!=1`、属主不对或被组/其他写，一律停止。
11. `is-active`：推导出的单元必须全部 active。

**取锁后、停服务后各再核一次**（`reverify`）：授权有效期、候选 blob 哈希、现场 `before`。
等待锁之前的检查结果不能直接用于发布；任何一处不符即中止，未写先退回。

**什么算"已有发布授权"**（可验证，不靠自填字段）：

1. 宿主策略 `/etc/fc27-cloud/release-policy.json` 声明该模块可发布、哪些文件、哪些单元 —— root 维护，仓库改不动；
2. 宿主授权文件 `authorizations/<module>/<release>.json` 绑定**同一个 merge commit** 与**同一份文件清单**，
   有到期时间，由 root 写入且不可被组外改写；文件与父目录都不接受符号链接；
3. 该 merge commit 的**提交作者**在策略 `authorization.commit_authors` 白名单里；
4. 仓库里的 `approval.json` 只是声明（pr / merge_commit / scope），必须与上面三者对齐 —— 它本身不构成授权。

所以"在 PR 里填个 authorized_by 和时间"发不出去；PR 合并本身也不构成生产授权。

## 5. 允许动作（穷举）

| 对象 | 动作 | 范围 |
|---|---|---|
| 白名单文件 | 原子替换（临时文件 `.<name>.publish-tmp` → fsync → `os.replace` → fsync 目录），保留 mode/uid/gid | 仅 `targets` 内的 37 个路径 |
| systemd | `is-active`、`stop`、`restart` | 仅 `fc27-cloud-api`、`fc27-cloud-worker`、`fc27-automation-tick.timer` |
| 单元选择 | **由真实 import 闭包推导**：哪个单元的入口进程（策略 `unit_entrypoints`）直接或间接 import 了被替换的模块，就重启哪个单元。`automation_tick.py` 被 api、worker 同时 import → 三个单元全部重启；`.sh`/静态文件不匹配任何模块 → 不重启 | 同一单元只停/启一次 |
| 目录 | `mkdir` 本次 `rollback/<stamp>-<module>/`、`releases/` 收据 | `O_EXCL`，不覆盖既有 |
| 读 | 策略、git 对象、目标现场哈希、`monitor` GET | 只读 |

**不允许**：任意 `systemctl`（含 `enable/disable/mask/reload-or-restart`）、整目录写、
改写/删除 `queue`、`jobs`、`executions`、账本、策略、凭据、锁；`sudoers` 只给
`/usr/local/sbin/fc27-publish` 这一条命令，不给 shell。

## 6. 失败与回退

| 阶段 | 行为 | 收据状态 | 退出码 |
|---|---|---|---|
| 校验 | 直接退出，不创建任何目录 | 无 | 3（`baseline_drift` 为 4） |
| 忙/锁占用 | 直接退出 | 无 | 5 |
| **停服务失败** | 立即停止发布，**不替换任何文件**；已停的单元按回退流程处理 | `rolled_back` | 6 |
| 停单元后未写入 | 重新拉起单元 | `rolled_back`（`nothing_written`） | 6 |
| 写入/重启/读回失败 | 停单元 → 用备份换回 → 重启 → 逐个核对 `before` | `rolled_back` | 6 |
| 回退停服务失败或文件字节无法恢复到 `before` | 停止重试，保留现场 | `unknown_write_state` | 7 |
| 字节已恢复但单元没起来 | 记录 `unit_errors`，不当作成功 | `rolled_back_unit_errors` | 6 |

收据始终落盘（成功或失败都写），另有 `journald`。失败后**不自动重试**，未知写入视为未知，不盲重放。
备份目录保留，人工确认后再清理。

## 7. 安装（宿主，root，一次性）

```
sudo bash releases/fc-coins/publish-entry-20261020/install.sh     # FC27_PUBLISH_GROUP=fc27ops 可覆盖
```

脚本只做六件事：校验源码可解析并打印 sha256 → 检查 `/opt/fc27-workbench` 检出是否有 `refs/remotes/origin/main`（缺则给命令，不自动 clone，私有仓库凭据由 root 侧准备）→ `install -m 0755` 到 `/usr/local/sbin/fc27-publish` →
**策略存在则不覆盖** → 检查 `/etc/fc27-cloud/monitor-user` 是否存在（不打印内容）→ 打印 sudoers 片段。
既有目录的属主与权限保持原样，仅创建缺失目录；授权作者列表默认空，须按明确授权配置。拒绝入口和策略符号链接。不启停单元、不碰 `/opt` 源码、不写 `/var/lib/fc27-cloud`。最后用"无参数应返回 2"自检。

sudoers 只放行一条命令，人工写入并 `visudo -c`：

```
Cmnd_Alias FC27_PUBLISH = /usr/local/sbin/fc27-publish
%fc27ops ALL=(root) NOPASSWD: FC27_PUBLISH
```

## 7.5 授权与卸载（安装属于持久发布权限，需单独授权）

**CI 通过不构成安装授权。** 本入口一旦装到 `/usr/local/sbin` 并配上 sudoers，就等于长期放行
"以 root 替换 `/opt/fc27-cloud-browser` 指定文件并重启三个单元"这一能力。因此：

1. 安装前需要有明确的人、明确的时间窗、明确的范围（模块 + 目标清单 + 三单元），
   并书面记录谁授权、授权到哪一版 `fc27_publish_entry.py`（sha256 记录在收据与安装输出里）。
2. 安装只做加法、不启停服务；真正的第一件事是**只跑 `--check`**（不加 `--apply`），
   看计划是否符合预期，再决定是否执行。
3. 卸载/收回（同样需要授权）：

```
sudo rm -f /usr/local/sbin/fc27-publish /etc/sudoers.d/fc27-publish
sudo rm -f /etc/fc27-cloud/release-policy.json          # 先备份/留存，便于审计
sudo visudo -c                                          # 确认 sudoers 语法未坏
```

`/etc/fc27-cloud/monitor-user`、`/var/lib/fc27-cloud/rollback|releases` 为既有身份与审计记录，卸载入口时**不删**。

## 8. 现场校准（发布前必做，只读）

策略里的目标是**路径白名单**，不等于"现场就是这个哈希"。两步：

```
# 1) 生成回读命令
python3 source/calibrate.py --policy /etc/fc27-cloud/release-policy.json --module fc-coins --emit-commands

# 2) 把回读结果贴回，得到差异表（有漂移/缺失退出码 4）
sha256sum /opt/fc27-cloud-browser/*.py | python3 source/calibrate.py \
    --policy /etc/fc27-cloud/release-policy.json --module fc-coins --readback -
```

报告分四类：`matched`、`drift`（期望 vs 实际）、`missing`（策略有、现场没有）、
`not_in_policy`（现场有、未登记，仅提示不阻断）。要和某次发布清单对照时加
`--targets releases/fc-coins/<release>/targets.json`，按该清单的 `before` 比较。

## 9. 演练：只检查、不发布（已实跑）

```
python3 source/rehearse.py --release-dir ../../../releases/fc-coins/<release> --pr <pr>
```

沙盒内用**真 git 仓库**跑 `GitArtifacts`（`git cat-file` / `merge-base --is-ancestor` / `log -1`）、
真实 sha256、真实 flock 与空闲判定；systemctl 用桩，不碰任何单元；不写 `/opt`、`/var/lib/fc27-cloud`、`/etc`。
默认跑五个场景：`base`（应出计划）、`candidate`（应 `candidate_hash_mismatch`）、
`baseline`（应 `baseline_drift`）、`scope`（应 `approval_scope_mismatch`）、`pr`（应 `approval_pr_mismatch`）。

2026-10-20 用 PR #231 的真实发布目录（4 文件真实字节）实跑结果：五场景全部符合预期，
`base` 在真实字节上推导出三个单元都要重启（`automation_tick.py` 被 api、worker、timer 同时加载），同一单元只停/启一次。

沙盒的三处映射会写进报告 `scope`：策略 `/opt` 路径映射进沙盒、`approval.json` 为生成（`rehearsal: true`）、
无 `--live-dir` 时用候选字节当现场基线。**这些都不是生产状态**，只证明校验路径与拒绝条件成立。

## 10. 离线测试

```
cd releases/fc-coins/publish-entry-20261020 && python3 -m unittest discover -s tests -t tests
```

90 条核心用例，另含安装目录保护测试，覆盖：策略/白名单越界、目标名/发布名路径穿越、PR 与 merge commit 绑定、
scope 不一致、候选字节与 commit 不符、现场基线漂移、symlink、队列/作业/执行未结、
锁占用、单元 inactive、单元动词越权、成功发布（备份+收据+原子替换+停启顺序+去重）、
重启失败回退、读回不符回退、保护文件漂移回退、健康超时回退、回退失败→unknown、调用端预检与不写入。

测试全部注入假 git/systemd/monitor，**不连网、不起进程、不碰真实 `/opt`**；`install.sh` 另有 `bash -n` 语法检查。

### 谁联网、谁不联网（别混）

| 动作 | 是否联网 | 谁执行 | 说明 |
|---|---|---|---|
| `git -C /opt/fc27-workbench fetch --prune` | **会联网** | root，单独执行（手动或复用既有定时任务） | 运维动作，**不属于发布入口** |
| `/usr/local/sbin/fc27-publish ...` | **不联网** | 发布入口 | 只读本地 `refs/remotes/origin/main` 的 git 对象；不拉取、不调 GitHub API |

没刷新时新 release 不在本地 main 上，入口直接以 `release_not_on_main` 失败——fail-closed，不会误发旧版本。
检出目录必须 `root:root` 且组外不可写（`chmod -R go-w`），否则任何人改了对象就能影响发布判断。

## 11. 尚未做（都要单独授权，不做默认动作）

| 项 | 状态 | 门槛 |
|---|---|---|
| 宿主安装 `/usr/local/sbin/fc27-publish` + `/etc/fc27-cloud/release-policy.json` | 未做 | 需明确授权；`install.sh` 在 `FC27_INSTALL_AUTHORIZED != 1` 时直接 exit 3 |
| sudoers 仅放行一条命令 | 未做 | 同上，人工 `visudo -c` 校验 |
| 37 个目标的现场 sha256 校准 | 未做 | 需 root 侧跑 `calibrate.py --emit-commands` 后回读；当前 30 个已登记、2 个只有合同文本、4 个被 PR #231 更新 |
| 首次 `--check` 演练（真实宿主） | 未做 | 安装完成、策略校准后，只跑不带 `--apply` 的一次 |
| 首次 `--apply` | 未做 | 需对具体 release 的发布授权（`approval.json`）+ 单独发话 |

