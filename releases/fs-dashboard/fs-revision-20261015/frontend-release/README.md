# 最终隔离前端发布候选

状态：仅本地候选，`releaseReady=false`，没有生产写入、Git 写入或服务停启。现网基线由 `live-baseline.json` 逐文件读取，版本是 `workspace-native-20261006-5d085f7c1aac`；原工程 release 的旧 a0f manifest 不作为现场基线。

最终 releaseId：`workspace-native-20261006-261bedcc395a`。

| 对象 | SHA-256 |
| --- | --- |
| release-contract.json / release-manifest.json | 1e789b3bdbc8fa60db9e8c02880f7268b79712e7bae42c3a08ed5c0d9115a626 |
| release_workspace.py | 31aafa101b8c5e07bb512bd178a487a10fc825d459d16767688ef3a0a461f64b |
| candidate/formal.conf | d9c6ce2d75d5220ff11f975a6248b4aa4f9fc264c70fa4e3f72edcc852224a41 |
| candidate/fs-home/navigation.js | ce0fc0a453ecae955bb8e7e2ae9ff6619de81c09691822935e5b9a3edc2c2aa1 |

139 immutable assets 和原 4 mutable 集合均复用原 `fs_boss_workspaces_20261013/release/release_workspace.py` 合同与发布机制。publisher 只有 CONTRACT_SHA 改动，发布逻辑、NAMES 和保护不放宽。149 个保护对象、经营 HTML 账本及真实其他资产保留；`source-runtime-map.json`、`build-summary.json` 给出完整来源与目标映射。

原始素材相对现场只有 3 个资产漂移（business.js/home.html/index.html），已按现场 SHA 选择对应原字节来源；新候选修改 7 个业务/导航资产，home.html 另仅重绑定新 releaseId 的资产 URL。与现场逐 SHA 比较实际 8 个 immutable 字节变化，其余 131 个保持原字节；两种变更集合均明确列在 build-summary/source-runtime-map。最终接线把 FC 日报入口改成 `/dashboard/fs-home/brain/index.html?report_kind=daily#reports`，管理页 FC 运营报告入口也用同一路径。旧事实日报导出和已保存历史归档保留。

17 个经营 HTML 和 1 个游戏 HTML 的普通 URL / immutable alias 共 36 个 location 注入同一 `/__hub/hubnav.js?v=fs-revision-20261015`。组件成功创建时隐藏旧全局 `.fs-nav/.fs-links`；页内总览、沙盘、日期筛选与游戏筛选功能保留。

4 个旧报告 HTML 入口退役到 `/dashboard/fs-home/brain/index.html?report_kind=weekly#reports`：weekly/index.html、weekly/legacy-index.html、新版本 advisor.html、weekly-legacy.html。weekly/ 原内部 rewrite 仍进入受保护的 index.html。现场 active Google current 只有 index.html；新增 exact `/dashboard/marketing/`、`/dashboard/marketing/index.html` 接新 `/dashboard/analytics/?mode=google`，覆盖原受保护静态 prefix。原 `/dashboard/marketing` 继续先跳至 trailing slash。

退役入口保留认证子请求，认证后以 `try_files ""` 转到 named location 再返回 302，避免普通 rewrite-phase `return` 提前结束请求。named location 是内部跳转目标；机制参照 [Nginx try_files 官方说明](https://nginx.org/en/docs/http/ngx_http_core_module.html#try_files)及[官方模块源码](https://github.com/nginx/nginx/blob/master/src/http/modules/ngx_http_try_files_module.c)。API/JS/JSON、native business/google HTML 片段、`/dashboard/index.html` 和 FC 入口保持。`verify.py` 对完整 location 块与原现场配置的比较确认仅 36 个导航 HTML、4 个旧报告 HTML 改动，新增 2 个 Google exact 与 2 个 named location。

验证：

- `verify.py`：139+4 文件存在/SHA、149 保护、精确合同、publisher 逻辑、导航同字节、36 注入、6 退役 HTML 与其它路由字节保护通过。
- `browser-combined.cjs`：143 项通过，页面异常 0，POST 0，强制 FC 刷新 1。覆盖 native、brain、全部 17 经营 HTML、游戏、两个 immutable HTML alias、1440/390px 页面无水平溢出、手机侧栏开关、FC modal top layer、游戏桌面/手机弹窗高于侧栏。Order 利润率故意设置等于 DY 目标值，实际卡保留全站参考值，达成仍显示「未评估」。
- `test_native_release.py`：Windows 3 pass + 4 Linux 明确 skip。Linux 文件操作/CAS/回滚测试直接运行原 publisher，用临时 root 和合成 before/protected 字节；系统服务调用替身，不执行真实 systemctl。该测试只依赖相邻 stage，可放入私库 `releases/fs-dashboard/fs-revision-20261015/frontend-release/` 原样运行，没有 E: 依赖。Linux、真实 Nginx 角色、生产 readback 尚未在此声称通过。

浏览器全部请求由本地路由替身处理。经营/FC 金额为合成测试；游戏数据是已读取公开情报历史成功版本；不构成生产业务或自然周期验收。截图在 `browser-evidence/`，含四页原图、游戏弹窗、FC 抽屉及手机导航。

原 E 工程根运行：`python docs/planning/fs-revision-20261015/analytics/prepare_candidate.py`，然后 `python docs/planning/fs-revision-20261015/frontend-release/build.py`、`python docs/planning/fs-revision-20261015/frontend-release/verify.py`。原 artifact 可在任意相同目录结构下运行 `python frontend-release/test_native_release.py`；浏览器本机重跑 `node docs/planning/fs-revision-20261015/frontend-release/browser-combined.cjs`。

主线先部署 backend/AI 时会改变本候选保护的活动 SHA。实际发布前必须由主线读取新现场、重新冻结并审核保护与合同；不能直接把这份历史基线 manifest 的 releaseReady 改 true。同一 navigation.js 两个串行 publisher 必须复用候选原字节，后者 beforeSha 使用前者实际发布值。没有在本任务改根 HANDOFF。
