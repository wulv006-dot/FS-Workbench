# 追踪独立授权实际验收

2026-11-09，用户在整批页面部署被自动审批拒绝后再次明确“允许追踪”。只实施这6文件的追踪范围，未实施其余页面、导航或四包业务发布。

manifest `1d8d686405640c290912688f7d1a21b984a6aa51f11aaf89944fcec0f7958b5c`；release `nav-20261109T140059Z`；backup `/var/backups/fs-navigation-20261006/nav-20261109T140059Z`。原publisher返回6文件已应用；读回6个after SHA及59守卫匹配、三服务active、enabled=true。原活动27、policy/config/rule及原发布操作保持。初始报价缓存未就绪，14:03:13 UTC自然预热恢复ready78，未手动刷新或修改业务配置。

真实Chrome测试标记 `6f672eb9-f1c3-4bfc-985c-7f445cecd983`；开始前Query三页无该标记。既有同意下初次view1；显式拒绝后平台改变及刷新未新增；再允许后正常操作，14:18 UTC分别读回Scout8/SBC6/Trio6个唯一事件，三页均含访问、商品曝光和选择，environment=test。正式统计排除该标记；没有浏览器伪造purchase。

14:16 UTC原登录FS活动面板实际读取UTC当日FCSCOUT10合计0笔/$0、退款订单0，明确为三页合计整单USD，非单页归因/净收入。当前无非零付款正例。购物车原有2条PS商品保持，未新增加购或付款，所以本轮新追踪的confirmed-cart接收尚未验；既有共享桥和旧27真实购物车记录按原范围复用。

本地证据：`.agent_runtime/weekly-console/{tracking-authorized-apply.json,tracking-authorized-live-readback.json,tracking-authorized-live-readback-initial.json,tracking-final-events.jsonl}`；真实界面截图另存同目录。事件数是14:18 UTC读回快照，不把关闭页面后可能追加的正常参与时长事件当重复访问。

源码PR960/CI1850成功；补充旧数据回归和追踪清单PR961/CI1851成功。其余页面18+导航18仅候选，四包迁移/审阅/正式发布及自然周更仍待对应实际执行验收。
