# 页面原生带码与发布目标补齐59

本轮只修两项已确认漏接：受控发布器缺少本项目provider目标、已证带码合同未进入实际页面。生产仍为RELEASE42；合并不等于发布，正式码、购物车和Apply现场验证另批。对外Library包按用户要求冻结。

## 发布目标

`publish.py`仅在原`BACKEND_FILES`集合登记`campaign_backend/provider.py`，目标为`/opt/fs-campaign-dashboard/backend/campaign_backend/provider.py`。没有添加目录通配、关闭CAS或改变鉴权。`test_publish.py`用实际provider源码字节经原inspect/validate/guards/target链验证可接受，同时验证基线漂移、伪造目标、其他backend文件及路径逃逸仍拒绝。

原发布流程仍执行`nginx -t`、daemon-reload、两个活动Node服务enable/restart/is-active及`nginx reload`。两个Node需重载本次模块/内存静态资源；本次未改Nginx配置，单从这两个代码变化看不需要新的路由生效，但原公共发布器固定执行reload。本轮没有更改或执行该公共流程；后续生产审批应披露reload影响，而非隐藏或绕过。

## 验收边界

| 用户入口 | 实际调用点 | 数据与状态 | 本地证据 |
|---|---|---|---|
| FC三页 Review → Submit | activity.js → publishedPlan → host native batch → checkoutPublished | 真实本地center发布/公开runtime；原生加购与Cart Apply为隔离模拟 | Weekly、SBC、Trio按钮走通；Apply接受/拒绝分开，未宣称主站实联 |
| Seasonal FC固定卡 → Buy Now → 平台/区服选择 | event.js/runtime-bridge → 同一native合同与host | 仅已证PS1000K编码；测试商品/码为合成 | new_gold/id163329311/group1000/num1，未开放其他未证组合 |
| 配置撤回/来源不符/旧码冲突 | 点击前重读公开配置、范围校验及持久操作记录 | 缺省unconfigured，原生POST之前拒绝 | 旧码不覆盖且不创建未知占用；跨origin不传码 |
| 部分加购/响应未知/再次点击或刷新 | 原批次回执 → 原操作记录 | 确认行保留，未知不盲重放 | 不写pending码、不导航、不再次发加购 |
| 发布provider与公开脚本 | 原publisher目标/CAS、prepare生成静态清单 | 实际源码字节＋隔离目标根目录 | provider精确目标接受；额外目标与漂移拒绝；带码脚本实际进入清单 |
| products同页素材＋模型＋优惠引用＋标题 | 本地编辑状态 → center preview → 原renderer | 真实本地管理HTTP，Admin模型来源为合成隔离fixture | 未保存整页预览含图片加载与平台关联；正式current/history不变 |
| products一次发布 | 完整draft/model_imports → 单次center publish | 原鉴权、CAS、版本和原操作ID | 一次发布；丢响应恢复同ID；CAS失败不部分写；没有先存半份草稿 |

带码能力从现有私有backend/policy.json的独立native_checkout字段，经center发布进入受控snapshot；普通运营草稿不能自我授权。该字段包含精确页面/商品/数量/属性/码、核验证据和有效窗，缺省不配置；本轮没有在生产写该字段。引用价格不授予购买权限。FC截止时刻按用户要求包含，超过截止拒绝。

统一整页编辑/预览/发布与本轮共用原products入口。选模型只改本地待保存状态；上传素材仍是未发布隔离资产，统一操作时校验英文确认并绑定。预览用鉴权、同用户、10分钟有效的内存令牌复用原页面renderer，禁止购买；没有新增平行编辑器。一次发布直接接收完整候选，校验通过后原子发布，不要求用户逐区保存或先存草稿。普通优惠引用仍按现有字段配置，不把私有native运行授权做成普通草稿开关。

通用商品选入也仅保留待提交引用，由服务端在统一操作时重读并核对；万圣节不再有独立确认阶段，只有实际改动的控件才更新对应字段。旧配置缺省、已核完整商品池标志和未编辑概率顺序保留。旧逐项API仅留历史兼容，不由新版界面调用。

原Q发现并定点修复三项：响应头后正文挂起的超时覆盖；未编辑万圣节字段的原形保持；旧省略字段的预览/发布投影一致。相应用例均为隔离测试，没有生产读写。浏览器证据入口为`app/tests/native-page59-browser.cjs`和`app/tests/products-page-flow-browser.cjs`，均已加入原pr-fast；旧模型/素材、草稿兼容和搜索错误分类按新统一操作语义回归，保留实质断言。

页面链路证据必须来自实际公开运行服务和页面按钮，只有原生端点与Cart Apply使用隔离合成响应。不允许以直接调用导出函数替代页面验收，也不允许用mock Apply成功声称主站已经生效。正式业务配置维持未配置，源码不得附私有Admin响应、会话或用户购物车记录。

最终提交、相关测试、原Q与精确head CI记录由本任务最终回执补充；本文件不作为已完成现场验收声明。
