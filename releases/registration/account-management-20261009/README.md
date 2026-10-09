# 账号审批、模块权限与登录反馈

独立增量，Private Draft [PR42](https://github.com/wulv006-dot/FS-Workbench/pull/42)。管理员入口 /__auth/access/ → **账号与权限管理**。只处理新注册账号；现有员工、四管理员与各模块既有业务规则保留。未merge、未生产发布、未执行真实账号动作。

## 使用与合同

当前页勾选待审批账号，填写原因，批量批准全局只读或拒绝；已批准账号可批量撤销。每页最多50条，逐项沿用原审批接口、Origin/CSRF、申请版本CAS及审计。失败保留各项结果；401/403/429、网络或异常响应/5xx停止后续操作，未知结果先刷新查审计，不自动重放。

已批准账号展开**修改模块权限**，逐模块设置无访问或只读。经营分析、营销分析、运营周报、工作任务台、绿茵计划、FC运营看板、FC球员维护共七项；仅工作任务台与绿茵计划另可选**可编辑：仅本人任务**。编辑依照原执行人和字段保护，只维护自己的任务进度、执行信息；创建、删除、指派、结构修改和成员管理继续拒绝。读取仍受当前原路由合同约束，未接入消费者不会因本次获得访问。

权限保存沿用管理员/Origin/CSRF保护，校验申请版本与权限版本；原因和完整模块配置写入现有不可变审计账本。保存递增账号epoch并删除旧会话，账号需重新登录。首次保存将SQLite user_version由3提升至4，六张原表结构不变；新runtime支持3/4并核对原检查点，旧runtime拒绝4。数据库、审计、会话撤销和检查点不以代码回退恢复。

开户批准仍默认全局只读；未保存模块权限的已有注册账号保持原范围。权限依申请ID与注册UUID绑定，新申请不继承旧授权。管理员保存编辑权限后，前端通过原管理员成员API检查执行人：存在且active则保留；不存在则只登记viewer成员，以供任务分配；inactive不自动激活。权限已保存但登记失败明确显示部分完成，需人工核对。登记成员本身不会授予编辑权限。

登录错误密码显示“账号或密码错误，请检查后重试。”，就在表单附近并滚动到可见位置；保留输入、恢复按钮。网络错误另有反馈，原认证与限流保留。

## 验证与发布边界

从本目录重跑：

- node tests/test_actions.cjs
- python -B tests/test_ui.py
- python -I -B tests/test_permissions.py
- python -I -B tests/test_release.py

Node18断言、Windows隔离Chrome47检查、后台8场景、发布4场景已通过。后台使用真实增量runtime/SQLite、两独立进程竞争、真实临时taskboard HTTP处理器；只用合成身份与临时存储。Nginx检查是当前SHA匹配配置的静态合同检查，不是运行Nginx。Windows发布测试仅替代POSIX锁与目录fsync；Linux通过须查本次新head的CI。浏览器所有请求均拦截，生产账号动作0。

SOURCE-MAP.json对应八个活动文件；deploy/approved-manifest.json冻结八个目标、现场基线和七项保护SHA，releaseReady=false。发布沿用扩展的既有release_navigation.py，保留锁、备份、原子替换、逐文件CAS和独立读回；仅认证与taskboard重启，不改Nginx/systemd/政策/绿茵核心/经营HTML。deploy/candidate仅由上述八份source原字节复制，入stage前逐SHA核对，不上传完整原服务器源码。

首次权限保存后禁止回退旧认证代码；发布器检测schema4或权限事件即拒绝旧代码恢复，后续应采用兼容schema4的修复。发布窗口不进行账号权限保存，防止新代码尚未完整就被使用。GitHub新head检查、明确merge/受控发布批准、现场CAS及真实角色生命周期验收仍待完成。没有任何真实账号授权被工具执行。

source/web/base.css、source/runtime/route-contract.json和Nginx夹具仅是测试依赖；原冻结候选和历史证据保持。
