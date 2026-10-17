# 独立报告主题与打印候选

状态：仅本地候选，`releaseReady=false`，未发布。运行目标只有 `/opt/fs-hermes-fc/report.template.html`；来源及活动 before SHA 见 SOURCE-MAP.json。以已核活动模板 `1a576686…14922` 为基线，不覆盖当前 brain/UI/learning 或报告原件。

- 独立离线 HTML 内嵌当前 `ui-system/tokens/fs-tokens.css` 与 `ui-system/adapters/fs-theme.js` 精确快照；两份共享文件仍是唯一维护源，测试验证快照一致。报告旧配色变量映射到统一语义变量，保留原布局、图表、折叠、下载及数据正文。主题控件复用 FSTheme，可选浅色、暗色、跟随系统；存储不可用时仍可操作。
- 打印前记下原本关闭的 details 并展开；重复 beforeprint 不覆盖记录，afterprint 仅恢复这些关闭项。打印使用同一套浅色 tokens，不改用户屏幕主题或图表 tab 选择。
- 不新增参考利润金额图，不生成或补造时间序列，不改模型、投影、原始证据及数据口径。

直接验证：配置既有 Playwright 的 NODE_PATH 后运行 `node tests/theme-print.cjs`。可附加本地已有 boss HTML 路径和截图路径，测试仅复用其 main 正文，不把原文或证据纳入本候选。

本地验证：12 项基础检查及 1 项既有真实日报正文复用检查通过，包含浅暗/系统偏好变化、显式选择优先、主题控件键盘焦点、图表原交互、嵌套折叠重复打印事件恢复、打印浅色、屏幕主题恢复和 390px 合成正文无溢出。旧真实日报的表格存在原有11px横向溢出（390px视口，原模板与本候选scrollWidth均401），本候选未扩大；它属于原排版，不以这次主题候选冒充已修复。截图使用已完成的旧稿，只验呈现，不是新日报/周报业务验收。尚未进行线上发布或人工逐页 PDF 审阅。

实现查阅 [MDN beforeprint](https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeprint_event) 与 [打印媒体指南](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries/Printing)：使用打印 CSS 控制颜色，只对必须展开的内容使用 beforeprint/afterprint。modern-web-guidance 命令因本机无 npx 无法执行，已以官方文档核对；未引入依赖。
