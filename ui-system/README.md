# FS UI 维护入口

本目录是 UI 可编辑源。业务 API、定价、订单、权限、模型与任务调度不属于此目录。

- `tokens/`：浅色/暗色的统一语义变量。
- `components/`：低特异度组件样式。
- `adapters/`：现有 DOM、Shadow DOM、全站导航与主题的兼容桥。
- `modules/native/`：首页、分析壳及样式。本次获明确授权的流量 `google.js` 与营收 `business.js` 为可编辑业务源；其他业务渲染 JS、实时接口和日期规则继续使用经核实的活动版本。
- `modules/brain/brain.css`：Hermes 报告阅读界面样式；不覆盖最新 HTML、业务脚本和后端。
- `publishers/`：只做 UI 范围的薄封装，按 SHA256 引用仓库已有冻结发布器。
- `tests/`：UI/发布合同、依赖闭包、主题和导航回归。

## 校验

在仓库根目录执行：

    python -m unittest discover -s ui-system/tests -v
    node ui-system/tests/syntax.cjs
    node ui-system/tests/theme.cjs
    node ui-system/tests/navigation.cjs

沿用 `tools/pr_fast.py`，没有新建工作流或关闭原检查。

## 构建及发布

`python ui-system/build_release.py --output /tmp/fs-ui-新批次` 生成新的不可变资产版本和精确路由；输出目录必须不存在且在仓库之外。构建包含历史已知 CAS，只可用作候选，下一发布须重新核当前基线，不能直接重放；历史发行目录不能作为日常编辑源。当前已发布资产版本、追加修正和回滚顺序以 `docs/ui/acceptance/20261015.md` 为准。新发布必须刷新本批现场 CAS；不能重放本文历史 manifest。

发布在既有 publisher、锁、备份、CAS 与回滚框架下进行。生产静态目录按已有网站惯例创建为 root 所有、0755，文件 0644；调用发布命令前仅在该命令进程中使用 `umask 022`。暂存包和备份保持私有。不要用暂存目录的 077 umask 创建公开静态目录。

薄封装的独立运行包须在 `native/release_navigation_base.py` 放入原仓库 `releases/fs-dashboard/menu-cache-20261015/native/release_navigation.py` 的精确字节；SHA256 必须是 `5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357`。它只用于复用原发布能力，不另行复制入 Git；在正常仓库内直接引用原路径。

## 安全边界

不在生产点击采集、改价、开关、保存参数、任务派发或付费模型生成来验证外观。不得因 UI 主题修改主动 OFF、定价参数、来源口径或授权。未知、部分、过期保持真实显示。

MLB 的旧固定凭据和日更任务的旧失败属于独立问题，UI 发布不能代替其整改与验收。

## 模块兼容边界
共享导航默认可用于旧工具，但正文全局令牌桥仅加载到已核验 dashboard 与 FC Players/Gallery 页面。D4/G2G 等旧工具须建立逐页兼容样式后再加入，禁止以一条全局深色规则覆盖硬编码白底。追加发布目录保留完整 CAS 清单；对应可编辑源在 adapters 与 modules。


## 2026-10-17 流量与决策增量

本次用户明确授权流量口径、接口、界面及报告改造，`modules/native/google.js`成为流量业务可编辑源；它复用现有只读接口与统一组件，原不可变业务资产保留历史。本次同时授权 `modules/native/business.js` 接入独立ES结构并修复主盘字段级Admin优先、Order补缺（含有效0）；其他业务JS仍固定到已核验版本。shell/index/home基于活动ba0a版本接入本次新流量模块，不能从10月15日旧壳回退。新数据合同和共享规则须先发布，再切新前端；验收与精确来源见`releases/fs-dashboard/traffic-hermes-20261017/README.md`，候选不等于已发布。本批仅准备流量与营收所需的5个不可变资产（business.js、google.js、shell.js、index.html、home.html）及2个可变目标（活动formal.conf、fs-home/index.html）；保留旧URL与现有共享CSS，不运行全站UI构建结果覆盖其他模块。

## 2026-10-17 ES订单结构增量

`modules/native/business.js`基于业务刷新活动维护源（SHA256 ec074d393b3fb38446f2eca03bbc0f7ac81f7511fcb1c67db694a553842a4d66）转接为本任务可编辑源；独立FC27 ES结构不覆盖Admin主卡，也不改变现有明细筛选。Google广告组仅作展开细分，不叠加系列/账号总额。其他业务依赖仍固定原活动资产。新前端需在结构路由和广告组合同就绪后发布，历史release不改。最小发布准备入口为 `releases/fs-dashboard/traffic-hermes-20261017/prepare_ui.py`；复用既有受限发布器及锁、CAS、备份、账本与回退，不以完整UI构建输出替代本批5资产/2目标。

## 2026-11-03 导航体验改造
当前导航增强可编辑源与构建入口见 modules/navigation-experience/README.md。此目录以本次核实的静态nav.js和动态hubnav.js为输入，统一收纳、搜索、紧凑侧栏与原生切换；旧adapters基线保留历史职责，不能覆盖本批活动版本。真实入口检查、已知服务故障与逆序回滚见该文档。

