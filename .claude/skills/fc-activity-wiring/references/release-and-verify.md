# 测试、发布与验收

## 本机跑测试

- 本机没有 `npm`，也没有 Playwright 自带的 Chromium，但仓库外有一份 playwright 包。用 `scripts/playwright-shim.index.js.template` 在 scratchpad 建 `shim/node_modules/playwright/index.js`（让 `chromium.launch` 固定用本机 Chrome），运行时设 `NODE_PATH=<scratchpad>/shim/node_modules`。
- node 用 codegraph 自带的 `D:/codex/FC27/tools/colbymchenry-codegraph/1.6.2/codegraph-win32-x64/node.exe`（PATH 上没有 `node`）。
- 命令：`node --test tests/xxx.test.cjs`（`*.test.*`），`node tests/xxx-browser.cjs`（`*-browser.cjs` 脚本不带 `--test`）。后端：`cd backend && PYTHONPATH=. python -m unittest discover -s tests -p "test_*.py"`。
- **改动前就红的用例**（本机环境原因，不是回归）：`catalog-seed.test.mjs`（调 `node`）、`analytics-browser.cjs`、`connection-browser.cjs`、`page-catalog-seasonal-browser.cjs`、`production-browser.cjs`、后端 `test_order_lines`（缺 `lxml`）。遇到红先 `git stash -u` 在基线上跑一遍再下结论。
- 改活动页的选择逻辑后，下面这些会受影响，要一起改并跑：`native-price-refresh.test.cjs`、`fc-published-browser.cjs`、`fc-english-only-browser.cjs`、`native-page59-browser.cjs`、`center-browser.cjs`、`ops-presentation-browser.mjs`、`coupon-login-browser.test.cjs`、`group-add-browser.test.cjs`。
- 改追踪或看板后：`fc-tracking.test.cjs`、`analytics.test.cjs`、`statistics-refresh.test.mjs`、`analytics-server.test.mjs`、`operator-dashboard-browser.cjs`、`coupon-usage.test.mjs`、后端 `test_coupon_usage.py`、`test_discount_revenue.py`。
- CI 偶发失败见过两处：`ops-presentation-browser.mjs` 里管理中心编辑器重载后读 `#language-0`、`fc-tracking.test.cjs` 的 SBC 用例读加购事件。原样 `gh run rerun --failed`，仍然失败再当作真实回归查。

## 发布到 187

187 的 SSH 入口：`E:\WorkBuddy\大超服务器\server_187\access\Invoke-Server187.ps1`（`-Action Run -RemoteCommand …` / `-Action Upload -LocalPaths … -RemotePath …`）。PowerShell 里直接 `&` 调用；不要把含引号的长命令塞进一行，复杂脚本用 base64 传过去再执行。线上 Python 是 3.9（`/opt/python39/bin/python3`），后端代码必须 3.9 兼容。

1. PR 合并后，记下合并提交 SHA；发布内容永远取自合并提交（LF），线上旧文件可能是 CRLF 但内容相同。
2. 生成发布包：`node scripts/make_stage.mjs <scratch目录> <发布号> <合并提交> <requestId> <模块相对路径…>`。脚本会导出文件、补齐发布器要求的依赖（见下）、写出 `stage.sh`。
3. 上传整个发布目录到 `/tmp/rel<发布号>/`，在 187 上运行 `stage.sh`：它建 `/var/tmp/fs-campaign-release<发布号>-candidate`、生成 `release-manifest.json` 并执行 `publish.py inspect`（`mutations:false`）。看清 CHANGED / NEW / same 列表和 `MANIFEST_SHA`。
4. **漂移核对**：用 `scripts/drift_check.mjs list <上一版提交> <文件…>` 生成"上一版仓库内容（去掉 `\r` 后的 sha256 前 16 位）"清单，传到 187 与线上同名文件逐个比（脚本头部有 shell 版比较命令），全部相同才继续；有 DRIFT 先停下问清来源，不覆盖。
5. 应用：`python3 publish.py apply --manifest <manifest> --approved-manifest-sha <MANIFEST_SHA> --release-id nav-<UTC时间>`。它会备份到 `/var/backups/fs-navigation-20261006/nav-<UTC>`、重启 `fs-campaign-dashboard`（以及需要时 `fs-campaign-runtime`）、reload nginx。`EXIT=0` 且三个服务 `active` 才算应用成功；"applied-awaiting-actual-http-role-acceptance" 说明真实入口验收还没做。
6. 发布器的硬性约束（校验会拒绝）：
   - 目标只能是 `target(rel)` 允许的：`app/<…>`（常见静态类型）、`backend/<白名单内的 py>`、几个专用文件。
   - 动 `statistics-refresh.mjs`、`server.mjs`、`discount-revenue.mjs` 必须同时带上 `statistics-retry.mjs`。
   - 动 `production-server.mjs` 且它 import 了 `google-traffic.mjs`，必须同时带 `google-traffic.mjs` 和 `backend/google_traffic.py`。
   - 新文件的 `beforeSha256` 为空是允许的（`make_stage.mjs` 已处理）。
7. 静态清单 `runtime/static-manifest.json` 只更新其中已有的键（110 个）；不在清单里的文件（`analytics/*.mjs`、后端）照常部署，只是不进清单。

## 发布后

- **价格同步窗口**：每次发布后约 1 分钟内，FC 三页公开配置里的现价会缺失，页面显示 `Price unavailable`、整组按钮置灰。**这是价格同步，不是故障**，用户已确认；等同步完成再读回。可以直接拉公开配置 `https://www.mmoexp.com/events/api/campaign/config`，看各页商品的 `price.expires_at` 是否在未来。
- Bash 工具不允许前台 `sleep N`；要等就用浏览器 `wait` 或后台循环。
- 不要在验证里点统计同意、输密码、点真实付款；加购会往测试账号购物车里加东西，收尾时告诉用户。
- 用完自己开的浏览器标签要关掉。

## 交付记录

`DELIVERY.md` 追加一节，格式参照已有条目：`### 日期 \`nav-…\`（PR #…）一句话`，然后依次写来源（PR、合并 SHA、候选目录、manifest 前缀、发布文件）、起因或内容、线上读回（具体数字和页面）、**未验证项**、回退点。只追加，不改旧条目；单独开文档 PR，CI 绿即合并。
