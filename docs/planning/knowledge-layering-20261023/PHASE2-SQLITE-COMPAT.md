# 二期发布环境兼容修复（2026-10-23）

这是原二期候选的增量，不另造发布器，不修改生产数据库。旧27文件、79项本地/9项容器隔离证据以及旧patch保留为当时快照；其中旧native_release.py的真实锁测试不自动覆盖本次新文件。本次准确commit、change_id、patch、正式CI和构建回执由最终交付记录固定，不复用旧生产批准。

## 原因与最小修复

宿主Python3.9.18默认SQLite3.7.17无法解析原生state.db中的`messages_fts_trigram_config ... WITHOUT ROWID`。这不是数据库损坏证据。服务器已安装的门户私有SQLite3.53.4能够只读解析同库四列租约表；库实际SHA256为`d3d896ba27628b174c67cfc6127c92f29c97b48dc3dfe70c84c5f6c28ca4c5f8`。

复用该库，只为发布进程设置环境，不更改Python、系统库、systemd环境、门户或Hermes的运行时：

```sh
LD_LIBRARY_PATH=/opt/auth-portal/registration-runtime-deps/sqlite-3.53.4/lib \
  /opt/python39/bin/python3 -I -B <staging>/release.py <原发布器参数>
```

执行前核对上述现有库SHA。`nativeSQLiteVersion`必须固定为实际`sqlite3.sqlite_version`（本服务器为3.53.4），prepare在创建目录或构建前核对，publisher inspect和每次锁内准入再次核对。运行时不符即拒绝，没有自动降级/切换驱动或schema修复。3.8.2只是WITHOUT ROWID必要语法下限；实际还必须通过整库schema解析，不把版本下限当完整兼容证明。

inspect使用mode=ro/query_only检查实际原生表的四列。生效仍须在原队列/文件准入fence内取得原生库BEGIN IMMEDIATE，并在同一事务重新查租约；任何租约（包括过期未对账行）、锁竞争或schema错误都拒绝。失败关闭连接、释放本批外层fence，不删除原租约，不以先前读到0替代原子准入。回滚重新核租约，未知写入保留原journal/ID。

同时将native-only停止状态读回改为既有兼容格式`systemctl show ... -p ActiveState`解析，避免旧systemctl不支持`--value`。仍只拟操作Desktop与原关联飞书网关；本阶段不实际操作服务。

首个正式CI（run39889518679，head8112be5）发现两个`existing_adapter_drift`错误：旧候选固定了Windows检出CRLF哈希，而暂存工具还会把冻结底座改成LF。现适配器固定Git规范LF字节SHA`cf06b7ca5d9ab33a849c6e18d735bb57557d664aabb0df08770f9a4941ad75ee`；冻结底座继续原样复制并严格核`1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de`，不改底座或兼容接受任意哈希。新增暂存实际输出→原publisher装配检查，旧失败保留，不沿首次CI结果发布。

## 验证与限制

- 本机Python3.12.14/SQLite3.53.1：知识/收尾/发布47项通过，含真实格式WITHOUT ROWID、四列租约、跨进程准入互斥、先读0后并发租约拒绝、schema异常不修复/不进入发布、连接释放和原发布器精确回滚/原ID拒重，以及已有本地基础镜像标签/ID/层及源码读回检查。旧3.7.17拒绝用显式版本测试；不假称本机实际运行了旧SQLite。
- 服务器Python3.9.18：仅设置单次进程的LD_LIBRARY_PATH，实际SQLite3.53.4只读读取现有Hermes库成功，未BEGIN/写库/取生产发布锁。真实生产发布fence和恢复尚未执行。
- 原生插件/接线原38项按受影响范围复验；旧9项真实容器检查只覆盖其记录的文件哈希。用户UI、完整provider初始化、模型效果仍未验，当前0模型调用。
- 正式CI和隔离构建已获准备授权，待实际回执更新；合并、生产四载荷替换、服务切换尚未获批，不能把本文件当上线回执。

## 发布前准备与生效边界

新候选完成后整合当前main，推送原分支`codex/knowledge-native-fs-20261023`并创建一个PR运行既有pr-fast，暂不合并。

获批的隔离构建operation为`KL-9156f40571ce279f40f60698:preflight-build-1`，只标识构建意图；标签`fs-hermes-native:knowledge-3339d3e17ca53ec1c0536f7c`，暂存`/var/tmp/fs-knowledge-native-preflight-KL-9156f40571ce279f40f60698-1`。记录它与新候选的映射，不能据旧ID执行生产。已有目录/标签或未知回执先对账，不盲重建。只复用原镜像8251bc53…，三文件上下文、network=none、pull=false，临时校验容器只读无网络且不挂载生产。镜像源SHA与最终image ID通过后仍不启用。

首次实际构建在FROM解析阶段失败：裸`sha256:8251…`被BuildKit当作仓库名，原子镜像标签仍不存在。第二次同ID对账续办已正确找到本地基础镜像，但RUN按基础镜像非root用户执行，无法写root所有的工厂文件；仍无子镜像。原日志和状态均保留，不登录仓库、申请权限或改运行用户。

现使用已经存在的`fs-hermes-fc:71d34bad-precheck`，前后严格核其完整ID等于原镜像；在宿主暂存内用精确SHA补丁生成factory，Dockerfile只COPY构造器及已补丁工厂两文件，不运行写工厂程序。三文件构建上下文改为Dockerfile、构造器和派生factory，补丁器源码及输入/输出SHA另记。子层必须以原层为前缀且只增加两层，最终运行User必须与原镜像一致。标签只是定位，不能替代完整ID/层和源码读回。`finish_candidate`仅在原状态已有已核验构建回执时完成releaseReady=false预览，不重建或发布；未知状态不能直接完成候选。[Docker构建参数说明](https://docs.docker.com/reference/cli/docker/buildx/build/)。

未来上线清单须固定四主机载荷前后SHA、策略native段的具体新FS会话、当前非native字段保留哈希、旧/新不可变镜像、Desktop及关联飞书网关自然排空与短暂影响、原ID/CAS/前值回滚。保护worker/range/Nginx、所有DB/消息/队列/技能/学习和既有调度。仅文档或本轮构建不重启服务。

无计费FS验收应读取专用空新会话的实际platform/profile/session、两读工具集合、知识release/catalog/条目SHA、task及使用回执；不能用手工调用helper代替真实入口。真实模型另列模型、请求数、输入/输出token及美元硬限制；未证明可执行上限前保持0调用，不以最大迭代数冒充费用上限。飞书消息、Notion和老D调度不在本批操作范围。
