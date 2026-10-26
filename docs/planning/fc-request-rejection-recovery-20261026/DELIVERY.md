# 改价台明确拒绝回执修复交付

原问题：15:22:39原采价POST收到HTTP503 `queue_mutation_busy`、`accepted:false`，服务端原ID未入队；页面仍保存pending并持续GET404，按钮被占用。原采价ID`fca31592-2466-4472-a341-e8981966031f`经查未入队后受控同ID恢复，随后同run完成预览与用户授权的一次即时压价；真实写入单`26f9a1b9-4480-4379-9ed0-da2a079b7901`已独立核ALL/cache/public，详见临时定价DELIVERY。该恢复先于本页面补丁，不算补丁线上故障注入测试。

PR491最终`43e4eb6a2e191d1804abd5b2aa1a33009ed5396e`，正式CI`40288356941`通过，merge`c7bcb080b344ba6d2f60724637142a842cc7e675`。本地VM八场景通过：采价/预览/执行明确503拒绝释放pending，未知5xx、网络中断、原GET404均保留原ID且不自动重发；原4xx合同与页面临时策略不变。两文件前后SHA见SOURCE-MAP。原发布器初次进入误套交易采集锁即失败，`nav-20261026T075206Z`备份/日志均不存在、两文件未写。原`fs-business-range`长驻持有collector.lock，不能中断它。

PR492仅修精确静态scope的无关交易采集锁：最终`dbfe75d1cd14cc975e8a0287f9e094ad2eedd9b3`，正式CI`40288928624`通过，merge`6f34b06405bb832760ac606e5483c5fe3f530cf6`。原全局发布锁、FC队列/重试锁、CAS/备份/90目标保护、静态无服务重启仍保留。原同ID发布`nav-20261026T075206Z`完成，两静态目标SHA读回与清单一致，90保护目标无漂移，队列0、未完成写入0，业务worker/timer动作0。实际登录wulv页面重新加载见新JS `fc-request-rejection-20261026-v1`、采集按钮可用、无错误、原执行ID保留，页面显示PS/Xbox/PC最近公开$8.68；截图`.agent_runtime/fc-review-channel-20261026/drop-live-ui.jpg`。

未做线上故意打满队列以制造第二次503；这一分支由真实首次拒绝回执和同源八场景离线检查共同验证。当前报价过期不额外采价，下一自然周期另验。Notion此前获准摘要属旧时点，未擅自重写或追加本次新规则/执行。
