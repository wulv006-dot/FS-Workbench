# 一次性共享接线协调清单（方案，未应用）

本文件给父任务和T3 A安排共同窗口；不是部署清单。下面符号为所需接口，不表示线上已有实现。先核owner活动文件/hash，再做最小增量；不整包覆盖当前A/B代码。

## 精确源文件与owner边界

| 源文件 | 最小增量 | owner/当前状态 |
|---|---|---|
| user-analytics-20261022/source/user_runtime.py | 在原build构造Service处注入真实epoch及导出准备/验证/发布器；全部依赖/迁移就绪才开member_keyset_index | 数据owner实施，A确认身份/宿主；本轮未应用此接线 |
| dashboard-refresh-20261025/source/range_api.py | 原已认证GET dispatcher增加capability与小job状态/取消/下载路由，绑定原trusted user；原用户export返回已验证私有artifact回执 | A拥有，未改 |
| hermes-server-unify-20261022/fs_readonly/__init__.py | 原工具注册增加capability/range/status/cancel固定dispatcher；不让模型提交URL/SQL/path或提高预算 | 共享宿主owner+A，未改；30秒/10MB外层保留 |
| user-analytics-20261022/ui/users.js | 仅在服务端声明keyset-v2/artifact-two-phase能力时消费opaque cursor/私有download handle；明确pending/failed/partial；不把receipt当rows | 数据UI owner配合A，未改 |
| dashboard-refresh-20261025/source/business.js、home-business.js、legacy-business.js | 接同一capability日期适配器，修dayMin空值/旧URL/全部/180/365/日历年和half-open；scope/mode变化重取cap | 对应UI owner+A窗口，未改 |
| cache-archive-retention-20261025/source/cache_retention.py | 未来只在原plan/maintenance gate内调用proof/dry-run判定，继续原cache_lock/7日可逆回收/引用扫描失败停止；本候选不提供apply | 原数据维护owner，未改 |
| tiered-data-access-20261101/source内新薄adapter（建议query_member_exports.py、source_adapters.py） | 接真实授权私有artifact宿主与现有Admin/Order reader；下述合同不造身份、URL、第二服务 | 数据owner候选后续实现；目前尚无真实adapter |

不能直接把私有成员流传入hermes-data-workspace-20261018/source/workspace_evidence.py.save：已核它是1MiB aggregate-only证据存储，不是管理员私有流式export。应由A指定已获授权的私有artifact/下载宿主，数据owner做薄适配；若现有宿主没有两阶段流式接口，需要独立小增量及owner确认，不能假称已有。

## 1 真实identity/epoch与scope

`permission_epoch(trusted_user, frozen_query) -> nonempty opaque str`：来自现有IAM/资源授权的实际revision，绑定用户实际可读scope，不来自浏览器、模型或日期policy。每次members/export/status/page/download重验现行grant；撤权或scope/epoch变化立即拒绝旧cursor/handle。A须提供稳定resolver与授权资源的实际来源；没有它就保持关闭，不能用固定fixture-epoch替代。

`get_capability(identity,dataset_id,requested_scope,mode,authorize=existing_grant,resolve=verified_registry)`：先核grant，再给字段/最早可用日/最早允许回源日/跨度/coverage/modes。未核source下界为null、live.enabled=false，不因UI想选日期就放开。scope全站/全游戏只能使用原授权明确枚举，空字符串不当全部。冻结报告仅由dataset声明frozen并校验snapshot/revision，不绕live限制回源。

建议路由`GET /data/capabilities`复用原range宿主及认证代理；最终对外路径由A核当前路由合同确认，不新建server。capability与picker/快捷/手填/保存URL/导出/Hermes用同policy版本。普通fresh必须requested=effective；90天超3日历月时解释禁选，不silent clamp。

## 2 原成员导出的两阶段私有artifact合同

在user_runtime.build的原Service构造点，依赖齐备后才注入：

```python
Service(store, authorize,
        permission_epoch=existing_grant_epoch,
        export_sink=private_export_host.prepare,
        export_verifier=private_export_host.verify,
        export_publisher=private_export_host.publish)
```

