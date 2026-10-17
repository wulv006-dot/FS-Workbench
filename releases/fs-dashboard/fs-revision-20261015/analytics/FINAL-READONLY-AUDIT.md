# 最后独立审计

本轮只读审计没有修改 AI/backend 共享源或生产。FC 前端最后按主线授权接 LV 决策大脑；实际候选 SHA 已重新写入 `changed-source-runtime-map.json`。

FC Details：query 校验、reader、配置、日期缓存键与路径、聚合/金额来源未变；仅队列分离和刷新状态/错误分类。独立一个 worker，原每分钟 3 starts、最多 2 pending、源 subprocess 900s 仍保留。14 个 FC Details 测试、2 个真实 executor 并发测试、生命周期测试通过。range 把同一 FC_DETAIL/FC_DAILY 对象继续交给 DeepService/Hermes；旧 start 调用在退役实现上为 no-op。

FC 退役：4 个 retirement 测试通过，AST 比较 db/bounded_model/_send_model/provider_slot/model_daily_limit/latest/source/build_report/admin 与原现场函数一致。另用本地合成 SQLite 插入一个旧 failed job、指定 revision 的 report、started 无回执 model_call，实测历史 GET 200 原内容/失败状态保留；旧生成返回 410；相同指纹返回 unknown_previous_attempt、callback 调用 0、账本行数不变。没有凭据、模型网络或真实业务数据读取。

已另读当前 Hermes 调用结构：`/opt/fs-hermes-fc/fs_inprocess.py` SHA `6e9dcee7ca003a31ec6a65c15e500e3c25c4cbc1cfc651dac5e2681fe8326dfd`，证据 `../frontend-release/route-live-audit.json`。gateway 使用 direct_provider，复用 daily.db、provider_slot 和 model_daily_limit；不依赖已退役 fc_daily_model.configured 或 ai_advisor_model.request_model。故 DailyReports 默认 configured=false 对旧供应商的退役不会切断当前 Hermes gateway。旧根目录 hermes_fc_pilot_20261013/fs_inprocess.py 是旧模型结构，不能据它判断现网或覆盖现网。workspace_official_model 自己显式使用官方 key-file 存在检查，并用新的 provider_policy 指纹保留旧 supplier 回执。6 个 official workspace 测试通过。

管理利润率：mar 只显示 Order 全站参考值，卡片显式关闭目标达成；「范围不同，不评价主站目标达成」保持。最终组合浏览器用 Order 全站值等于 DY 原目标 25% 的合成输入，卡片显示 25%、原目标 25%，达成是「未评估」，不会再出现 100%。同周期 Admin 主站收入/订单及其客单价独立消费，Order stale 时不会将其冒充主站。目标 JSON 与原包 SHA 保持 `2985f9a48902b577cfe6955b95c82f191a2f34d1bc10302aad8c5d4581ce8102`。

PR140 冲突：其 SOURCE-MAP 两个现场目标 `/var/www/dashboard/fc27-coins.html`、`/var/www/dashboard/fc27-quote-cloud.js`，与本轮 native immutable/mutable/protected、analytics 与 retirement 所有目标集合交集为空。本审计没有替代主线对 PR140 最终 main/blob 的实时校核；没有重验球员价格。

发布前限制仍在：后端/AI 串行上线会改变 native 当前保护 SHA；主线需重读并重冻合同。所有上述通过是本地候选/合成回归；没有 Linux 真实角色、现网发布、真实 provider 响应或自然周期成功声明。
