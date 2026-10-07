# 一次隔离增量QA入口

仅准备，尚未执行Linux/Nginx。复用根协调器已有、正式获准的非生产Linux QA及已审输入；不读取、复制或上传新的生产源码，不建workflow、不写Git或生产，不安装依赖。

薄载荷：`linux_delta_entry.py`、本动作卡、`overlay-manifest.json`。依赖既有已审输入根，入口先验证`review-input-manifest.json` SHA `722757c03619bd0bc2d33301782ee38f31d0d993243b9b7465b89c6fdba5f1ed`及其47项字节；21文件集合仍为`45254c1e33afc9481f45da65ea90ef14c88c560ac51c4852b2be3b377f2226a3`，恢复SHA `8d24b5c11179100b2cb8672dacc5d858596fe5d5b7b392ac76ebe234f573ff5e`。

执行环境必须已有Python3.9.18、SQLite3.53.4、Nginx1.26.1（包含auth_request/SSL及完整候选所需模块）、openssl。当前对话没有确认可调用的对应Linux执行器；已通过的GitHub43+4 workflow为固定用途，不修改或复跑它。任何依赖或已审QA输入缺失即停报，不自动构建、传源码或换执行渠道。

根协调器将下列变量绑定到**已有获准QA**中的真实路径后执行一次，限时120秒加自有子进程清理；变量只含路径。正式工具授权仍由执行入口处理，本动作卡不创建或代替授权。

```sh
LD_LIBRARY_PATH="$QA_SQLITE_LIB_DIR" "$QA_PY39" -I -B "$QA_OVERLAY/linux_delta_entry.py" \
  --reviewed-root "$QA_EXISTING_REVIEWED_ROOT" \
  --nginx "$QA_EXISTING_NGINX_1261" \
  --openssl "$QA_EXISTING_OPENSSL" \
  --output "$QA_WORKSPACE/registration-seamqa-receipt.json"
```

同次有限范围：真实Python子进程执行原字节caller main；缺store及insecure配置拒绝启动；全master＋10份include代入两个精确候选配置，经真实nginx -t后启动隔离Nginx；HTTP到固定HTTPS、新入口跳转、四admin/native editor/注册viewer、真实method/URI和user/role/groups覆盖、直接伪造头、readonly POST、旧FC cookie、敏感FC分析、真实verify503及跨恢复注销/撤销。原43+4及Windows7项套件不重复运行。

所有数据、成员、凭据、TLS证书均临时合成。三个服务使用父进程预绑定且验证归属的loopback socket；Nginx使用独立loopback端口，日志/pid/temp/web及TLS路径映射到自有临时目录，非目标上游映射到阻断端口。固定runtime/policy路径及global verifier端口由QA加载器映射，源码字节保持不变；headers观察器仅记录合成user/role/groups/method/URI/status，绝不记录Cookie或body。全部自有子进程结束后删除临时合成数据，只保留去凭据JSON收据。

验收是此精确输入在现有QA中的新接线及认证往返。生产systemd实际loader、UID/ACL、正式TLS、合法真实角色、fresh CAS与唯一发布锁仍须现场证据。Nginx解析使用完整配置的QA环境映射，不能声称生产原路径已原生解析或服务已上线。

恢复候选关闭`access/api/*`为503，保留当前DB/witness及verify；旧native登录入口按已审范围保留，不能宣称所有登录停发。运行失败保留失败收据，不自动重跑、修库或恢复旧DB/witness。此前被拒绝/取消的服务器QA上传保持禁止，本次没有上传请求。
