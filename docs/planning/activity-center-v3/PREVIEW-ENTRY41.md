# FS 活动预览入口修复

2026-10-26。范围仅活动入口映射，不修改报表/查询/配置/交易。

本机Chrome现有products标签沿左栏“活动转化分析”进入原analytics页面。页面右上“体验活动页”实际href为父目录 `/dashboard/analytics/campaigns/`，默认FC首页；与所选活动无关联。products四页选择原本没有整页体验链接。已查看真实当前界面像素，不依赖附件推断。未保存/上传/发布任何配置。

修复：原分析页体验链接进入唯一products编辑器的page-preview位置；编辑器根据当前page_id选择严格四页路径，复用现有受控publicPrefix。未知页不提供链接，不回退FC。链接明确打开已发布版本，不保存草稿、不通过URL泄漏未保存配置。Seasonal使用其已发布主题，默认Halloween由既有页面处理；不把未发布主题参数冒充正式配置。

运行范围：app/analytics/index.html（仅一个入口链接）、products.html（预览入口及说明）、products.js（四页映射及切换刷新）。不新增编辑器/跳转兼容层，dashboard.js/css、分析查询与数据口径不改。

验证：preview-entry-browser.cjs 使用原production-server与合成管理员身份，从原分析入口实际点击进入products，依次点击四个页面及FC/Seasonal往返，断言URL、无POST、草稿文件字节不变。公开目的页由只读fixture响应，此测试不代表线上新版本已部署或真实业务验收。已登记既有pr-fast，无新增workflow。首次测试因空临时目录未显式生成state夹具失败，已补合成初始草稿后通过。

发布仍需逐次批准，不能复用RELEASE39。批准后需核当前线上CAS/并发保护并沿真实导航复验四页；不用直链可达替代入口验收。本轮不部署。
