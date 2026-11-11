# 订单用户邮箱筛选导出（施工中）

## 目标与负责人

负责人：DSH lead。独立分支 `dsh/order-email-export-20261111`，工作区 `D:/FS/DSH-worktrees/order-email-export-20261111`，起点 `origin/main` 为 `3efb92c60cfcc5b9b70496b58cbd18893e3c8ce6`。本任务增加数据分析工具的名单导出，不发送邮件，不修改定价、订单或成员权限。

用户目标：按 Admin 订单管理页条件选择站点、多个游戏、日期以及其他筛选项；自动跨月拼接订单，提取用户邮箱、去重、导出。典型验收为本年 FC26 + FC27 联合名单，同邮箱只出现一次。

## 范围与待核事实

截图筛选项：订单进度、订单状态、订单站点、产品类型、游戏/服务器/产品、游戏、服务区、推广人ID、折扣码、促销活动ID、商品ID、操作人、下单时间、国家；原页面还有订单集合标签和模糊搜索。必须核真实请求字段与取值，不凭中文标签猜协议。

当前实时订单调用合同为 `releases/fs-dashboard/tiered-data-access-20261101/LIVE-ORDER-PAGINATION.md`，现有源仅允许站点266、单游戏、付款时间、精确用户邮箱；28天/20条分页/365天边界、private权限及共享在途限制保持。不能把旧通道当作截图全部条件已支持，不能把付款时间冒充下单时间，也不能直接放开worker固定站点检查。

候选前端入口为 `releases/fs-dashboard/hermes-data-workspace-20261018/frontend/tools-page/page.js` 及同级页面，实际挂载 `../data-workspace.js` 的不可变资产版本。旧 prepare_release.py 固定历史CAS，不得重放为新发布。活动路由、当前源码SHA及publisher清单待服务器读回确认。

## 正确性约束

- 邮箱只取订单用户邮箱，不以支付邮箱补缺。去空格、按大小写无关键去重，保留可用原邮箱；不作 Gmail 点号/加号等供应商归一化。
- 输入和导出只在原真实登录/private/站点对象权限中使用，不建立固定管理员身份或额外名单权限。
- 在源限制内串行取全部分片和分页，遇源变化、错误、限额或中断，明确未完成，不提供冒充完整的名单。实时非快照限制须可见。
- 全年导出可能远超单HTTP时限；不能用短总时限+无续读的方案声称全年场景已验收。评估复用已有任务/续页机制，避免并发轰炸共享Admin通道。
- CSV包含单列email，正确转义并防电子表格公式注入；不要记录邮箱正文或将邮箱放浏览器URL。
- 订单邮箱不证明营销订阅许可；发送阶段由现有邮件营销系统处理退订及禁止营销名单，不在本任务自动发送。

## 当前阻碍与下一步

Remote Workspace 已成功连接已存187机器，但本会话是 LOCAL，rw_exec 明确拒绝读取，不允许回退到其他会话的active machine；rw_pick_workspace 指定 `/root` 后仍要求在对应远程镜像工作区另开会话。镜像为 `C:/Users/Administrator/.dsh/remote-workspaces/47.85.224.112-root-22/root`。未切原始SSH、浏览器登录或Cookie以绕过此拒绝。

需在该远程工作区会话只读核：当前nginx数据工具/实时订单路由；活动range_api与user_runtime的真实身份/private检查；Admin订单筛选元数据、站点/游戏目录和请求字段；当前源页面分页结构及时间语义。只回传脱敏协议/源码位置，不输出凭据或客户名单。随后补齐接口、UI、测试、PR/CI，再按具体授权发布与真实入口验收。

CodeGraph MCP已调用，本任务无索引，服务要求本会话使用源码检索、不再重复查询；未伪报调用图。基础实现已由子代理交接，lead已读collector及HTTP差异并独立复跑回归；不代表真实上游协议或生产可用。

## 本地阶段结果（2026-11-11）

