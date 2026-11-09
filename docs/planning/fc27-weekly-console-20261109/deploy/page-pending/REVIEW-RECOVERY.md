# 完成核价后的原任务恢复

四包原位导入补丁PR964、CI1854通过并合并为3353d7a。单个products.js沿原publisher部署为nav-20261109T153338Z，未重启业务服务。真实UI一次保存草稿28，operationId5808b688-14e0-4d21-a47d-07633c24dd70；53旧模型、其余草稿及三页缺省选择摘要均保持，模型总数57，四个组合三平台身份精确一致，公开仍27。

原编辑器保存后自动review在后台完成，但前端收到超时。后续浏览器原确认框操作失去响应，恢复后只读确认保存结果与公开版本，未重复保存。16:27 UTC重新进入原发布页，Nginx于16:28:15返回504/upstream timeout；后台仍于16:28:59完成proposal011de741-aeea-4e14-8a08-7f3391ab617b、review72c5c41e…，can_publish=true、无blockers。该候选仅增加Weekly/SBC24条绑定，原1626条逐字保留；Trio原有legacy12及admin12均保持，不能把原Trio总数误写为12。

真正的恢复缺陷是：后端原readRun对已完成review一律返回can_publish=false/requires_review=true；前端自动恢复只复用publication，其他情况又POST全量核价。界面无法只读回收已完成的核价，容易循环超时。

修复仅weekly-workflow.mjs与weekly.js。后端沿原owner/run、revision/draft hash、review有效期、同步validateCommerce的proposal/policy/TTL校验，允许GET恢复仍有效的审阅；用原同步makePreviews更新进程内私有预览令牌，review哈希和到期时间保持，不写草稿、政策、审阅或发布记录、不重取Admin/model。已知陈旧情况仍要求重新核价，损坏或权限错误不隐藏。前端首载/返回发布/读取状态优先GET，仅在无有效审阅时POST；明确“重新核对”仍强制fresh review，发布仍需原确认和服务端重新校验。

相关workflow/commerce20项测试和原周更浏览器24组检查通过，覆盖504后只GET恢复、预览与确认可用、过期/草稿/政策/权限/损坏反例以及原发布ID恢复。新测试没有生产写入。

激活需要重启fs-campaign-dashboard。已核现有admin-price-provider启动时内存为空会暂写REFERENCE_PRICE_REFRESHING/unavailable，之前实测约272秒后原producer自然恢复；不能宣称缓存不受影响。本次不改provider、不重启runtime/range/Hermes、不改调度或Nginx等待时限。实际部署、缓存恢复及正式发布均需另读回；现有候选过期不可强行使用。
