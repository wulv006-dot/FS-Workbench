# 账号管理与模块权限增量

管理员wulv入口：/__auth/access/ → **账号与权限管理**。支持新注册账号批量批准全局只读、拒绝、撤销；已批准账号可逐模块调整无访问/只读，工作任务台和绿茵计划可开启本人任务编辑。现有员工及管理员角色保持。

登录错误密码增加就地中文反馈。权限保存有双版本CAS、审计与旧会话撤销；可编辑只沿用原任务执行权限，不开放新增、删除、指派、成员管理。执行人登记只写viewer投影，失败明确显示部分完成。所有操作未知结果停止、不自动重试。

本地[源码与完整合同](../../../releases/registration/account-management-20261009/README.md)、[八文件映射](../../../releases/registration/account-management-20261009/SOURCE-MAP.json)、[受控发布清单](../../../releases/registration/account-management-20261009/deploy/approved-manifest.json)。原目录、冻结manifest和历史验收保持；本地索引已更新。

本次实测Node18、Windows隔离Chrome47、后台8场景、发布回退4场景通过。包含两独立进程竞争、真实临时HTTP任务处理器、跨模块/跨账号拒绝、旧会话失效和旧runtime回退拒绝。Nginx为现场SHA匹配配置静态检查；真实Nginx/线上角色和生产生命周期尚未验收。

Private [Draft PR42](https://github.com/wulv006-dot/FS-Workbench/pull/42)沿用同一候选，不新建PR。旧前端head9c920bb…的CI37883363438成功属于历史输入；本次权限新head必须单独验。新现场SHA证据时间2026-10-09 05:42:25 UTC（北京时间13:42:25），两个服务active；无内部源码导出、原QA重试或生产账号写入。

首次模块权限保存后user_version=4，旧认证runtime拒绝启动；发布器也禁止把它回退成旧runtime。数据库/检查点/审计从不跟随代码恢复。merge、八文件受控发布和真实角色验收分别记录；当前releaseReady=false、未merge、未上线。