- 新增 `releases/fs-dashboard/tiered-data-access-20261101/source/admin_order_email_export.py` 及 `tests/test_admin_order_email_export.py`，候选 `releases/fs-dashboard/management-november-20261103/source/range_api.py` 增加 POST `/users/order-email-export`。尚无生产nginx映射或发布清单验证，前端未接入。
- JSON请求为 `{site_id,game_ids,start,end_exclusive,filters?:{}}`；非空filters明确422，仍仅原配置site266/private/游戏权限，时间为付款时间。只取customer_email，不取支付邮箱；结果trim/casefold去重，不落服务器磁盘。每页复核会话、使用原共享池。
- 当前45秒、1000页、约1MiB响应预算；超限/失败均无emails且complete:false。尚无续跑，因此不满足大规模全年导出的验收。
- lead在共享Python3.9独立执行 `python -m unittest discover -s releases/fs-dashboard/tiered-data-access-20261101/tests -v`：169 tests，1.221s，OK，包含9项新增测试。仅本机fixture/HTTP AST测试，不证明生产取数或183兼容。
- 自动续轮3：rw_info仍确认同一LOCAL未绑定状态、连接和Ping正常。同一阻碍持续三轮，自动目标转blocked，不继续重复空转。恢复入口：在Remote Workspace打开187的/root远程工作区会话，按本记录只读核对真实Admin筛选元数据和当前路由/活动源码，把脱敏协议证据带回本任务；本地实现仍保留当前独立worktree/分支，不迁移或覆盖其他任务。不能把基础后端、171项本地测试或本记录当完整交付。
- 自动续轮2：rw_info确认187连接/Ping正常，但本会话仍LOCAL、没有remote workspace绑定（未尝试绕过）。补严格日期round-trip校验，防止不同Python版本把YYYYMMDD或周日期静默转换；新增相应无取数拒绝断言，171 tests/1.263s/OK，git diff --check通过。真实筛选、活动路由/发布源、183验证均仍缺远程证据；没有提交/PR/部署。
- 自动续轮1：去重键仍trim/casefold，但导出保留首个邮箱原拼写，避免不必要改写；补跨游戏/跨窗口合并、响应字节上限及中途撤权不泄漏结果测试。lead复跑171 tests/1.189s/OK，git diff --check通过。远程会话阻碍未解除，未重试被拒操作，尚未实现全年续跑或真实广筛选。
- 已移除未接入的重复草稿 `order_email_export.py`，避免与真正候选模块混淆。未提交、未提PR、未合并、未部署；保持施工中，等待远程协议核验。

## 本轮继续：CSV与预算（2026-11-11）

- 返回前增加完整JSON封装字节预算（含Unicode转义及scope/统计元数据），超限不返回邮箱。新增对应回归；本机Python3.9全套172项测试通过（1.207s）。
- 新增独立前端序列化模块 `releases/fs-dashboard/hermes-data-workspace-20261018/frontend/order-email-csv.js` 与7项Node测试：仅接受完整user_email响应；单列email、UTF-8 BOM、CRLF、引号转义和公式前缀防护；不读取支付邮箱，不丢弃条目，不用JS lower-case近似Python casefold。lead读回源码并独立复跑7项通过。
- 两套新测试接入 `tools/pr_fast.py` 原有tiered-data-access/hermes-data-workspace分组；selfcheck通过。编辑工具曾把原混合换行整体改为CRLF，已按HEAD原始字节保留原换行并验证只有2增1删；CRLF-aware diff --check通过。没有隐藏测试失败或业务变更。
- CSV模块尚未接到查询页面/下载按钮；仅模块测试，不是浏览器或Excel真实验收。仍缺真实广筛选、下单日期协议、站点/游戏目录与活动路由核对，以及大名单续跑。尚未提交本任务PR或部署。
- 另一个独立任务的受限发布脚本草稿PR989已建且CI绿，不支持数据工具发布，不解决本任务远程读协议问题，不算本功能交付。

## 筛选下载组件读回（2026-11-11，续轮5）

- 新增独立 `frontend/order-email-panel.js`：明确由宿主提供同源endpoint与真实站点/游戏目录，不猜生产路由、不填假ID、不自动挂载；当前仅付款日期/站点/多选游戏。开始/含当天结束日期严格校验并转UTC exclusive边界。
- 查询为同源JSON POST；完整响应的期间及scope须与本次请求一致才允许下载。条件变化、取消、dispose都中止请求并清除名单/Blob URL；旧请求和旧JSON解析完成不能覆盖新条件。无邮箱预览、无持久化、无自动发信，显示退订/拒收提示和CSV公式前缀处理说明。
- lead完整读回两模块及测试，独立执行Node：CSV7项＋组件7项=14项通过（此前子代理所称14项为两套合计）；组件模拟DOM，并非真实浏览器验收。本机无可直接resolve的Playwright，不把模拟测试当视觉/主题验证。
- Python全套172项/1.182s/OK，pr-fast selfcheck、CRLF-aware diff --check通过，pr-fast仅3增1删。组件测试已接入现有CI分组。
- 真实页面尚未挂载，未获生产协议/目录/路由证据；全年大名单续跑、Admin广筛选、183Linux和生产入口仍待完成。准备将当前最小候选提交草稿PR追踪，不等同可合并或已交付。

## 业务及生产验收（均待执行，本地测试结果见上）

1. 真实站点与多选游戏目录、截图筛选语义一致。
2. 年初至当前的FC26+FC27跨窗分页，跨月/跨游戏重复邮箱只保留一次；空邮箱单独计数。
3. 时间边界、闰日、非法筛选、未知条件拒绝，不能静默忽略。
4. 原private及多角色/站点权限隔离，撤权中断，原共享并发限制保持。
5. 源超时/变化/页预算/响应上限不伪完成；大名单可按既有机制继续完成，而非每次重新从头超时。
6. CSV格式/公式防护、筛选变更清除旧结果、取消与失败状态、浅暗主题。
7. 相关Windows与183隔离Linux测试、main必需CI、PR、合并、部署及真实入口分别记录；当前均不声称完成。
