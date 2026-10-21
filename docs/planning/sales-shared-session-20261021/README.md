# 共享会话维护与Sales验收

当前维护源与测试：[shared_backend_session](../../../shared_backend_session/README.md)。8767图片验证码采用既有OCR流程；完整登录、2FA及发布边界见 [当前登录合同](../../../shared_backend_session/OCR-SESSION.md)。Sales只消费全局Admin8767与全局Order8768；SBC页面和客户端不包含独立登录入口。

认证迁移及客户端清理结果见 [DEPLOYMENT.md](DEPLOYMENT.md) 和 [CLEANUP.md](CLEANUP.md)。这些记录不作为旧镜像重新部署或恢复独立登录的依据。

Sales全量及首轮自然周期均已在当时通过，分别见 [FINAL-ACCEPTANCE.md](FINAL-ACCEPTANCE.md)、[ACCEPTANCE-RESULT.json](ACCEPTANCE-RESULT.json) 和 [NATURAL-RESULT.json](NATURAL-RESULT.json)；不据首轮结果外推长期多轮稳定性。
