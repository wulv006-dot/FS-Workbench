# 阶段二：受限代理、预算与背景接口

沿用PR108，没有新建任务。新增gateway.py、runtime_contract.py、background.py及两组测试。全部58项离线测试通过，0失败/错误/跳过；测试使用临时数据库、假provider/锁、合成聚合数据，没有真实网络或秘密。

## 本次实现

- ScopedTools从TaskStore核owner、RUNNING、lease、snapshot和截止时间，只转发五项固定MCP工具名至聚合EvidenceBook。
- ModelGateway在原持密钥进程中使用依赖注入接口：existing daily.db、provider_slot、daily_limit、provider及可信token上界计算器。没有默认生产路径、网络监听或凭据读取；请求不能指定model/endpoint/key/tools/stream，固定非流式工具对话候选。真正HTTP/SDK和Hermes兼容仍未接线。
- UnifiedBudget直接复用原model_calls表及四字段结构，在同一个DB新增hermes_reservations元数据表。调用记录/usage/价格版本/计算金额/回执只写原model_calls，不新建第二计费数据库。启动迁移只在测试fixture执行，生产尚未执行。
- 原provider_slot内BEGIN IMMEDIATE先写预算预留与started，再发provider；同owner/task/turn重放复用回执，换请求冲突；旧全局调用次数限制保留。每轮先按可信输入token上界和最大输出预留任务token、任务金额和Hermes日金额。单价为固定版本的整数micro-CNY/token，尚无正式生产费率/限额配置；不能把fixture价格当百炼报价。
- provider异常、缺usage、usage越界或不合格工具结果均转unknown并阻断后续试点支出。已知结果按真实usage结算；取消在途请求仍结算已发生用量，随后拒绝把结果作为成功任务继续使用。unknown没有自动清空/重试入口。
- 原模型日报次数限制仍统计所有model_calls；新增日金额上限仅统计Hermes调用，不宣称旧顾问费用已纳入货币预算。
- 同时8个相同请求只有一次假provider调用；另有假模型选平台工具→受限证据返回→第二轮模型的完整离线流程。后台业务无写操作。

## 运行时和停止边界

runtime_contract.py是惰性的FS隔离提案校验器，不冒充Hermes原生配置/可执行systemd单位；只返回launch_allowed=false。环境变量从固定白名单构造，不继承父进程密钥。固定源码、Python3.14、专用目录、无公网监听/外网出站、局部socket均等待批准和兼容验证。

截止时间和取消状态阻止新调用，不能中断一个已经阻塞的同步provider。因此“600秒实际停止”、进程监督、断电恢复和Linux权限仍是上线门槛；本阶段未宣称完成。输入token计算器也必须用固定模型的可信保守实现验证，不能用普通字符数冒充硬预算保证。超过预留仍会记录unknown并暂停，但真实provider是否严格遵守max_tokens必须接通后验证。

## 背景导入

主对话用户要求业务背景/画像/偏好，正式文档libfile_d2de6fdbc8d08191b3d0b91567c61ff9已完整读取（v1.0，243行，18904字节），但当前官方物化程序在Windows的os.setxattr处失败，目标本地文件不存在，未导入Hermes。身份/版本/实际失败见background-materialization.json。background.py只接收显式传入正文及FS审核元数据，不查聊天或文件。按UTF-8精确SHA、版本、来源导入，保留原版本；修改字节须重新审核。背景、任务状态和实时证据引用分区。背景权限为空、context_only；文中任何“授予权限”不会改FS策略。敏感令牌/密码模式拒绝；该检测不是完整PII脱敏保证，正式文档仍需人工审核。

## 最新接入意向与待确认

用户允许真实百炼API和后台读取，并愿意用wulv授权。该意向已收到，本次仍未读密码/会话/密钥，未新增身份或网络设置。可行方案是wulv在现有FS鉴权层授权任务，Hermes仅拿受控代理的脱敏结果。

现有query_api只支持GET /api/fs/v1/profiles和/statistics，项目白名单+过期哈希令牌；通配*仅为既有DY客户端，不能复用/扩成Hermes管理员身份。主源Admin/Order标注估算可复用，但该接口不是全部后台通用读权限。首批FC聚合适配不变；其它后台需逐个定义接口/字段/脱敏/审核，不向模型交管理员密码或Cookie。

待确认的完整动作见ACCESS-AND-RELEASE.md：专用无登录身份、限定任务局部代理访问、隔离运行时与局部网络约束、单任务/日金额和费率版本。真实模型调用意向不等于已执行这些持久配置。Portal不使用。

## 验证记录

命令：python -B -m unittest discover -s hermes_fc_pilot_20261013。58不同用例包含上一阶段29项。一次背景测试错误地在说明词query_for_values中查找子串value，已改成验证证据对象字段集合；另一次命令目录拼写错误未执行测试。最终完整58项通过，不隐藏上述调试过程。

捆绑包协作定位仅查看任务列表与其HANDOFF段，未发现直接负责人任务ID；可验证入口为PR95及docs/planning/fc27-pack-bundles-20261013/README.md。未改模块、未触发验收或旧任务。

背景入口采用简短文档引言和章节索引，按version/SHA读取详细章节，单章上限8000字节；不默认注入全文，不开放任意文件路径。真实文档尚未本地物化，58项测试仅含合成背景样本，不冒称正式导入验收。
