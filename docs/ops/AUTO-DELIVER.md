# 自动交付指令 v5（WorkBuddy 项目指令 + 一键交付工具）

更新：2026-10-12 ｜ 取代 `项目指令 v4 / v4-lite` 中「开工全量对账 + 逐项人工确认 + 合并需逐个 owner 批准」的做法。
与全仓唯一执行规则 [`HOTFIX.md`](HOTFIX.md) 一致：**已授权范围内连续推进，不在每步再询问、不要求双方逐个相互 Approve。**

## 1. 唯一工作方式

```
提需求 → git fetch 对齐 main → 改（改前备份+md5） → 推分支 → 开 PR
      → 等 pr-fast 绿 → 自动 merge → 部署 47.85.224.112 → 读回验证 → 一次性报告
```

用户在对话里提出的需求 = 完整授权。中途不打断、不要求人工确认、不要求去网页点 PR。

## 2. 事实源（单真源 + 部署目标）

- **源码唯一真源 = 仓库 `main` + 本机工作副本**。
- **线上（47.85.224.112）只当部署目标**：与仓库不一致时**不再停工问人**，直接备份后以本地最新版覆盖。
- **取消**「仓库 ↔ 线上逐文件 sha256 全量对账」；开工只做 `git fetch origin` 并对齐最新 `origin/main`。

## 3. GitHub 规则（2026-10-12 实测，据此自动化）

| 项 | 实测结果 |
|---|---|
| `main` 规则集 | `main-pr-fast`（`enforcement=active`） |
| 规则内容 | 禁删除、禁 non-fast-forward、**必须走 PR**、**人工审批数 0**、必须 `pr-fast` 检查通过且 base 最新 |
| 陈超权限 | `push`（`admin=false`）→ 能开 PR，**也能自动合并自己的 PR** |
| 结论 | **直推 `main` 会被拒** → 一律走 PR；PR 0 审批 ⇒ **全流程可脚本化，无需人工点** |
| CI | `.github/workflows/pr-fast.yml` → `tools/pr_fast.py`（改动路径离线隔离检查，10 分钟超时；未映射代码显式失败） |

`pr-fast` 红了：读日志修；修不好保留分支**如实报失败**，不绕闸、不关 CI、不新增 workflow。

## 4. 一键交付工具

`fs_deliver.py`（stdlib-only，凭据运行时从 git credential manager 读取，**不打印、不落盘**）。
默认参数从同目录 `fs_deliver.config.json` 读，因此命令行全 ASCII、可安全在 Git Bash 调用。

```bash
python fs_deliver.py --slug d4-gold-history \
  --paths opt/d4follow/app.py,opt/d4follow/templates/index.html \
  --message "feat(d4follow): 金币货架历史"

# 预演（不动任何东西）
python fs_deliver.py --slug x --paths a/b.py --message "fix: y" --dry-run

# 连部署一起（备份 → 上传 → md5 读回 → 重启服务）
python fs_deliver.py --slug x --paths opt/d4follow/app.py --message "fix: y" \
  --deploy opt/d4follow/app.py=/opt/d4follow/app.py --restart d4follow
```

脚本动作：`fetch` → 从 `origin/main` 建 `chenchao/<slug>-<日期>` → **逐项 stage**（不接受 `git add .`）→ commit → push →
开 PR（已存在则复用）→ 轮询 `pr-fast` → 绿则 **自动 merge**；base 落后自动 `merge origin/main`（**永远不用 force push**）重跑。
退出码：`0` 成功 ｜ `1` 错误 ｜ `2` 需要人看一眼（CI 红 / 等超时 / 合并未完成）。

## 5. 唯一保留的 3 个人工闸门

1. **共享文件**：`etc/nginx/`、`var/www/` 下的**登录 / 首页 / 导航**（吴律主导）→ 覆盖前问一句。
2. **吴律的模块**：FC / NBA / MLB 源码 → 不动。
3. **红线动作**：force push（含 force-with-lease）· reset 远端 `main` · 重写公共历史 · 旧包覆盖线上 ·
   直接从 E 工程 push · 新持久凭据（token / OAuth / SSH key / 新生产账号）· 生产权限扩展 ·
   **定价策略变更** · 不可恢复删除 · 输出秘密值。

## 6. 不许省的最小纪律

- 改前备份**单独一条命令** + `md5sum` 核对 + 明确回滚点；有副作用的操作别串进长 `&&` 链。
- **逐项 stage**，禁 `git add .` / `git add -A` / 整目录上传。
- 部署后**读回验证**：文件 SHA + 服务健康 + 业务数据；`unknown` / 部分成功 → 暂停写入、保留证据与旧 ID，**不换 ID 重试、不用旧包盖回**。
- 改完 `templates/index.html` 必须 `systemctl restart d4follow`（Jinja 模板缓存）。
- 见旧 IP 先判性质：带 `http://` 的 URL 或 `host` / `public_url` 字段 = **活配置必须新机**；叙述文字里的裸 IP = 历史记录，保留不改。
- 敏感物只记位置与类别，**不输出值、不上传、不测有效性**。
- 截图 / HTTP 200 / merge 成功都不是终点：终点是**从真实入口确认业务结果恢复**。

## 7. 分工

- **吴律**（`wulv006-dot`，admin/push）= FC / NBA / MLB + 共享登录、首页、导航。
- **陈超**（`dachao1997`，write）= **D4 / PoE2 / Aion2**（⚠️ PoE2 不在目录名里，仍属陈超，不得遗漏）。
- 其余「待指派」，不猜。`write` 是仓库级能力，路径分工是政策不是技术 ACL。
