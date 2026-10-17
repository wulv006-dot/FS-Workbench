# -*- coding: utf-8 -*-
"""创建 PR + 查状态 + 按精确 head SHA 合并（FS-Workbench）。

用法：
  python _fs_pr.py create      # 建 PR
  python _fs_pr.py status      # 查 PR + CI 状态
  python _fs_pr.py merge <sha> # 按精确 head SHA 合并（squash）

⚠️ 两个必须记住的接口坑
  1. 合并只能 `PUT /pulls/{n}/merge`；`POST` 返回 **404**（迷惑行为，不是权限问题）
  2. `GET /pulls?head=...` **列表接口不返回 `mergeable_state`（恒 null）** ⇒
     用它判闸门会误判「不满足合并条件」。必须再打一次 `GET /pulls/{n}`。
     （`mergeable` 是 GitHub 异步算的，首次常为 None，需轮询几次）
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "wulv006-dot/FS-Workbench"
API = "https://api.github.com"
BRANCH = "wulv/mlb-card-count-copy-20261012"
OWNER = REPO.split("/")[0]


def token() -> str:
    p = Path.home() / ".workbuddy" / "mcp.json"
    d = json.loads(p.read_text("utf-8"))
    return d["mcpServers"]["github-fs"]["headers"]["Authorization"].replace("Bearer ", "").strip()


TOK = token()


def req(method, path, body=None, retries=4):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {
        "Authorization": "Bearer " + TOK,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "fs-workbench-push",
        "Connection": "close",
    }
    if data:
        h["Content-Type"] = "application/json"
    last = None
    for a in range(retries):
        r = urllib.request.Request(url, data=data, headers=h, method=method)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with op.open(r, timeout=60) as resp:
                b = resp.read()
                return resp.status, json.loads(b.decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                j = json.loads(b.decode("utf-8"))
            except Exception:
                j = {"_raw": b[:500].decode("utf-8", "replace")}
            if e.code < 500 and e.code != 429:
                return e.code, j
            last = (e.code, j)
        except Exception as e:
            last = (0, {"_err": repr(e)})
        time.sleep(1.5 * (a + 1))
    return last


def pr_state(num, tries=6):
    """取单个 PR（唯一能拿到 mergeable_state 的路径）。"""
    for _ in range(tries):
        c, j = req("GET", "/repos/%s/pulls/%d" % (REPO, num))
        if c == 200 and j.get("mergeable") is not None:
            return j
        time.sleep(2)
    return j if c == 200 else {}


def find_pr():
    c, j = req("GET", "/repos/%s/pulls?head=%s:%s&state=open"
               % (REPO, OWNER, BRANCH))
    if c != 200 or not isinstance(j, list) or not j:
        return None
    return j[0]


TITLE = "feat(mlb): 写后台前加人工确认闸门 + 当期金币售价自动取价"

PR_BODY = """## 本次改动（MLB 方向，承接 #72）

老板两条要求，这一批全部落地：

> ① 「这个页面做完采集，在正式写入后台的时候，应该有一步是让人工确认上架的卡片步骤。
>    人工核对无误后才可点击放行，进行写入动作」
> ② 「当期金币售价这里也应该可以自动拉取后台的 MLB Stub 的实时单价。不需要人工手动填写」

---

### ① 写前人工确认闸门

**改前**：`/result` 一进来就 fire & forget 起写卡线程 —— 人在网页上看到的永远是「已经写完了」。
**改后**：回传后**只冻结快照，不写**；人逐条核对 → 勾选 → 点「确认放行」才写。

四条设计要点（都不是可选项）：

1. **冻结快照，不读 DB 里的 cards**
   `tasks.result.cards` 会被后续 `/result` 覆盖（任务重跑 / 执行器补传）。
   若人核对的是 A 而写的是 B，这道闸门就是假的。
   ⇒ 待写卡片整份落到 `<workdir>/<tid>.pending.json`（附 `sha256`），**放行只从快照取卡**；
     新结果**整份替换**快照 ⇒ 旧的人工确认自动失效。
2. **只写勾选的**：放行名单里出现快照外的 `product_name` ⇒ 拒绝（防 UI 过期 / 人为构造）。
3. **一次性的 `awaiting_review → running`**
   hub 是 `ThreadingHTTPServer`，双击「放行」会起两个写卡进程 → 建重复模型。
   `APPROVE_LOCK` 把「读状态 → 判状态 → 落盘 → 起线程」做成原子；第二次拿 `noop`。
