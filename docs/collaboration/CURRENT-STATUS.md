# 仓库配置与运行状态快照

观察时间：2026-10-07 13:50 UTC；观察基线 ee8f36b6861d2f568692a7b333a8efe403e5551a。此文件是事实快照，执行规则只见 [HOTFIX](../ops/HOTFIX.md)，不是授权或准入门槛。

- 仓库private，allow_auto_merge=true。
- main规则24637210实际active：PR、GitHub Actions pr-fast、最新base、0Approve、禁强推/删除，无bypass。
- 已有8个workflow：1个PR自动快测，7个指定输入的手动QA。没有在此次规则整理中新建生产部署器。
- 注册PR快测仅driver-check；专用增量运行37623684963、37630588766均真实失败，修复进行中。不能把静态绿当集成成功、不能因重写规则关闭失败断言。
- 发布、真实角色和线上功能结果按模块的当前现场证据分别记录；此快照不宣布任何模块production_ready。
- 新额度余量未在本次审查读回；保持0美元额外预算，不把旧免费分钟数当当前余额。无人值守SLA通知未配置。

[旧状态全文](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/docs/collaboration/CURRENT-STATUS.md)描述早期323文件、无workflow/规则未知及PR5旧候选；已过期，不得套用到新任务。历史failed/unknown记录继续保留。
