# 原服务精确增量候选

固定来源提交：`cb87b4901a81ffd313e06e4882a3b33918519ea2`。此包在本地装配，尚未上传、未生成生产manifest、未执行生产写入。源文件before来自2026-11-09T04:45:12Z现役只读快照；每次prepare/inspect/apply仍核SHA，不用旧快照冒充当前状态。

## 载荷与保持范围

9个目标，详见source-proof.json和review.diff：

- `/opt/fs-exact-range-20261001/conversation_http.py`仅增加connector路径的ID解析及两个纯读分支；新增同目录conversation_readonly.py。新分支读取文件列表与材料元数据，不删除过期附件、不运行材料执行/对账/续grant路径。
- `/opt/fs-hermes-fc/tracking_controller.py`只加stored_only分支、tool_read改为customer_snapshot；新增tracking_readonly.py，沿原AdminService与当前Store读SQLite mode=ro/query_only。
- tracking_tool.py保留现役anonymous_snapshot全部原文及计算，增加客户身份/订单明细投影；不将本地新buyer计算覆盖现役。
- customer_tracking.py只删除bind_report中出现邮箱就拒绝的旧条件，原类型/16000字符/CAS等保持，Store.detail等方法完全保持现场原文。
- pool_reports.py只插email/UID并更新说明，不复制本地新增buyer字段或其计算；原聚合/12000字符上限、幂等、UNKNOWN不变。
- customer_reports.py仅更新原报告prompt身份可用性；不启动旧单人自动报告。
- research.py只替换客户追踪工具描述中的强制匿名句；保留现役全部工具、普通cohort权限与其他描述。

不替换range_api、容器镜像、前端、nginx、systemd单元、调度器或数据库；不创建报告或读取Admin网络订单。现役代码有漂移，包内before是回退证据，不能用仓库旧整文件替换after。

## 原发布器与运行影响

release.py是精确目标适配，调用原runtime_release.frozen及release_navigation_base.py（原SHA校验）、software_protected_paths、quiescent与release_readiness。沿原全局发布锁、collector锁、provider锁、Hermes admission fence、逐文件CAS、备份/journal/原rollback。

重载服务为fs-hermes-fc.service与fs-business-range.service，镜像保持原样。原admission fence先阻止新增任务，在确认无活动/UNKNOWN请求、普通/定价会话、学习、客户扫描/旧节点及pool报告后，停止range、解开其事务锁，再沿原HERMES_WORKER_SCOPE重启worker并检查能力接口，随后沿原DEEP_SCOPE重启range，各沿原最长60秒readiness。现役worker的make_adapter启动时调用proxy_gateway.schemas，并导入research.tool_schemas注册到常驻registry，所以必须重启worker才能让工具描述生效。fs-hermes-fc worker保持同一运行镜像，不重启FC调度，不停已有任务抢空闲；忙/UNKNOWN时本次发布应延期。range短暂停止期间依赖该HTTP服务的读取/新任务暂不可用，前端和其他业务进程保持。

inspect额外做不构造服务实例的组合导入，要求实际模块来自candidate/http和candidate/runtime，禁止静默回退线上旧模块。stage导入不发网络业务请求；运行命令均使用-B避免写Python缓存。

## root串行执行

1. 将完整目录上传到新的`/opt/fs-release-stage/<本次唯一目录>`。此处必须完整保留candidate、before、source-proof、review.diff及5个发布helper；勿覆盖旧stage。
2. 在该目录执行`python3 -B release.py observe`。仅输出SHA、文件元数据、worker镜像和状态；不会修改生产目标。若报活动/UNKNOWN或CAS漂移，保留原任务/编号，核状态后延期或重新装配，不能删状态或换发布编号盲重放。
3. root确认本次具体清单后执行`python3 -B release.py prepare --release-ready`，只创建当前stage的approved-manifest/observation。记录其manifest_sha256及source-proof SHA；重新检查完整9目标、所有保护路径、原服务状态和sourceCommit。准备动作不等于已上线。
4. 执行`python3 -B release.py inspect --manifest ./approved-manifest.json`。正式apply必须使用这份manifest的确切SHA和一次性原格式release_id。
5. root授权串行发布命令：`python3 -B release.py apply --manifest ./approved-manifest.json --approved-manifest-sha <确切SHA> --release-id nav-YYYYMMDDTHHMMSSZ`。记录原publisher返回的backup和状态。超时先核journal、已写目标SHA与服务状态，不能换ID重放。

release.py prepare是上传后新鲜现场清单生成入口，不能把本地缺少生产保护路径的模拟清单用作approval。包内helper/候选文件变化即使只改一个字节，也须重新prepare和审阅SHA。

## 回退

使用同一stage、原backup、同一approved-manifest-sha：`python3 -B release.py rollback --backup /var/backups/fs-navigation-20261006/nav-YYYYMMDDTHHMMSSZ --approved-manifest-sha <同一确切SHA>`。原发布器只恢复本包备份代码并移除本包新增目标，沿相同锁、空闲检查以及worker/range重载读回；不恢复数据库、不清新会话/报告/任务，不恢复退役自动报告。回退前若代码已被其他发布覆盖或有在途/UNKNOWN，按原CAS/任务保护停止并核原状态，不能强制覆盖。

## 真实入口验收

沿真实FS HTTPS入口与当前用户原会话测试，身份头只由原网关生成，不能填固定管理员：

- GET原advisor.json的固定stored_only candidates/detail，确认200的业务结果保留stored_only=true/refreshed=false；正常空/缺数据、partial、历史coverage和失败各据实返回，不以HTTP200宣称完整。
- 原admin仍可读其原HTTP范围；无admin/private权限者拒绝。原tool_read仍保留其owner限制，核有权主体可读email/UID/原单号/业务订单字段且不回凭据。
- GET`/api/hermes/conversations/<自己的cid>/connector/files`和`.../connector/materials/<原request_id>`，核真实文件元数据/覆盖/有效期与原私有记录一致；不同owner/未授权拒绝。对不存在对象404只证明合同，不代表真实数据验收完成。
- 对照目标9文件SHA、受保护路径SHA、range健康与worker能力接口、镜像不变及新进程启动时间；仅检查元数据/计数，不将会话cookie或客户数据写入发布日志。
- 上述GET前后只读核相关数据库文件/行状态或调用边界，证明不触发扫描/观测/报告/材料执行；不通过点击生成、刷新或写订单来验只读适配。
- 活跃技能身份旧句还需沿其原publisher另发新版并核current index/task freeze，本代码包不会改历史reviewed哈希，也不能据Python已变称提示知识已生效。

本地精确overlay测试21项通过：实际导入候选、现场未改方法/匿名计算保持、原admin与SQLite只读、完整订单/身份输出、1000条23字符原单号聚合完整且报告仍小于12000、原fence内先worker后range重载、当前两份原只读回归。Linux目标兼容与生产实际验收另记录。
