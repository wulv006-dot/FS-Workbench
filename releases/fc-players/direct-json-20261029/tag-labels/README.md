# FC27 Players 标签显示修复候选

状态：候选，未合并、未发布。真实页面仍需发布后由原浏览器验收。

实际缺陷为 FUTBIN 23700 / 模型 45274659 的标签列显示 `12307 Newest,TOTW；12411 Newest`。2026-10-29 12:08 北京时间只读快照与 Admin GET 证据已冻结到 `../tests/fixtures/tag-labels-23700.json`：实际 `tid=["12307","12411"]` 正确，目录为 12307=Newest、12411=TOTW，旧快照 `tag_names=["Newest,TOTW"]`。

根因：查询将旧名称与目录名称合并去重，输出三项名称，前端再按列表位置匹配两个 ID。复合名称还会造成名称筛选误命中。

最小修复：`model_service.py` 在查询/筛选和新快照保存时按标签 ID 使用该快照的权威目录；旧快照只读兼容，无需数据库迁移。前端也直接按目录 ID 取名。未知 ID 显示 ID，名称留空；两个不同 ID 允许同名。模型 ID、FUTBIN ID、标签 ID、推荐、上下架及写入路径均不修改。

离线验证：真实响应回归 5 项先全部复现失败，修复后全部通过；JSON/续办等合计 85 项、原发布器 16 项全部通过，零跳过；实际前端渲染 4 场景、原续办 DOM 13 场景通过；原模型分页/筛选/导出/操作消费者 12 项通过。测试禁止外网及业务写入，fixture 断言源行及业务 ID 不变。正式 CI 状态以本 PR 的 pr-fast 回执为准。本地完整 driver selfcheck 因稀疏检出不含无关 campaign center.html 而拒绝，未改门槛；正式 CI 全检出验证。

发布候选为 `2026.10.29-cloud.16`；`SOURCE-MAP.json` 冻结现役 cloud.15 的 manifest SHA `d939ac267457adda90ea1c18c0f4372e87676b02e92561791c6f78137f3f38ec`、51 文件中的精确三项基线/候选 SHA及其余 48 项保护。仅两个生产源码与 VERSION。沿原 Players publisher 准备窄增量 stage，发布负责人须审实际 manifest/镜像及 CAS/备份/回滚，不直接临时 bind、不整包重发 cloud15 八目标。版本不是上线回执。

HMAC/client/images、功能 flags、DB/账本/jobs/UNKNOWN、锁及服务身份保持。此候选无 Admin POST，未改变真实标签；不声明生产页面已恢复。

## cloud15 → cloud16 原发布器适配

`upgrade_tag_labels.py` 固定原 `publisher/upgrade_direct_json.py` 的 Git 字节 SHA及本目录 `SOURCE-MAP.json` SHA；只替换该原模块的本次版本/镜像/两 RO bind 来源/manifest 校验与只读账本投影，不改历史文件或其 cloud14→15 常量。main 仍调用原流程，持同一 `deployment.lock`，保原两次 CAS、源码与容器 SHA读回、env/主unit/dropin备份、SQLite online backup、current原子切换、失败回滚。回滚从不覆盖旧DB。原所有表（含已保存图片计划、快照）及 schema 均纳入只读事务指纹，未知写入原ID保留；活动任务拒绝发布。原其它服务状态/PID、price-writer.lock inode保护与 flags 不减。

2026-10-29 本次只读重新核定当前 cloud15 镜像/manifest及配置 SHA：env `16545169…`、主unit `91f2fcee…`、on-demand `50fc07e2…`。真实配置未输出，仅公开 flags。适配器只接受精确三目标及原51完整映射，其余48和HMAC/client/images不变；不接受添加第4目标、改候选SHA、替换基底或占位fixture。

10项新离线合同覆盖正确/错误manifest、两个只读bind、原部署锁竞争、完整DB/schema变动、活动任务拒绝、51源成功切换、事后并发计划变动触发原回滚且保留该新计划/原UNKNOWN，以及打包来自固定Git字节/仅3成员/拒绝覆盖stage。所有systemctl/docker/HTTP均替身，未作真实apply。

仅本地准备stage（不会上传、构建生产镜像或apply）：

```text
python -B releases/fc-players/direct-json-20261029/tag-labels/prepare_tag_labels.py <repo绝对目录> <具体commit> <新的stage绝对目录>
```

工具生成 `delta.tar.gz`、manifest、原publisher、窄适配器、Dockerfile、固定source-map及 `stage-receipt.json`。stage已存在即拒绝，不覆盖未知结果；准备与上线状态分开。部署负责人后续只可经原SSH入口在 `/opt/fc27-player-tool/staging/<本次目录>` 审已sealed字节，显式运行 `upgrade_tag_labels.py <stage绝对目录>`；本说明和准备动作不授apply。服务若按需退出，发布负责人须沿既有唤醒入口，不绕原健康/活动任务/CAS检查。

## 首次 stage 的 VERSION 构建失败及更正

已审原 stage `tag-labels-d5885b6a` 一次执行在原publisher第273行、任何backup/stop/switch之前被51源核验拒绝：候选镜像另外50项匹配，但 `/app/VERSION` 仍是cloud15，host候选VERSION已是cloud16。只读核实无symlink、volume、onbuild或dockerignore干预；镜像有COPY VERSION层。缓存复用旧内容是据此推断，内部缓存机制未直接证实。current/运行镜像仍cloud15、PlayersPID18902未变、DB/schema及env/unit/dropin/manifest/保护状态与原intent完全相同，没有cloud16 backup目录。原失败intent/log/outcome和候选镜像ID `b4957cae1c33f61b8c6b1e8c884d66c3382ceb38191a0fb256f69da35cdcd861` 保留，不重发原stage。

更正保持三个Git源码SHA不变：Dockerfile明确 `COPY VERSION /app/VERSION`，紧接独立RUN检查VERSION精确SHA，防构建缓存静默沿用旧版本；打包成员mtime改为固定Git提交时间，而非一律0，确保同长度版本变更也带新源元数据。Dockerfile校验器严格固定上述两行，不接受旧目标目录、删断言或改预期SHA。新增显式“VERSION copied”回归执行实际RUN断言：同长度cloud15失败、cloud16通过；原10项继续通过，共11项。新stage摘要、CI和独审另记，不修改旧sealed stage，不降低51源验证或删除已生成release16目录绕过原guard。

### Modern Web Guidance

我检查了 responsive-table 指引；此次只修正 ID/名称映射，未应用布局或 API 改动。
