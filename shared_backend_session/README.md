# FS 全局后台会话客户端

当前维护源，替代 `sales_shared_session_20261021/` 的一次性迁移、登录探测和补丁生成脚本。当前OCR登录合同及来源见 [OCR-SESSION.md](OCR-SESSION.md) 和 [OCR-SOURCE.json](OCR-SOURCE.json)。

| 维护源 | 活动路径 |
|---|---|
| shared_admin.py | /opt/fs-shared-session/shared_admin.py；Sales collector 同名模块 |
| manual_captcha.py | 8767镜像 /usr/local/bin/manual_captcha.py；保留文件名兼容，实际为OCR识别 |
| sales_auth.py | /opt/sales-dashboard/collector/p2pah_auth.py |
| sales_collection.py | /opt/sales-dashboard/collector/fetch_all.py；发货页失败只重试原页，仍失败整轮不发布 |
| sbc_admin.py | /opt/fc27-sbc-tool/admin_client.py |
| fc27_sbc_fix_20261015/source/webapp.py（本地） | /opt/fc27-sbc-tool/webapp.py；私库规范文件沿用 releases/fc-sbc/security-20261015/source/webapp.py |

Admin只读取8767；Order由独立的全局8768服务与受限socket提供。客户端不接收账号密码/验证码，不落盘缓存会话，也不回退独立登录。FS用户登录及业务权限校验保持。

SBC上传签名密钥从服务器 `/etc/fc27-sbc-tool/upload-signing.key` 延迟读取（root、0600），未复制到本地或Git。只读请求无需读取该密钥。8767全局凭据配置仍仅在服务器。

检查：`python -m unittest discover -s shared_backend_session -p 'test_*.py' -v`。这些是离线回归；真实读取、同步作业及部署结果见 `docs/planning/sales-shared-session-20261021/CLEANUP.md`。不保留一次性部署器，不以模板覆盖生产源；按当前HOTFIX、现场SHA/CAS及空闲状态发布。

既有授权的OCR图片验证码识别→账号登录→身份核验→获取及续期共享凭证，是8767需要保留的自动化操作流；人工Google动态码回退不替代图片OCR。离线行为回归和来源哈希校验阻止规范源回退为人工等待。当前树不再提供固定历史人工镜像的一次性会话迁移发布器；本次同步不发布、不重登、不重启。
