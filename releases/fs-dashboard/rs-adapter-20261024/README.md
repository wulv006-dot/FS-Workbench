# RS经营看板适配候选

业务/交互：[方案](../../../docs/planning/rs-business-adapter-20261024/PLAN.md)。验证与未验范围：[验收](../../../docs/planning/rs-business-adapter-20261024/ACCEPTANCE.md)。活动来源与候选哈希：[SOURCE-MAP](../../../docs/planning/rs-business-adapter-20261024/SOURCE-MAP.json)。

source/为候选源码。build.py仅按本次冻结现场字节生成，不覆盖原维护目录。baseline/为忽略的私有只读基线；stage/为忽略的生成包。现有代码/数据/服务未因本目录存在而生效。

常用入口：网站 → 类目；区服位于“更多筛选”、默认全部。原生站点/类目统计复用现有全局Admin；利润继续为有范围说明的Order参考，不增加自动业务写入或独立登录。
