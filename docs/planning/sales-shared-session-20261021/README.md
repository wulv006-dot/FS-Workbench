# 认证迁移历史与当前维护入口

当前维护源与测试：[shared_backend_session](../../../shared_backend_session/README.md)。Sales只消费全局Admin8767与全局Order8768；SBC页面和客户端不再包含独立登录入口。

迁移历史：[DEPLOYMENT.md](DEPLOYMENT.md)、[人工恢复](MANUAL-RECOVERY.md)、[验证后清理](CLEANUP.md)。旧一次性脚本已由当前源替代，不再按历史模板部署；原代码可在PR265/266的Git历史审计，凭据与原始服务器备份仅留受限服务器目录。
