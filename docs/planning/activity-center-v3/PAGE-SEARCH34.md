# PAGE-SEARCH34：原商品编辑入口与有界检索

范围：只修改“商品编辑与预览”及其商品检索/草稿合同。活动转化分析页、查询口径、图表、布局、共享导航及现有业务数据不修改。本轮不部署、不保存生产草稿、不提交 Admin 业务写入。

## 入口与兼容

2026-10-25 原本机 Chrome 现场沿 `/dashboard/analytics/campaigns/analytics/` → 左栏“商品编辑与预览”，确认为 `products.html`，显示旧预设球员编辑器。RELEASE33 的四页配置在另一 URL，不能算原入口接通。

候选唯一实现为 `analytics/products.html` + `products.js`。原 `center.html/js` 静态实现移除；`center.html` 仅经原鉴权后单跳到 products。不存在 iframe、模板代理或 `?view=original` 第二套编辑器。原必要 FC weekly/trio/bundles/SBC 默认核心、搭档和备选控件并入同一编辑器表单。Seasonal 使用自己的主题、商品池和角色。

唯一编辑草稿为 `api/center` 的 revision/operation_id/draft，原 FC 编排纳入 draft.fc_layout，复用既有 validateLayout。旧业务 state.json 的 layout 仅在新草稿缺少 fc_layout 时作为只读缺省；首次用户授权保存才落入 center 草稿，不自动迁移或回写旧 state/registry。旧审计、历史、公开快照保留。数据页仍使用原接口，不随编辑器迁移改变。

旧 center sessionStorage pending 键继续兼容，防止换入口遗失未确认操作；待无旧 pending 及旧书签消费者后才可另行移除兼容。旧 center.js 不再服务；生产旧字节在下一次获批发布时隔离退役而非公开保留，原备份保留可回退。

## 搜索事实与修复边界

- RELEASE33：准确 goods_id 查询、模型关联查询、Gold Non Rare + 平台21587/类型9627 的两页查询及非预设170485033详情成功。未扫完整目录。
- 无平台/类型的 Haaland 查询于 09:15:29Z 返回504。Nginx错误记录证实等待8948响应头超时。
- 原共享 get_admin 每次60秒，异常最多3次；活动子进程120秒。代理先超时、后台可能继续重试，前端把HTML504误报成业务操作未知。
- 一次有界 `title LIKE Haaland` 对照读取在20.014秒超时；不据此捏造索引/SQL执行计划或认为改title字段已解决性能。
- 候选仅 catalog_search 复用同一合法Session/admin/token，固定原端点单次GET，无redirect、自动重试或401刷新，20秒总期限；Node外层35秒。未改共享鉴权或Nginx/生产超时配置。
- 超时/拒绝/格式错误明确显示“未取得结果”，不假空、不回退预设、不静默截断。修改筛选后回第一页；保留关键词、商品ID、模型ID及真实分页入口。

**尚未解决：上游无附加筛选的宽关键词为何缓慢。** 当前证据不足以独立修改主站查询计划。下一步需要原商品列表查询实现/慢查询或可证明的索引/筛选语义；不以延长代理超时、批量扫描或本地预设替代。此次客户端保护修复不得标为宽关键词性能已通过。

## 模型与 SKU

goods.Goods/index 支持当前已证分页参数；goods/edit 提供真实 mid，GoodsMould/edit 提供该模型详情。模型ID查询的是关联商品，不是SKU。商品与模型的 `more.saleprop / skuTableSet` 是当前可核对规格来源；空、缺失、非空待映射必须区别。没有已证实的独立SKU查询端点，也不能把 gold 数量档位当SKU。未知规格/单位不开放购买。

## 后续一次性批准建议（本轮未执行）

1. 仅发布最终已审候选的商品编辑/搜索运行差异，核原数据页及全部业务配置哈希；原导航进入 products 验证。退役旧 center 静态源码，保留单跳URL及备份，不删配置/审计。
2. 若批准真实保存：先备份最新完整 center 草稿、旧 layout 和当前公开快照，确认无pending/并发；在一个页面未发布草稿中调整两项**已有商品**顺序，使用固定操作ID保存一次，独立读回，然后以第二固定ID恢复原完整草稿并读回。只增加审计版本，不改变公开快照、旧layout、优惠或购买门禁。结果未知只按原ID核对。
3. 此最小验证不导入新商品，因导入元数据为server-owned，不能假称恢复页面选择即删除全部导入历史；导入保存仍单列未验。不能点击“发布已保存预览”。发生并发变更即停止恢复覆盖，按原操作对账。

已有 RELEASE33 真实查询证据与本轮合成测试分别记录；候选、合并、部署、真实保存不可混称。
