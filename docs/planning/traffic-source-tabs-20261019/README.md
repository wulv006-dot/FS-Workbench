# 流量分析三来源改造（已发布）

## 范围与状态
用户2026-10-19授权云端实施、发布验收并提交合并。主标签改为GA4/GSC/Ads，站点改筛选；采用游戏表与所选游戏细分并排结构。Admin主源、Order补源、参考利润估算及全局品牌例外保持。

本批已完成生产发布及独立读回，详细结果与试发布回滚历史见ACCEPTANCE.md。真实数据请求、三来源切换、游戏下钻、历史缓存升级、日期URL恢复、主题与经营页回归均已核验；数据覆盖限制仍按来源显示。

## 源与依赖
- 基线main c1a0f8aea9edb6c1be34fd8e3c29d337374378f2。
- ui-system/modules/native/google.js、google.css：来源页签、游戏表及来源细分。
- mmoexp_google_data/details/game_dimensions.py及game_mapping_20261019.json：用户提供100条广告组映射；名称与稳定ID仍分开，冲突保留未知。
- detail_model.py：输出独立games/game_countries/game_channels；不覆盖来源原生总量。
- collect_details.py：增加landingPage×country/sourceMedium、page×country只读查询，沿用现有身份、配额、分页上限，不改变调度。
- 新helper和JSON必须与detail_model.py同时部署；缺少时不可切换消费者。所有调用detail_model的运行环境均须核查，不只复制单文件。

## 已知未完成项
- Ads实际国家联合查询已编写，真实请求验收通过；系列名称后缀不能当实际国家。
- GA4/GSC游戏归属仅明确路径及标明的News名称线索，未知与通用保留。无分类词表覆盖保证。
- 历史订单source→现系列别名未核，不模糊匹配；不上传原订单或经营数值。
- 参考映射MG-SN-Stickers-EN-US有冲突标签，保持UNKNOWN。
- Hermes当前只通过已有报告入口衔接，本批未新增付费分析或自动预算操作。

## 受控发布
遵循AGENTS及docs/ops/HOTFIX.md。实际页面活动壳观察为workspace-native-20261006-37fe775358df，旧prepare_ui.py常量不是当前现场CAS，禁止重放。须通过合法服务器会话核当前路由、源哈希、依赖、运行进程与发布锁，备份后先数据合同再消费者，保留当前其他业务资产。回滚不得恢复旧数据库、队列、账本或采集状态。

Workbench由用户完成root密钥登录。仅发布本任务相关文件，未更改SSH、安全组、账号或凭据；不把PR合并当作上线证据。

## 当前现场兼容
保留线上壳的2026-10-19导航防闪逻辑、原经营模块资源路径及range_api既有同快照GSC明细补全。游戏投影使用独立版本，旧区间缓存只标待升级并保留历史；重新取数成功后写入现有版本归档。业务归因RULE_VERSION不因展示维度改变。
