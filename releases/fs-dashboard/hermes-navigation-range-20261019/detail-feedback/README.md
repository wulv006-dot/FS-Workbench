# 客单详情点击反馈 · 2026-10-19

已部署并独立读回，真实 UI 验收通过；PR227 合并状态以 GitHub 为准。

## 行为
- 手动点击立即显示按钮加载文字、禁用重复点击并高亮当前客户卡片。
- 自动滚动并聚焦详情区域，显示醒目的读取提示和加载图标；内容加载后再次定位，避免短占位高度导致详情仍停在页面底部。
- 成功、失败及重试均有明确状态；详情加载完成不等于模型报告成功，各节点保留自身状态。
- 后台轮询不滚动、不抢焦点；切换客户时旧请求不能覆盖新状态。
- 使用原 FS brand 令牌适配浅暗色；保留减少动画偏好和权限拒绝处理。

## 当前源码与部署
candidate/page.js、candidate/page.css、candidate/customer-index.html 为最终发布字节。
只替换 /var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/ 下 page.js、page.css、index.html。
candidate/detail-feedback.css 为被合入 page.css 的局部样式片段，不再独立加载；早期新增文件不被最终 HTML 引用。
prepare_release.py 用于从 PR226 原基线构造最终三文件候选，所有旧 SHA 必须匹配；上线后不得重放。polish/prepare_polish.py 仅记录本次第二步基线，不是通用发布入口。
沿用既有 UI 发布器锁/CAS/备份/回滚，没有后台、业务规则、模型调用、权限及定时器改动。

## 验证
node tests/detail-feedback.cjs；node --check candidate/page.js。合成数据交互测试覆盖加载、重复点击、切换竞态、后台轮询、失败重试和权限拒绝。
真实浏览器验证了加载文字、单一选中、焦点、滚动、成功状态及浅暗主题；未在生产人为制造故障或触发付费分析。
详细发布哈希、备份和验收边界见 ACCEPTANCE.md。
