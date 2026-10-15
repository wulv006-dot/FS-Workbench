# FS UI 维护入口

本目录是 UI 可编辑源。业务 API、定价、订单、权限、模型与任务调度不属于此目录。

- `tokens/`：浅色/暗色的统一语义变量。
- `components/`：低特异度组件样式。
- `adapters/`：现有 DOM、Shadow DOM、全站导航与主题的兼容桥。
- `modules/native/`：首页、分析壳及样式。业务渲染 JS、实时接口和日期规则继续使用经核实的旧不可变版本，不能擅自换掉。
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

`build_release.py` 生成新的不可变资产版本和精确路由；历史发行目录不能作为日常编辑源。当前已发布资产版本、追加修正和回滚顺序以 `docs/ui/acceptance/20261015.md` 为准。新发布必须刷新本批现场 CAS；不能重放本文历史 manifest。

发布在既有 publisher、锁、备份、CAS 与回滚框架下进行。生产静态目录按已有网站惯例创建为 root 所有、0755，文件 0644；调用发布命令前仅在该命令进程中使用 `umask 022`。暂存包和备份保持私有。不要用暂存目录的 077 umask 创建公开静态目录。

薄封装的独立运行包须在 `native/release_navigation_base.py` 放入原仓库 `releases/fs-dashboard/menu-cache-20261015/native/release_navigation.py` 的精确字节；SHA256 必须是 `5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357`。它只用于复用原发布能力，不另行复制入 Git；在正常仓库内直接引用原路径。

## 安全边界

不在生产点击采集、改价、开关、保存参数、任务派发或付费模型生成来验证外观。不得因 UI 主题修改主动 OFF、定价参数、来源口径或授权。未知、部分、过期保持真实显示。

MLB 的旧固定凭据和日更任务的旧失败属于独立问题，UI 发布不能代替其整改与验收。
