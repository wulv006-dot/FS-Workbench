# 第二包：受限查询规范化与纯planner

独立文件：source/query_contract.py、query_planner.py、schema/query-v2.json、tests/test_query_planner.py。没有修改共享range_api或T3执行链。

normalize只接受已声明字段、显式日期/site/game和dataset白名单。filters、fields排序后统一生成filter_hash，规划与未来cache必须使用该规范化结果；此hash不是包含身份/permission_epoch/watermark的完整缓存key。
plan只在可信capability、verified source profile和服务端budgets齐备后规划。原生summary保持完整需求窗；detail按profile片长拆分，全部片保留scope/fields/filters/date_semantics。archive/frozen不计划网络。游标恢复必须先经宿主验证；未经验证的cursor拒绝。缺日期、SQL/URL注入、跨scope、未知字段、预算不足均不产生源计划。planner内部planned/local状态不作为QueryResult执行状态；预计页数未知用null，不能以分片数量冒充完整分页请求数。

新增6项fixture测试通过（独立包现14项）；源执行器、schema validator集成、分页total/watermark验证、singleflight/queryjob尚未实现。schema是结构合同，dataset权限/字段/范围由同一运行时入口强制，不能仅凭JSON schema通过就执行。没有真实源可再生证明。

## 索引成本补充

synthetic-only benchmark_version_index.py，1万条当前+1万条旧版本、单个旧revision JSON：baseline DB3,526,656字节→索引后逻辑DB6,557,696字节，新增3,031,040字节；commit后WAL3,102,392字节；Python heap峰值8,390,260字节；一次耗时0.386秒。RSS/锁等待unknown。这说明候选索引需要额外空间；不是清理或节省存储的证据。默认关闭，生产迁移未许可/未执行；大revision JSON仍需进一步治理。

## Linux验证与现场盘点阻碍

本机PATH无docker/podman；Docker默认CLI路径不存在；WSL -l只返回安装帮助，当前用户Lxss无发行版记录。未安装软件、启用系统功能、修改权限或网络。当前没有已验证可用的本机Linux执行入口。
需要父协调提供一个现有获准Linux测试入口（可执行命令/容器名及工作目录），在隔离checkout运行用户分析相关175项及新包测试；Windows137errors不代表逻辑通过。不在生产服务容器跑开发回归。

当前用户没有OpenSSH config，也无FS_*SSH/HOST或SSH_*环境变量；已查看现有user analytics探针和ops回执目录，未找到可沿用连接身份。未读取私钥/密码或尝试猜测登录。最小缺口：187既有获准连接profile/调用脚本的准确路径及身份，允许仅运行本包metadata清单与指定引用核查；不得新建凭据或更改SSH配置。此前24.26GB数字仍是历史报告，未现场盘点。

## 交给T3 A协调的边界

仅请求现有range宿主提供：trusted identity→authorize(dataset,requested_scope,mode)返回真实grant，resolve(grant,...)返回经过授权过滤的capability；调用normalize/plan后按原会话/锁调固定adapter。接口不接受调用者URL/SQL/root，不让客户端提高budgets。
先约接口后由owner修改range_api；当前没有待自动应用的共享源patch。数据job恢复限定同scope/policy/watermark，与材料Agent恢复无关。
