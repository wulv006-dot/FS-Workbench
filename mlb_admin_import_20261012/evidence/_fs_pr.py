# -*- coding: utf-8 -*-
"""创建 PR + 触发 CI + 按需合并（FS-Workbench）。

用法：
  python _fs_pr.py create      # 建 PR
  python _fs_pr.py status      # 查 PR + CI 状态
  python _fs_pr.py merge <sha> # 按精确 head SHA 合并（squash）
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
BRANCH = "wulv/mlb-admin-write-20261012"


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


PR_BODY = """## 本次改动（MLB 方向）

### ① `mlb_admin_import_20261012/` —— MLB 后台直写链路打通（新增）
逆向并实跑验证 **P2PAH 后台建模型 → 上架产品** 双步链路，含完整证据。

**核心结论**
- **两步骤**：`POST /admin/goods.GoodsMould/add`（建模型骨架，产品数=0）
  → `POST .../shelves`（上架产品，MLB26 = 16 × 3 = **48 条/模型**）
- `add` **不返回 mid** → 必须回读 `/index` 按 title 定位
- `shelves` **异步**（须 sleep ≥4s 再回读）；会自动把 `is_put` 置 1
- **MLB 不能用批量导入**：`importPlayers` 硬编码 `E=[833,1327]`，MLB(gid=927) 被拒
- **图片上传在另一个域**：`b2c-api.p2pah.cn`
  - `POST /upload/network?pic_list=<url>`（无鉴权 + 幂等，推荐）
  - `POST /upload/file`（multipart 字段名 `file`，需 md5 签名）
- ★★ **`icon` + `zh_title` 绝不能漏**（球员卡自动改价脚本依赖）
  - `zh_title` = `more.extend=[{"key":"zh_title","value":"<32位hash>"}]`
  - 该 hash **就是卡图 URL 里的 hash**，与 `icon` 同源

**生产脚本** `src/mlb_write_cards.py`
- 五步流水线 + **幂等**（已存在且产品≥48 → 跳过）
- `--dry-run` / `--apply --confirm mlb26-players` 双闸门
- ⛔ **凭据不落库内文件**：`--cred <库外JSON>` 或环境变量
- ⛔ **POST 绝不自动重试**（未知结果转人工）

**实跑结果**：4 张卡生产写入成功，MLB 总数 **270 → 274**，全部产品=48、icon 与 zh_title 齐全。

### ② `docs/planning/mlb-admin-api-feasibility-20261012/`（新增）
逆向结论文档：实跑结论_阻断点 / 新增模型通道 / 建模型与上架产品_双步链路。

### ③ `共享资源/MLB新卡上架/`（2026-10-05 归档补录）
此前 10-05 那轮「执行器检测不到」故障修复的产物，一直未入库，本次一并补齐：
- **四个根因**：SQLite 3.7.17 不支持 UPSERT / 认证换代后被漏（302 非 401）/ bat 是 LF 换行 /
  **BOM + chcp 65001 回归**导致 `setpass`、`'etpass' is not recognized`
- 修法：bat 纯 ASCII 化 + `_normalize_bat.py` 强校验闸门 + `_make_agent_zip.py` 取消吞异常
- 含 `故障修复报告_20261005.md` 与端到端验证脚本

---

## ⚠️ 需注意的点

1. **未部署生产**。本 PR 只是入库；上线须另批指定模块与产物。
2. `共享资源/MLB新卡上架/web/index.html:248` 存在**前端明文 Basic 凭据**
   （`HANDOFF.md:373` 记录的遗留决策点）。经确认**原样入库**；
   该 Basic 体系 **2026-09-30 后已完全失效**，泄露风险有限。
3. `.workbuddy/memory/**` **本批不入库**（含真实密码与 API key）。
4. `共享资源/MLB新卡上架/server/data/*.db*` 为 **SQLite 运行时数据，已排除**。

---

## 验证情况

| 项 | 结果 |
|---|---|
| 幂等 dry-run | ✅ 4 张卡全部识别为"已存在且完整，跳过" |
| 字段验收（vs 参考模型 44234597） | ✅ icon / zh_title / icon_format / products=48 / title / gid·cid |
| 凭据扫描（94 文件） | ✅ 仅 1 处已批准例外 |
| 非 UTF-8 文件 | ✅ 已定位并排除（SQLite 三件套） |
| 线上实跑 | ✅ 4 张卡写入成功，270→274 |

**未验**：`shelves` 在站点侧的全部 15 个站点可见性（仅核了产品数=48）。
"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "create":
        c, j = req("POST", f"/repos/{REPO}/pulls", {
            "title": "feat(mlb): MLB 后台直写链路打通 + 10-05 上架工具归档入库",
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
        c, j = req("GET", f"/repos/{REPO}/pulls?head=wulv006-dot:{BRANCH}&state=all")
        if c != 200 or not j:
            print("未找到 PR:", c, j)
            return
        p = j[0]
        print("PR #%s [%s] %s" % (p["number"], p["state"], p["title"]))
        print("   url:", p["html_url"])
        print("   head:", p["head"]["sha"])
        print("   mergeable_state:", p.get("mergeable_state"), "| merged:", p.get("merged"))
        print()
        # CI
        c2, j2 = req("GET", f"/repos/{REPO}/actions/runs?head_sha={p['head']['sha']}&per_page=20")
        if c2 == 200:
            runs = j2.get("workflow_runs", [])
            if not runs:
                print("   CI: 尚无运行记录")
            for r in runs:
                print("   CI %-28s %-12s %s" % (r["name"], r["status"], r.get("conclusion")))
        else:
            print("   CI 查询失败:", c2, j2)
        return

    if mode == "merge":
        if len(sys.argv) < 3:
            print("用法: merge <精确 head SHA>")
            return
        want = sys.argv[3 - 1] if False else sys.argv[2]
        # 先重读 head 防漂移
        c, j = req("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
        if c != 200:
            print("✗ 取分支失败:", c, j)
            return
        cur = j["object"]["sha"]
        print("分支当前 head:", cur)
        print("要求合并 SHA  :", want)
        if cur != want:
            print("⛔ head 已漂移（%s ≠ %s），拒绝合并。请重新确认。" % (cur, want))
            return
        # 找 PR
        c, j = req("GET", f"/repos/{REPO}/pulls?head=wulv006-dot:{BRANCH}&state=open")
        if c != 200 or not j:
            print("✗ 未找到开放 PR:", c, j)
            return
        num = j[0]["number"]
        ms = j[0].get("mergeable_state")
        print("PR #%s mergeable_state=%s" % (num, ms))
        if ms not in ("clean", "unstable", "has_hooks"):
            print("⛔ mergeable_state=%s，不满足合并条件" % ms)
            return
        # ⛔ 合并必须用 PUT；POST 会 404
        c, j = req("PUT", f"/repos/{REPO}/pulls/{num}/merge", {
            "merge_method": "squash",
            "sha": want,
            "commit_title": "feat(mlb): MLB 后台直写链路打通 + 10-05 上架工具归档入库 (#%d)" % num,
        })
        if c == 200:
            print("✅ 已合并:", j.get("message"), "| sha:", j.get("sha"))
            print("   merged:", j.get("merged"))
            # 合并后 main 的 SHA
            c2, j2 = req("GET", f"/repos/{REPO}/git/ref/heads/main")
            if c2 == 200:
                print("   main 现在 =", j2["object"]["sha"])
        else:
            print("✗ 合并失败:", c, j)
        return

    print("未知模式:", mode)


if __name__ == "__main__":
    main()
