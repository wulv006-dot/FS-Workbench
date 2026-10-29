# FC27 Players 标签显示修复候选

状态：候选，未合并、未发布。真实页面仍需发布后由原浏览器验收。

实际缺陷为 FUTBIN 23700 / 模型 45274659 的标签列显示 `12307 Newest,TOTW；12411 Newest`。2026-10-29 12:08 北京时间只读快照与 Admin GET 证据已冻结到 `../tests/fixtures/tag-labels-23700.json`：实际 `tid=["12307","12411"]` 正确，目录为 12307=Newest、12411=TOTW，旧快照 `tag_names=["Newest,TOTW"]`。

根因：查询将旧名称与目录名称合并去重，输出三项名称，前端再按列表位置匹配两个 ID。复合名称还会造成名称筛选误命中。

最小修复：`model_service.py` 在查询/筛选和新快照保存时按标签 ID 使用该快照的权威目录；旧快照只读兼容，无需数据库迁移。前端也直接按目录 ID 取名。未知 ID 显示 ID，名称留空；两个不同 ID 允许同名。模型 ID、FUTBIN ID、标签 ID、推荐、上下架及写入路径均不修改。

离线验证：真实响应回归 5 项先全部复现失败，修复后全部通过；JSON/续办等合计 85 项、原发布器 16 项全部通过，零跳过；实际前端渲染 4 场景、原续办 DOM 13 场景通过；原模型分页/筛选/导出/操作消费者 12 项通过。测试禁止外网及业务写入，fixture 断言源行及业务 ID 不变。正式 CI 状态以本 PR 的 pr-fast 回执为准。本地完整 driver selfcheck 因稀疏检出不含无关 campaign center.html 而拒绝，未改门槛；正式 CI 全检出验证。

发布候选为 `2026.10.29-cloud.16`；`SOURCE-MAP.json` 冻结现役 cloud.15 的 manifest SHA `d939ac267457adda90ea1c18c0f4372e87676b02e92561791c6f78137f3f38ec`、51 文件中的精确三项基线/候选 SHA及其余 48 项保护。仅两个生产源码与 VERSION。沿原 Players publisher 准备窄增量 stage，发布负责人须审实际 manifest/镜像及 CAS/备份/回滚，不直接临时 bind、不整包重发 cloud15 八目标。版本不是上线回执。

HMAC/client/images、功能 flags、DB/账本/jobs/UNKNOWN、锁及服务身份保持。此候选无 Admin POST，未改变真实标签；不声明生产页面已恢复。

### Modern Web Guidance

我检查了 responsive-table 指引；此次只修正 ID/名称映射，未应用布局或 API 改动。