`prepare(header, iterator) -> prepared_receipt`：只在私有staging流式写canonical UTF-8 JSONL，每行LF；不注册可下载的已发布对象。完整消费后回执必须含contract=fs-member-export-receipt-v1、status=prepared、opaque artifact_id、snapshot_id/data_version/export_filter_hash、rows/bytes/sha256。失败/取消不能装作成功；处理异常/中断的暂存生命周期沿原宿主策略。

`verify(user, header, receipt) -> True`：从真实私有manifest独立读回，证明句柄存在、归属/权限epoch、scope/filter/水位、相位、行数/字节/hash相符。只返回truthy字典不算通过；不能只相信sink自报。

`publish(user, header, prepared, revalidate) -> published_receipt`：持有原发布锁，在提交manifest/正式引用pin之前调用revalidate()，再原子标published。revalidate核当前private权限和原epoch；无调用/调用失败不得发布。返回status=published及同数据回执，Service再次verify及复验权限后才返回complete。没有任一真实callback则503未就绪。

下载必须走现有认证私有路由，句柄由服务端查manifest生成，不给文件路径或任意URL，不暴露直接public/static文件。每页/chunk核grant/epoch/取消；正式报告/recipe引用必须注册原pin resolver。只读dry-run的dead-lease候选不能作为安全删除授权。

prepare/publish必须沿原artifact ID和幂等key对账；发布结果未知时先读回原manifest，不换ID盲重发。服务在发布后再次发现撤权时会拒绝响应/后续下载，但不能撤销已经提交的artifact或其他外部副作用；只能由原宿主按原ID确认状态、保留证据及处理私有暂存/引用，不能宣传“权限失败就已回滚”。

## 3 受限range adapter/job宿主

固定`adapter(verified_slice_with_server_scope_and_budget) -> {rows,complete,next_cursor,watermark,confirmed_empty}`，来源由dataset registry映射至原reader；Admin原生summary保持整窗，Order/逐笔按实测source_max_slice转换half-open秒/分钟边界，不将全部源套28天。必须验证全部required/nullable/type字段、stable ID、total/边界/水位；来源没有稳定水位就partial/source_unstable，不臆造。

Engine由原宿主持有并注入原admission/maintenance锁、真实grant、Checkpoints.save及固定adapter。恢复只允许同scope/policy/watermark/source_contract，resume_allowed严格True；不能恢复MaterialRun/Agent或重发AI POST。Engine及catalog锁顺序需由A与原archive维护统一，不能只接自己的新锁。HTTP受理用202+queued/job_id，accepted不是另一个隐藏执行状态。大结果返回小状态/artifact引用，不突破Hermes30秒/10MB。

## 一次直接验收与开关

1. 未授权cap不枚举；缓存命中、状态、续页、下载与导出最后发布均撤权失败；scope与epoch从原IAM取得。
2. 同policy UI/API/Hermes边界一致；古老短窗、闰年365/366、缺日期、旧URL、90天/3月交集不合法均不过上游。
3. 原Admin/Order小窗实际请求带scope/date/fields；401/429/timeout/结构漂移非0；budget与source水位可读回；不扩大历史授权。
4. 原writer/recipe及member-keyset逐字段shadow、先后日期修订旧snapshot仍读旧结果；原publish callback准备失败/未消费/失句柄/最后撤权无published成功。
5. 两同scope请求singleflight，单订阅取消不误杀他人；旧代晚结果不能覆盖新checkpoint；真实宿主重启同水位续读，不恢复AI run。
6. 在隔离库核索引空间/WAL/锁与保留合同；生产DDL、路由切换、正式pin/清理policy独立授权。feature flag仅全链路就绪后按dataset启用；回滚只关读路由/开关，保留新事实、receipt、journal、UNKNOWN、key。

真实范围/身份、artifact宿主与活动source map尚未齐，当前不能给出可执行生产payload或最终部署hash。本文件的精确源码路径是协调入口，不冒充运行target。所有共享源本轮保持未应用。
