# 单卡默认普通版 · 2026-11-07

用户本次明确业务规则：Signature是普通版之后额外推出的升级款；同name+Version在完整转换context内只有一张卡时默认normal。两张仍按IS低normal、高Signature；双卡缺IS、同IS、多于两张、重复ID及其它属性错误继续按原合同处理，不把仅勾选一人当完整context单卡。

维护源与调用方沿direct-json-20261029/source/direct_model_payload.py → direct_model_import.prepare_direct_items → 原新卡预览、确认和执行链；只有分类函数新增单卡分支。原context/SHA、身份、范围、原ID、UNKNOWN/回执、六商品同步、缺行情策略、业务价格和图片上传保持。

Windows分类29项及导入25项通过，新增规则先在旧实现准确失败；只选Signature但完整context有双卡仍识别Signature的集成边界通过。原24076/24078同名同版本各一张、IS2625，按新规则均为normal；测试使用合成字段，不提交真实业务。

候选cloud.21沿原publisher和cloud.20的51源基线，运行delta仅player_web/direct_model_payload.py及VERSION；manifest与前后SHA见SOURCE-MAP.json。发布器窄适配与原cloud.19/20相同，备份、双CAS、锁、仅本次差异回退和不回库保护保持；未扩权限或新增依赖。准备包留本工作树.agent_runtime/players-single-card-20261107/stage/，不与原图片任务重放混用。

本次用户授权添加分类规则；#887的两文件/单图发布授权不自动覆盖本cloud.21发布或真实补建。尚未上线，旧失败计划冻结的direct_items不改写，不清scope、不自动补建24076/24078，不重做已完成60人；历史证据和回执保留。合并、生产发布与真实新增分别验收。

独立规则复核无阻断；183/Python3.10.12、Pillow9.0.1隔离Linux的29项分类+25项导入合计54项全部通过、无跳过，包含仅选高IS卡仍为Signature。1CPU/512MiB、无网络/端口、源依赖只读，57个Python源hash测试前后不变。另本release2项固定manifest/源SHA与原wrapper等价检查通过。

知识收尾入口已执行，Windows环境因缺Asia/Shanghai时区数据失败且有平台skip，未报为通过；未改知识目录、Notion或相关平台代码。正式CI结果以本PR实际回执为准。
