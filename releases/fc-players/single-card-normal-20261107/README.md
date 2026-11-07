# 单卡默认普通版 · 2026-11-07

用户本次明确业务规则：Signature是普通版之后额外推出的升级款；同name+Version在完整转换context内只有一张卡时默认normal。两张仍按IS低normal、高Signature；双卡缺IS、同IS、多于两张、重复ID及其它属性错误继续按原合同处理，不把仅勾选一人当完整context单卡。

维护源与调用方沿direct-json-20261029/source/direct_model_payload.py → direct_model_import.prepare_direct_items → 原新卡预览、确认和执行链；只有分类函数新增单卡分支。原context/SHA、身份、范围、原ID、UNKNOWN/回执、六商品同步、缺行情策略、业务价格和图片上传保持。

Windows分类29项及导入25项通过，新增规则先在旧实现准确失败；只选Signature但完整context有双卡仍识别Signature的集成边界通过。原24076/24078同名同版本各一张、IS2625，按新规则均为normal；测试使用合成字段，不提交真实业务。

候选cloud.21沿原publisher和cloud.20的51源基线，运行delta仅player_web/direct_model_payload.py及VERSION；manifest与前后SHA见SOURCE-MAP.json。发布器窄适配与原cloud.19/20相同，备份、双CAS、锁、仅本次差异回退和不回库保护保持；未扩权限或新增依赖。准备包留本工作树.agent_runtime/players-single-card-20261107/stage/，不与原图片任务重放混用。

本次用户授权添加分类规则；#887的两文件/单图发布授权不自动覆盖本cloud.21发布或真实补建。尚未上线，旧失败计划冻结的direct_items不改写，不清scope、不自动补建24076/24078，不重做已完成60人；历史证据和回执保留。合并、生产发布与真实新增分别验收。

独立规则复核无阻断；183/Python3.10.12、Pillow9.0.1隔离Linux的29项分类+25项导入合计54项全部通过、无跳过，包含仅选高IS卡仍为Signature。1CPU/512MiB、无网络/端口、源依赖只读，57个Python源hash测试前后不变。另本release2项固定manifest/源SHA与原wrapper等价检查通过。

知识收尾入口已执行，Windows环境因缺Asia/Shanghai时区数据失败且有平台skip，未报为通过；未改知识目录、Notion或相关平台代码。正式CI结果以本PR实际回执为准。

## 本轮发布、原批补齐与用户最终口径

用户明确批准#891合并发布。为满足更新后的main，合入#892后head03137b6c的正式CI42337072409通过，merge4cdbac68e0c7297a541b15cea1a18ecfd6e1c755。原publisher在04:12 UTC成功发布cloud.21，备份`/opt/fc27-player-tool/backups/2026.11.07-cloud.21-20261107T041227Z`；运行镜像sha256:7c39cceb56d63db99d98287d79b3ddf439cd0b9ba61a442b6728842a95373e13，实际分类模块SHA5a187611e572a4c6edc13ad893b5f5a82083f2edd4af03be703d6572678fdde3，两张原context实际判normal，双卡normal/Signature保持。

首次候选镜像仅VERSION仍旧cloud.20，被51源哈希核验挡在切换前；BuildKit no-cache仍传旧同mtime/大小上下文，证据保留。只为本次原publisher设置DOCKER_BUILDKIT=0后核验通过，未修改publisher、关闭校验或改变全局配置。中间一次因原600秒按需退出停在active预检，唤醒原服务后接续；不把正常按需退出当故障。发布前后原账本摘要相同、0业务写入；FC API4267/worker4264保持09:21:38启动。

用户随后明确授权处理完整原批，并反复澄清最终口径：失败具体哪名/哪个商品/哪步就记录并跳过，继续正常项；最终明确报告失败供人工介入，不扩大为整批/全功能禁用，不撤销正确成功项。逐项启售保留，无整批同时启售要求。图片缺失/上传失败不影响售卖，独立记录，不设启售门槛。

原两卡通过无days姓名查询和导出证明确为同名同UEL RTTK全源单例。只在原execution942d57f3cbff4e0da38291a7dc0b5c9d内为24076/24078追加有SHA及未派发add证据的root_controlled派生计划，原冻结计划/digest、60个verified及其它回执不改。沿现有direct链仅补两名，最终62verified、completed_readback/done，无pending/unresolved。新增模型24076=45496989、24078=45496991，图0按用户允许后补；12个商品沿原缺行情9999策略同步/兜底并读回，非新推荐价格。持久化恢复标记防重发，不重复创建或同步原60名。

全量现场读回62模型、372商品，均覆盖原两网站×三平台六组合、启售且有正值unit_price。原60名后来合法完成的图片保留，不重传。旧60中55名model.ps_price/pc_price与原冻结游戏币输入不同，抽样与当前源也有差异；没有更新来源/时点证明，记录待核，不据此断言错价、合法同步或盈利正确，不用旧值覆盖当前数据，不扩大拦截。本批操作完成不等于现价公式/所有行情新鲜度独立审计通过。

实际证据在本工作树`.agent_runtime/players-single-card-20261107/`的deploy-*.log、build-inspect*.log、readonly-verified.json、recover-two.log、batch-audit-final.json、live-cloud21.json。行情只读抽样和独立复核证据留原E盘同任务目录。后续系统复核只修已复现的分类窗口完整性与原ID续跑选择问题；不改逐项启售、金额公式或写入保护。自然周期未额外触发，原FC自动化保持。