4. **审计留痕**：`approved_by` / `approved_at` / `approved_cards`(计数) /
   `approved_names`(名单) / `sha256`。
   ⚠️ 计数与名单**都要**：只有计数回答不了「到底放行了哪几张」；只有 `sha256` 得把快照翻出来重算。
   留痕经 `run_once(extra=...)` 以 `setdefault` 合并 —— **只做补充，绝不覆盖运行结论**。

另外：
- `require_approval` 缺省 **true**（配置写漏了就往「停下来等人」的方向倒）
- `cancel` 只在 `awaiting_review` 允许。跑动中不给取消：kill 掉写卡子进程会留下
  「未知结果」的卡，比不写更危险
- 开机清扫把「待审但快照丢了」扫成 `review_lost`（不许猜、不许默认放行）

---

### ② 当期金币售价自动取价

来源（老板指定）：**订单后台** `order.p2pah.cn` → 游戏&产品 → 金币价格管理 →
所属游戏 **922**（MLB The Show 26）→ 该行 **`b2c`**。
`b2c` 口径 **USD/1K**，工作台 `rate` 口径 **USD/100K** ⇒ `rate = b2c × 100`。

⚠️ 这是**订单后台**，与商品后台 `admin-api.p2pah.cn`（GID 927 / CID 8233）
**是两套系统，GID 不通用**。

- `src/p2pah_price.py`：**纯标准库**（服务器 `/opt/python39` 没有 `requests`/`urllib3`），
  `ddddocr` 只在函数内惰性 import
- `server/mlb_coins_rate.py`：子进程桥接；**失败负缓存 60s**
  （取价每次都要登录订单后台过验证码，失败就立刻重试 = 每小时 720 次登录 → 有锁号风险）
- `GET /api/coins-rate`；前端预填 + 手动「重新取价」，人改过就不再覆盖；取不到退回人工填
- 取价**绝不影响**建任务 / 领任务 / 采集回传 / 上架

**逆向踩到的三个坑**（已写进代码注释）：
1. 菜单路径是「站点根相对」（页面里 `WEB_ROOT = "/"`）：加 `/admin/` 前缀一律 **404**
2. 筛选参数必须是 `?gid=922`；写成 `?gid[]=922` 会被路由打成 **500**
3. 价格表里 `c2c` / `g2g.com` / `eldorado.gg` 三列被 `<!-- -->` 注释掉，
   **必须先剥 HTML 注释再解析**，否则 7 列变 11 列、列序整体错位

---

## 验证情况

门禁按 **CI 同版本 Python 3.9.25** 复现，基线 `main = 7ae57b83`。

| 项 | 结果 |
|---|---|
| `tools/pr_fast.py` | `{"result": "PASS", "affected_groups": ["mlb-admin", "mlb-shelf-tool"]}` |
| 离线 `mlb-admin` 组 | `testsRun=45 / 0 fail / 0 error / 0 skip`（`-I -B` 隔离 + `Popen` 桩） |
| 离线 `mlb-shelf-tool` 组 | `testsRun=102 / 0 fail / 0 error / 0 skip` |
| `verify_writeback_e2e.py`（真起 hub / 真发 HTTP / 真等子进程） | **56/56** |
| `frontend_structure(index.html)` | OK，41,450 B |

端到端里**刻意验的几条**（这才是"闸门是真的"的硬证据）：
- 回传后等 4 秒，`<tid>.writeback.json` **不存在** ⇒ 放行前确实没写；
- 放行名单里塞快照外的卡 → `noop` + 精确原因，磁盘仍无产物；
- 只勾 1 张 → 报告里就只能有 1 张；
- 连点两次「放行」→ 第二次 `noop`，报告仍是 1 张；
- **关掉闸门 → 回到旧的自动行为**（加闸门不能把老路径弄坏）。

---

## ⚠️ 需注意的点

