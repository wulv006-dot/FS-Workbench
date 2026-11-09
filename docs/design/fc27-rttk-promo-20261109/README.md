# FC 27 RTTK 推荐素材 · 2026-11-09

状态：内置 image_gen 实际生成三张 PNG，本地设计交付；未投放、未替换主站横幅或邀请组件。没有使用图片 API key 或 CLI，没有编辑/重采样生成图。

| 文件 | 原生导出 | 目标资源位 | 处理说明 |
|---|---|---|---|
| rttk-desktop-native.png | 2172×724，RGB，3:1 | 3840×1160，约3.31:1 | 工具未按请求精确输出；原文件不是3840px。示例用contain+海军蓝留边，不裁字；上采样不会增加真实细节。 |
| rttk-card-native.png | 1774×887，RGB，2:1 | 1200×600 | 比例准确，原生像素更大；浏览器按目标等比展示，未另做栅格重采样。 |
| rttk-badge-native.png | 1254×1254，32-bit ARGB | 240×240或512×512，实际图示约80px | 工具输出较大原生方图；保留alpha。已读取角像素alpha=0、中心alpha=252，非黑底冒充透明。 |

三张使用深海军蓝球场/抽象卡框，cyan、电光蓝及violet光线。无真实球员、评分、价格、库存或授权声明。文字为 FC 27 / RTTK PICKS / 10% OFF / FC 27 ITEMS / FCSCOUT10 / BUILD YOUR LINEUP；徽章仅FC 27与10% OFF。抽象卡框不代表真实卡面或商品。

## 预览

直接打开 `preview.html`。CSS有低频扫光、4px微浮动和hover反馈；减少动态效果偏好下全部停用。悬浮关闭按钮独立于链接；移动端左侧、底部96px+safe area，避免占用常见右下客服位置（正式接入仍需核实际客服和购物车占位）。没有埋点或后台请求。预览的三个活动链接沿现役 `/events/Player-Trio.html`、`Weekly-Scout.html`、`Sbc-Companions.html`。不创建第二套优惠；原购物车确认券资格且不与优惠券/积分叠加。

素材原始文件约2.09MB、2.14MB、1.49MB，当前是无损设计母版，不把其当作已压缩上线包。正式投放前由总控确认资源位、裁切/压缩及图片可读性；不替换原12%或邀请业务。

## 生成提示记录

均使用内置 image_gen，逐图独立生成。没有参考真实球员照片。

1. Desktop：target3840×1160超宽；left exact copy FC 27、RTTK PICKS、10% OFF、FC 27 ITEMS、FCSCOUT10、BUILD YOUR LINEUP；right abstract collectible-card outlines；midnight stadium/cyan/electric blue/violet；无players/ratings/logos/官方赛事标识，6%安全区。
2. Card：target1200×600，same palette/copy；left typography/right two empty card frames；thumbnail可读；无球员数据、12%、邀请文案。
3. Badge：target512×512，transparent_background=true；navy shield/cyan-violet边缘；only FC 27、10%、OFF；80px可读；无背景矩形或评分。

本轮不是生产部署或真实投放效果验收。
