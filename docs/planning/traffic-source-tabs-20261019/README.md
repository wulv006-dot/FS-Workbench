# 流量分析三来源改造（候选）

## 范围与状态
用户2026-10-19授权云端实施、发布验收并提交合并。主标签改为GA4/GSC/Ads，站点改筛选；采用游戏表与所选游戏细分并排结构。Admin主源、Order补源、参考利润估算及全局品牌例外保持。

本批为未发布候选，不声称生产完成。27项相关Python单元通过，JS语法通过；真实联合查询、浏览器交互、主题以及部署读回待完成。云端浏览器与执行工作区的localhost不互通，候选浏览器验收尚未完成。

## 源与依赖
- 基线main c1a0f8aea9edb6c1be34fd8e3c29d337374378f2。
- ui-system/modules/native/google.js、google.css：来源页签、游戏表及来源细分。
- mmoexp_google_data/details/game_dimensions.py及game_mapping_20261019.json：用户提供100条广告组映射；名称与稳定ID仍分开，冲突保留未知。
- detail_model.py：输出独立games/game_countries/game_channels；不覆盖来源原生总量。
- collect_details.py：增加landingPage×country/sourceMedium、page×country只读查询，沿用现有身份、配额、分页上限，不改变调度。
- 新helper和JSON必须与detail_model.py同时部署；缺少时不可切换消费者。所有调用detail_model的运行环境均须核查，不只复制单文件。

## 已知未完成项
- Ads实际国家联合查询尚未接入；系列名称后缀不能当实际国家。
- GA4/GSC游戏归属仅明确路径及标明的News名称线索，未知与通用保留。无分类词表覆盖保证。
- 历史订单source→现系列别名未核，不模糊匹配；不上传原订单或经营数值。
- 参考映射MG-SN-Stickers-EN-US有冲突标签，保持UNKNOWN。
- Hermes当前只通过已有报告入口衔接，本批未新增付费分析或自动预算操作。

## 受控发布
遵循AGENTS及docs/ops/HOTFIX.md。实际页面活动壳观察为workspace-native-20261006-37fe775358df，旧prepare_ui.py常量不是当前现场CAS，禁止重放。须通过合法服务器会话核当前路由、源哈希、依赖、运行进程与发布锁，备份后先数据合同再消费者，保留当前其他业务资产。回滚不得恢复旧数据库、队列、账本或采集状态。

Workbench现有root免密连接失败，未修改SSH、安全组、凭据或登录设置。发布条件未满足，不合并为已交付版本。待真实查询、页面切换、日期切换/返回、缺失/部分/过期、浅暗主题验收与现场读回后更新本记录。
