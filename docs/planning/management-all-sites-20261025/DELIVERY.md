# 交付状态

修复根因：管理台仍强制要求主站查询，并从Admin渠道行抽取主站销售额；RS全站适配器返回全部网站及CNY发货统计参考率后不兼容。全项目改用核准原生全站顶层统计，不混合不同币种金额。

当前候选：Linux 6项口径/锁/回执测试通过，前端合同检查通过，真实15项目月累计均有全站销售额、订单及参考利润。完整逐日候选正在原只读API范围内生成，正式CI与上线/真实入口状态见ACCEPTANCE。

发布复用原channel-effects frozen navigation publisher和shipping_readiness，保留CAS、备份、准入、模型锁及回滚；只更新SOURCE-MAP八文件，不修改目标配置、定时器或价格。现有完整业务基准只追加本次规则，knowledge-load-policy只替换原wulv/FS/fs基准兼容SHA，不发布新目录，不主动调用收费模型。
