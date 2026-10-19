# 客单详情点击反馈验收 · 2026-10-19

## 状态
- 生产入口 https://47.85.224.112/dashboard/fs-home/hermes/customer-tracking/
- 2026-10-19 23:16–23:17 Asia/Shanghai 独立读回与真实浏览器验收通过。
- PR https://github.com/wulv006-dot/FS-Workbench/pull/227；Git 合并状态以 PR 为准。
- 无业务写入、付费模型调用、权限、密钥、后台服务或调度变更。

## 发布过程和边界
云端 Workbench 登录恢复后先核验 PR226 原 page.js/HTML 哈希完全匹配。
首次发布 nav-20261019T151230Z 生效交互，但实际浏览器发现新增 CSS 未产生预期视觉效果；没有以文件存在或部署成功冒充验收。改用原 page.css 路由合入局部样式，并版本化 CSS/JS URL，经第二次受控发布修正。
第一次误用非时间戳 release_id 被发布器在写入前拒绝，按原格式更正；未放宽发布检查。

- 原 manifest d201577daf4e5ae57dd2a8ae88f9bb8e47ac4c9c6720bf570044aac0a9b20c4e
- 原备份 /var/backups/fs-navigation-20261006/nav-20261019T151230Z
- 最终 manifest 4842e1aa5c744b22545745440195bf90506ac34d581cec455e317e4586d58553
- 最终备份 /var/backups/fs-navigation-20261006/nav-20261019T151600Z
- stage /opt/fs-release-stage/customer-detail-feedback-20261019/polish
- 最终三文件 SHA256 全部独立匹配；保护文件全部一致。Nginx 配置测试通过，发布器报告业务 worker/timer 动作为 0。

## 最终文件
目标目录 /var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/
- page.js：55cc9c2417dc09e1835243d26250cee2acad2aeb179dcdab49125e461048b02f
- page.css：e613219c73c7867b530bd45d578c979b4ebbb75486a722f91d02c7ccf9bc662e
- index.html：6834d09bd80eda072f7bb32d1247e0b1ed274d935a823f0058284929a44f9b07

## 验收
真实 wulv 登录态：点击后按钮立即“正在加载订单与节点…”，详情区 aria-busy/loading，焦点转移到 detail-section；跨客户保持一个 selected/expanded。成功后显示“订单与观察节点已加载”，焦点与滚动定位到详情顶部。最终提示条 1px 边框、生效品牌色；深色主题背景/文字/边框可辨，测试后恢复浅色。仍按各节点状态显示待到期/失败/就绪，不误宣告报告成功。
本地 Node VM 合成测试通过：加载状态、禁止重复请求、跨客户旧响应隔离、后台更新不抢焦点、失败后可重试、403 权限拒绝。node --check 通过。
生产没有人为制造失败、改变观察名单、扫描区间或调用模型；合成测试不等于真实故障注入。截图仅临时视觉核查，没有上传客户/订单详情到仓库或文档。

## 回滚
沿用原 release_ui.py 的受限 rollback，按本次备份从第二次到第一次逆序处理；先核现场哈希与并行发布，不用旧整包覆盖。保留业务数据、调度和账本。新发布脚本不能直接重放已消耗的原基线。