1. **未部署生产**。本 PR 只是入库；按纪律「**合并 ≠ 部署**」，上线须另批指定模块与 commit/产物。
2. `.workbuddy/memory/**` **本批不入库**（含真实密码与 API key）。
3. `共享资源/MLB新卡上架/server/data/**` 为 **SQLite 运行时数据，整目录排除**。
4. `共享资源/MLB新卡上架/web/index.html` 保留 2026-10-05 记录在案的前端 Basic 凭据
   （已于 2026-09-30 后失效），本次为**原样保留**、未新增任何凭据。
5. 订单后台凭据文件 `_cred_order.json` **只存在于服务器**，本 PR 不含任何凭据内容。
"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "create":
        c, j = req("POST", "/repos/%s/pulls" % REPO, {
            "title": TITLE,
            "head": BRANCH,
            "base": "main",
            "body": PR_BODY,
            "draft": False,
        })
        if c in (200, 201):
            print("✅ PR #%s 已创建" % j["number"])
            print("   ", j["html_url"])
            print("   head:", j["head"]["sha"])
            print("   base:", j["base"]["ref"], "=", j["base"]["sha"])
        else:
            print("✗ 创建失败:", c, j)
        return

    if mode == "status":
        p0 = find_pr()
        if not p0:
            print("未找到开放 PR")
            return
        num = p0["number"]
        p = pr_state(num)
        print("PR #%s [%s] %s" % (num, p["state"], p["title"]))
        print("   url:", p["html_url"])
        print("   head:", p["head"]["sha"])
        print("   mergeable =", p.get("mergeable"),
              "| mergeable_state =", p.get("mergeable_state"),
              "| merged:", p.get("merged"))
        print("   changed_files =", p.get("changed_files"),
              "| commits =", p.get("commits"))
        # CI 结论走 /actions/runs（check-runs 需要 checks:read，PAT 没有 → 403）
        head = p["head"]["sha"]
        c2, j2 = req("GET", "/repos/%s/actions/runs?head_sha=%s&per_page=20"
                     % (REPO, head))
        if c2 == 200:
            runs = j2.get("workflow_runs", [])
            if not runs:
                print("   CI: 尚无运行记录（可能还在排队）")
            for r in runs:
                print("   CI %-28s %-12s %s" % (r["name"], r["status"],
                                                r.get("conclusion")))
        else:
            print("   CI 查询失败:", c2, j2)
        return

    if mode == "merge":
        if len(sys.argv) < 3:
            print("用法: merge <精确 head SHA>")
            return
        want = sys.argv[2]
        c, j = req("GET", "/repos/%s/git/ref/heads/%s" % (REPO, BRANCH))
        if c != 200:
            print("✗ 取分支失败:", c, j)
            return
        cur = j["object"]["sha"]
        print("分支当前 head:", cur)
        print("要求合并 SHA :", want)
        if cur != want:
            print("⛔ head 已漂移（%s ≠ %s），拒绝合并。请重新确认。" % (cur, want))
            return
        p0 = find_pr()
        if not p0:
            print("✗ 未找到开放 PR")
            return
        num = p0["number"]
        # ⚠️ 必须用单 PR 接口；列表接口的 mergeable_state 恒 null
        p = pr_state(num)
        ms = p.get("mergeable_state")
        print("PR #%s mergeable=%s mergeable_state=%s" % (num, p.get("mergeable"), ms))
        if ms not in ("clean", "unstable", "has_hooks"):
            print("⛔ mergeable_state=%s，不满足合并条件（只收 clean/unstable/has_hooks）" % ms)
            return
        print("   head 复核 =", p["head"]["sha"])
        if p["head"]["sha"] != want:
            print("⛔ PR head 与要求 SHA 不一致，拒绝合并")
            return
        # ⛔ 合并必须用 PUT；POST 会 404
        c, j = req("PUT", "/repos/%s/pulls/%d/merge" % (REPO, num), {
            "merge_method": "squash",
            "sha": want,
            "commit_title": "%s (#%d)" % (TITLE, num),
        })
        if c == 200:
            print("✅ 已合并:", j.get("message"), "| sha:", j.get("sha"))
            print("   merged:", j.get("merged"))
            c2, j2 = req("GET", "/repos/%s/git/ref/heads/main" % REPO)
            if c2 == 200:
                print("   main 现在 =", j2["object"]["sha"])
        else:
            print("✗ 合并失败:", c, j)
        return

    print("未知模式:", mode)


if __name__ == "__main__":
    main()
