# 注册权限候选源码导入

状态：独立审核候选，releaseReady=false。本次只提交已确认的20项，不替换仓库现有规范源。

formal/三份caller与recovery/恢复源码、review-diffs/七份差异、tests/下Linux薄载荷保持已审原字节。test_release_delta.py只调整仓库相对路径；config/三份example为必要接线片段和占位模板，不能直接作为生产配置。候选源码中的已审固定运行路径与origin保持不变。

依赖复用main已有registration_approval_runtime_v3_20261006/，不重复导入15份runtime。基线commit/tree和逐文件SHA-256见candidate-manifest.json。

凭据核对：门户AUTH_SECRET仅由环境读取，无字面量默认凭据。疑似硬编码值位于selftest合成样例，不是部署凭据；测试中的密码与Cookie也为合成夹具。此说明不列出凭据值。密码、真实Cookie/密钥/账号数据库/经营数据、live-config和完整现场配置不在导入清单。

本地最小回归（Windows，合成输入、无监听socket）从仓库根执行：

```powershell
python -B -m unittest discover -s tests/registration-import-20261007 -p test_release_delta.py -v
```

7项覆盖caller启动拒绝、旧FC身份入口退役、任务台伪造身份拒绝、四管理员/native editor/注册viewer及恢复后的注销/撤销拒绝。此结果不代表Linux、真实角色或生产验收。

linux_delta_entry.py、EXECUTE.md和overlay-manifest.json保留原薄载荷及历史状态。其Linux入口要求已有获准QA中的完整47项已审输入；本导入刻意不包含live-config，不能把本仓20项当成那个完整输入根。缺环境或输入先报告，不改旧manifest、绕过既有上传拒绝或启用新workflow。

交给老D：按candidate-manifest.json核对字节，先审正式caller/恢复边界与三份模板，再沿现有合法QA路径验证接线。GitHub候选入库、合并及生产发布分别记录；本次授权仅为独立分支入库。共享入口由吴律主导、陈超参与，FC归吴律；本提交不替代业务owner确认。
