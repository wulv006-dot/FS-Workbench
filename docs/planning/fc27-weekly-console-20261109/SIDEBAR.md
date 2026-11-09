# FC27 周更运营台左侧入口

本轮在现役 FS 全局清单的主站活动区加入 `campaign-weekly`，地址 `/dashboard/analytics/campaigns/analytics/weekly.html`，沿用 dashboard 权限与现有侧栏交互。

可维护差异：`releases/fs-dashboard/campaign-analytics-20261023/navigation/prepare_weekly.py`。输入是服务器当前清单与脚本，不用历史清单覆盖新入口。脚本只加入同一菜单项、更新两个编译脚本内的清单、刷新14个消费者的导航缓存引用，并同步两份现役清单；保持其余脚本和配置字节。冲突身份、脚本清单漂移或缺少引用即停止。4项直接测试通过。

候选在服务器本地生成。只读回菜单、引用数量与 SHA，不导出完整页面或 Nginx 配置。沿已核 SHA 的现役导航发布器 `navigation-experience-20261103-repair-v3/release_ui.py` 检查和发布，保留原双锁、CAS、备份、Nginx 检查、reload与回滚；不重启活动/定价 worker，不改业务数据或定时任务。

2026-11-09候选：`fc27-weekly-nav-20261109-bba30d7296b9`，18文件、1保护项；manifest SHA256 `8cab5733effc7ee59ff0aded6c7f772c0e8f29064d3825e01eedff46e5ed9c66`。原发布器 inspect 已通过 sourceCAS、protectedCAS、retirement；尚未激活。实际部署与真实菜单点击结果另记验收。
