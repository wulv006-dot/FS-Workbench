# FC27 周更审阅与发布闭环

2026-11-09 用户要求：自动取品、三页草稿预览、人工修改、明确确认发布及工作单记录在原 FS 运营台串联；真实发布等待本人确认。

## 实现设计

沿原 weekly pipeline 保存草稿后，服务端按运行原 ID / 上海 ISO 周自动关联三页工作单。重复回执恢复不重复建单，同周多次运行保留历史。原活动中心仍是草稿、发布及版本的唯一来源。

运营台直接提供三页私有整页预览；同源嵌入原 products 编辑器，保存后更新预览及工作单版本。嵌入模式不提供独立发布按钮。消息校验来源、窗口、运行 ID，未保存修改不能被后台刷新覆盖。

审阅接口冻结当前已保存 revision、草稿摘要、交易策略差异和到期时间，返回可发布状态。确认按钮仅向原会话下的管理员开放，绑定本次审阅摘要。修改或策略变化使旧审阅失效。新模型交易映射使用原 Admin 字段合同生成候选，预览不安装；真人确认时才沿原 publisher 锁、CAS、私有备份和回执安装候选，再调用原 center.publish。优惠码保持 FCSCOUT10 / Discount6049 / FC27 Items，不写券或改变折扣。

发布沿原 operationId 恢复，先查原 center 回执，再考虑新写入；真实公开配置读回匹配后自动回填三张工作单。工作单已批准、已发布读回不代表支付或自然周期验证。无模型、来源或新模型映射时说明具体缺口，不伪价、不伪成功。

## 施工计划

- [x] weekly-store 自动 run / draft / publication 关联，pipeline 原保存与恢复回调；保留人工工作单兼容。
- [x] weekly-commerce 私有候选、预览价格、精确三平台原生映射及原 publisher 安装适配；保持有界目录与批次。
- [x] weekly-workflow 审阅 / 明确确认发布 / 原 ID 恢复；原 HTTP 权限、Origin、CSRF 和 center 事务保护不变。
- [x] weekly UI 三页预览、同页原编辑器、确认/取消、超时恢复、自动工作单；补录移到次要入口。
- [ ] 相关单测、HTTP 和真实浏览器验证，正式 CI/PR/main，沿原发布器部署代码并读回；本轮不替用户点击真实活动发布。

## 验收重点

自动与人工触发保存均自动建单；同周重复不丢历史。预览和刷新不发布、不写生产策略。编辑保存后版本与预览同步，旧确认不可用。管理员明确确认才安装已审核交易映射及发布；失败可按原 ID 恢复，不重复安装或发布。回执绑定原运行、三单、草稿及实际公开 release/config hash。深浅色、窄屏、键盘、只读、加载、空、失败状态保留。

## 当前状态

代码实现及相关离线验证完成，正式 CI / 合并 / 部署 / 真实入口分别待记录。183 使用现有 fs-fc-camoufox 镜像，1 CPU / 1GB / 无网络 / 只读源码 / 无业务卷与端口，Node 83 项通过；Python 初包缺三份仓库夹具，补齐后原完整 253 项通过，未修改或跳过断言。Windows 运营台浏览器 23 项及原编辑器完整浏览器集成通过，覆盖深浅色与窄屏。发布到公开指针后中断、旧回执在新草稿/新运行之后恢复、慢请求跨发布临界区均有直接回归。

线上只读基线：草稿25（原运行 4c09cd43-d93b-4223-8e93-f5905e6aaac3），公开 campaign-preview-24；本轮不替用户发布草稿25、不重派模型、不改券或周日计划。首次自然周更与实际支付仍独立待验。

## 当前来源与精确接线

维护源为 releases/fs-dashboard/campaign-analytics-20261023。app/analytics 下 weekly-store / weekly-pipeline / weekly-workflow / weekly-commerce / weekly-commerce-install.py / production-server / center-store 对应 /opt/fs-campaign-dashboard/analytics 同名目标；weekly 与 products 的 HTML/JS/CSS 仍由原管理服务提供。app/runtime/model-options.mjs 对应原 runtime 同名目标；backend/bridge.py 对应原 backend/bridge.py。没有增加外网服务、数据库、定时器或第二个发布器。源码部署沿原 traffic-source-tabs publisher 的精确目标、CAS、保护清单、备份及恢复适配。

价格策略总量与模型合同同为有界300，原每次 backend batch 最多100，旧 Halloween / 其他游戏合同保留；目录1000商品与3000绑定上限保留。超过上限明确阻塞，不能删除旧策略或伪装完成。新候选预览价格优先于同组合旧缓存，但预览始终关闭购买。

当前任务工作树未建立 .codegraph 索引且无 graphify-scope.json，未从另一个旧分支索引推断本轮来源。新增服务模块仍在上述原管理服务和既有发布入口内维护，不迁移源码或新增发布入口。
