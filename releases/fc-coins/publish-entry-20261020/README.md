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
| 宿主仓库检出（root 所有，只有 root 能 fetch） | `/opt/fc27-workbench` |
| 主分支引用 | `refs/remotes/origin/main` |
| 状态根（既有） | `/var/lib/fc27-cloud` |
| 本次备份（唯一新建目录） | `/var/lib/fc27-cloud/rollback/<UTCSTAMP>-<module>/` |
| 发布收据（唯一新建文件） | `/var/lib/fc27-cloud/releases/<UTCSTAMP>-<module>.json` |
| 既有写锁（**只按原协议** flock，不改写、不清空） | `/var/lib/fc27-cloud/state/price-writer.lock` |
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

1. 策略可读、`version == 1`、模块名/目标名/根前缀/单元动词都合法。
2. 发布名合法；`<release_prefix><release>/approval.json` **存在于 origin/main**。
3. `approval.merge_commit` 是 40 hex、**是 origin/main 的祖先**、其 subject 含 `(#<pr>)`（squash 绑定）。
4. `approval.pr == pr`，`authorized_by`/`authorized_at` 非空，`approval.scope` 与 manifest 的 targets **集合相等**。
5. manifest 取自 **该 merge commit**（不是工作区）；每个 `before`/`after` 是合法 sha256。
6. 每个候选字节 = `git cat-file blob <commit>:<base>/source/<name>`，其 sha256 必须等于 `after`。
7. 每个目标：在策略里、路径与策略逐字符一致、不是 symlink、`realpath` 一致、现场 sha256 必须等于 `before`（否则 `baseline_drift`）。
8. 空闲与锁：`queue/` 无文件；`jobs/` 无 queued/running、无"auto_cycle 已 confirmed 但未 completed_at"；`executions/` 无 RUNNING/UNCERTAIN/PARTIAL；对既有 `price-writer.lock` 取 `LOCK_EX|LOCK_NB`。
9. 单元：策略授予 `is-active`，三个单元必须全部 active。

**什么算"已有发布授权"**：两层同时成立 —— 宿主策略文件声明该模块可发布（root 维护），
且本次 release 目录里的 `approval.json`（经 PR 合并进 main）写明 `pr`、`merge_commit`、
`authorized_by`、`authorized_at`、`scope`，`scope` 与文件清单完全一致。缺一层都不发布。
PR 合并本身不构成生产授权。

## 5. 允许动作（穷举）

| 对象 | 动作 | 范围 |
|---|---|---|
| 白名单文件 | 原子替换（临时文件 `.<name>.publish-tmp` → fsync → `os.replace` → fsync 目录），保留 mode/uid/gid | 仅 `targets` 内的 37 个路径 |
| systemd | `is-active`、`stop`、`restart` | 仅 `fc27-cloud-api`、`fc27-cloud-worker`、`fc27-automation-tick.timer` |
| 单元选择 | 由目标推导：`automation_tick.py` → timer + worker；`fc27_cloud_api.py` → api；其他 .py → worker；`.sh`/`/opt/fc27-collector/*`/静态文件 → 不重启 | 同一单元只停/启一次 |
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
| 停单元后未写入 | 重新拉起单元 | `rolled_back`（`nothing_written`） | 6 |
| 写入/重启/读回失败 | 停单元 → 用备份换回 → 重启 → 逐个核对 `before` | `rolled_back` | 6 |
| 文件字节无法恢复到 `before` | 停止重试，保留现场 | `unknown_write_state` | 7 |

收据始终落盘（成功或失败都写），另有 `journald`。失败后**不自动重试**，未知写入视为未知，不盲重放。
备份目录保留，人工确认后再清理。

## 7. 安装（宿主，root，一次性）

```
sudo bash releases/fc-coins/publish-entry-20261020/install.sh     # FC27_PUBLISH_GROUP=fc27ops 可覆盖
```

脚本只做五件事：校验源码可解析并打印 sha256 → `install -m 0755` 到 `/usr/local/sbin/fc27-publish` →
**策略存在则不覆盖** → 检查 `/etc/fc27-cloud/monitor-user` 是否存在（不打印内容）→ 打印 sudoers 片段。
不启停单元、不碰 `/opt` 源码、不写 `/var/lib/fc27-cloud`。最后用"无参数应返回 2"自检。

sudoers 只放行一条命令，人工写入并 `visudo -c`：

```
Cmnd_Alias FC27_PUBLISH = /usr/local/sbin/fc27-publish
%fc27ops ALL=(root) NOPASSWD: FC27_PUBLISH
```

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

## 9. 离线测试

```
cd releases/fc-coins/publish-entry-20261020 && python3 -m unittest discover -s tests -t tests
```

57 条用例，覆盖：策略/白名单越界、目标名/发布名路径穿越、PR 与 merge commit 绑定、
scope 不一致、候选字节与 commit 不符、现场基线漂移、symlink、队列/作业/执行未结、
锁占用、单元 inactive、单元动词越权、成功发布（备份+收据+原子替换+停启顺序+去重）、
重启失败回退、读回不符回退、保护文件漂移回退、健康超时回退、回退失败→unknown、调用端预检与不写入。

测试全部注入假 git/systemd/monitor，**不连网、不起进程、不碰真实 `/opt`**；`install.sh` 另有 `bash -n` 语法检查。

## 10. 尚未做（需用户确认后才谈）

- 宿主安装 `/usr/local/sbin/fc27-publish` 与 `/etc/fc27-cloud/release-policy.json`；
- sudoers 只放行那一条命令；
- 策略里 37 个目标需与宿主回读的现场一致（当前 30 个已登记、2 个只有合同文本、
  4 个被 PR #231 更新、其余待宿主 sha256 回读后校准）。
