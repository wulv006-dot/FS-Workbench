# Hermes ES 结构查询路由修复

FC 原复盘 e54c0c7270ec411c885bca010d65bc89 的两次查询为 FC27、product、2026-11-06 和 2026-10-30；模型已完成，不重新提交。两日已有归档用现役解析器离线投影均 available，各5组，不产生新导出。

生产 conversation_user_data.py 将 /advisor 的 mode=hermes 错误送至 ADVISOR.get，而同一 HTTP 路由实际用 HERMES.get。旧 Advisor 只接受 id/memory，返回422，native继而抛出异常，对外成为503。修复内部选择，与现役HTTP保持一致；原binding、资源授权和读前读后guard不变，不使用固定账号请求头。

活动源码：releases/fs-dashboard/hermes-conversation-20261018/source/conversation_user_data.py → /opt/fs-hermes-fc/conversation_user_data.py。影响同一native读取中的ES商品结构、优惠结构、商品订单查询；普通汇总/模型/定价不变。

新增测试在修复前报 native_fs_http_422，修复后15项相关测试通过；验证合成operator身份透传和读前/读后撤权，非生产身份注入。183隔离目录首次缺3项既有依赖，补齐后另记录结果。生产发布及实际入口读回单独验收，不以代码/测试当上线。
