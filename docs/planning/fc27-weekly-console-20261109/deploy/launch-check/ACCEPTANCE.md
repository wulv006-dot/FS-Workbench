# 三页发布检查验收

## 源码/隔离验收

本节记录2026-11-09本轮组合包与隔离测试证据。候选部署范围见[发布清单](README.md)，不把源码、本地测试或隔离测试通过写成生产生效。

### 固定组合范围与调用链

用户选择“先同步现有4个固定组合”，不扩为Packs类目下全部15个当前在架模型。187只读核对当前FS已选组合及三平台真实商品映射，范围如下；这些ID是本次观察，不是永久白名单。

| 当前组合 | 模型ID |
|---|---|
| LALIGA EA SPORTS Player Bundle | 44839987 |
| Lyon Women Player Bundle | 44839989 |
| Barcelona Player Bundle | 44839991 |
| Premier League Player Bundle | 44839993 |

每轮从当前 `fc_layout.bundles` 派生范围：已存模型取model_id，旧卡沿真实PS goods引用精确核对goods→model，再读取当前在架状态与三平台身份。后续人工改选会进入下一轮，不按名字推断、不替换成其他Pack。周更草稿为三页保存同源组合引用和bundle角色，SBC公开投影使用自身页面范围；组合不混入Scout前三、Trio三名或SBC九核心/十八搭档的24行模型结果。三页商业提案仍要求真实报价及逐页、逐平台原生绑定，统一FCSCOUT10/Discount6049、仅FC27 Items，保留其他游戏及旧策略。

本地 `tests/native-model-browser.test.cjs` 通过：导入模型形态的固定包在三页×PS/Xbox/PC共九组中，独立审阅仅包含该包，点击确认后提交精确 `new_items` 商品ID、平台aid、group/num，并带FCSCOUT10；未批准的SBC/PC绑定仍不可购买。同时修复了固定包误用球员选择事件，以及独立包审阅被主球员集合为空挡住的问题。`native-page59-browser.cjs`、`products-page-flow-browser.cjs`、`fc-english-only-browser.cjs`及相关追踪/阶段合同回归通过。全部为隔离或模拟交易，未据此宣称真实加购、优惠核销或付款成功；后续展示变更仍由总控执行受影响浏览器回归。

### 183 Linux核心验收

使用现有镜像 `fs-fc-camoufox:20261103`，镜像ID为 `sha256:296ee057ce1c5f75de95703f690e1076728207ebaa4501d629437582fc4ee876`。环境为Python3.12.3、Node24.18.1、镜像既有zoneinfo；限制1CPU/1GiB、network none、源码只读挂载、只读根文件系统、无主机端口映射，测试临时写入仅在隔离目录和容器tmpfs。没有操作RPG、生产服务、真实模型或业务配置。

| 检查 | 结果 | 跳过 |
|---|---:|---:|
| `backend/tests/test_weekly_selection.py` | 15通过 | 0 |
| `backend/tests/test_discount_revenue.py` | 9通过 | 0 |
| Node：weekly-pipeline、weekly-commerce、model-media、page-catalog、runtime presentation及discount-revenue | 69通过 | 0 |

首次Node装配漏带原有 `seasonal/model-selection.js`，启动失败证据保留。补齐这一既有依赖后，只重跑Node组，69项全部通过；原83个源码文件字节未变，未通过修改断言或业务代码消除失败。Python两组已通过的结果复用。

证据位置：

- 183 Python原日志及首次装配失败：`/opt/fs-isolated-tests/fc27-bundle-revenue-20261109-02/results/`。
- 183补齐依赖后的Node结果：`/opt/fs-isolated-tests/fc27-bundle-revenue-20261109-03/results/`。
- 本地汇总及源码摘要：`.agent_runtime/weekly-console/bundle-revenue-linux-stage/acceptance-summary.json`、`source-manifest.json`。
- 原工具限定目录内的下载日志：`E:/WorkBuddy/大超服务器/.agent_runtime/weekly-console/bundle-revenue-linux-results/`。

下载后与当前源逐文件比较，变化仅为另由UI任务继续调整的activity.js、activity-content.js和activity.css；上述后端及Node核心源码未漂移，Linux核心证据可复用，不替代最新展示的浏览器验收。

### 正式CI与旧测试合同修正

CI1847暴露两条旧合同：canonical-editor仍只预期三个球员平台引用；activity-bundle-scope仍硬编码只有Weekly/Trio的选择分支。已核实际21个FC引用准确等于该fixture的一个候选Player×三平台，加原FS已配六个Bundle×三平台，成员唯一，无重复或目录扩散。测试改为完整21成员加唯一新导入项的精确数组断言，并逐页核共享组合成员；范围测试执行实际selector/scoped及公开投影，覆盖三页×三平台、未绑定变体/其他页/未知商品不泄漏，以及显式空SBC范围不借用Trio。仅改这两个测试文件，本地六项全部通过，未放宽业务校验。

CI1848的425项Node检查通过，但weekly-console浏览器用例因popup通知/close时序失败，不能记为整次CI通过。随后只修测试等待close的时序，相关23 checks连续三次通过。CI1849已通过该用例，但products-page-flow仍等待客户页已隐藏的映射文字，原30秒超时；已准确改验PS/PC商品身份及内部信息不可见，未提高超时、删除交易校验或修改生产源码。相应七个浏览器脚本及两项原生模型测试通过。

最终正式CI1850 / run42626190019 **success**，PR960成功合并，main `bbaab74262161808b44f7ff88da67ab80e379331`。最新21个生产源码逐一与固定候选SHA匹配，测试后未再修改生产代码。

生产部署、公开页面、新正式追踪及本轮业务新绑定的发布/真实入口验收，均由总控取得实际回执后另行补充。本节不将先前版本27的交易证据复述为本轮新验收；旧证据仅按其原范围参见[既有独立编辑流程验收](../paged-workflow/ACCEPTANCE.md)及[既有商业接入验收](../commerce/ACCEPTANCE.md)。

## 尚未部署：自动审批要求最终批准

2026-11-09 13:35 UTC准备执行原publisher的23目标apply，自动审批在创建进程前拒绝，动作没有运行。理由：该批会写入生产公开页面并开启追踪，审核认为缺少对整批实际写入的最终明确批准，且原任务要求真实发布/生产配置变更等待人工批准。未重试、拆成单独开关、另用脚本或换发布方式绕过。

独立侧栏18目标原publisher最终inspect仍通过，mutations=false；同样保留候选、待整批确认。没有将菜单候选、代码合并或HTTP200称为已上线。当前业务版本27、新24条组合包绑定与追踪Capture验收的状态见[具体待批准清单](APPROVAL-SCOPE.md)。

13:39:37 UTC只读读回：23/23部署前SHA匹配；三服务active，center/public27、原配置/规则/policy SHA及发布操作 `e2bb13b1-e20c-4d61-a782-c2f771d50f90` 保持；正式enabled=false，追踪登记11/布局摘要正确。缓存ready78；Scout每平台3/3、SBC每平台27/27有fresh USD，Trio每平台7个选项中仅3球员有价，4个legacy包缺价，未将其算作全覆盖。证据 `.agent_runtime/weekly-console/launch-live-readback.json`。

补查发现旧4包seed仅有site/game/goods引用，不满足现代model_card_key的报价及snapshot投影合同。撤回“只fresh review即可完整可售”的早先推断；实际执行清单须先用原model_imports/save将同4包变为真实模型，再沿原review/publish，不能只看policy候选绑定数。相关真实旧形状回归另记结果，当前不宣称新版生产已修复。

### 旧四包转换：原接口完整回归

新增weekly-commerce端到端测试使用当前数据形状：33个现代Player/SBC模型、4个legacy包、三页implicit product_keys、Trio原有12条包平台绑定。先证明仅prepare虽有候选却不能生成公开原生报价别名；再通过实际隔离production-server的HTTP center/save，提交4条model_imports，由原服务器model_resolve读可信details，一次保存追加到37模型，只更换同4个bundle键，原33记录、weekly/trio/sbc/routes保持。原ID重放读回原回执，不重新读取/保存。

后续沿原commerce prepare、私有preview、模拟明确确认publish和原price producer刷新缓存，证明三页共36条包平台绑定、仅新增Weekly/SBC24条、Trio原12条精确保留；4×3×3公共报价ready，私有preview保持不可购买。观察价格完全为隔离fixture，未冒充生产读取。未知模型请求不造兜底观察；原保留Seasonal模型仅作为明确独立fixture并验证不进入FC三页。

相关commerce/workflow17项通过、0fail/0skip。只新增测试，无生产源码变更，23文件候选保持同一SHA。该测试证明现有一次可信导入/保存足够，不另加自动迁移、兼容层或付费Sol调用；生产转换和正式报价仍须批准后执行与读回。

## 后续明确授权：仅追踪6文件已部署

用户再次明确“允许追踪”后，沿同一原publisher只激活4个已合并追踪源码、追踪开关及只改2项的静态摘要。manifest `1d8d686405640c290912688f7d1a21b984a6aa51f11aaf89944fcec0f7958b5c`，release/backup `nav-20261109T140059Z`。6 after SHA、其余59守卫与三服务active均读回；enabled=true、原center/public27/policy/发布操作及登记11保持。首次cache unavailable保留为initial证据，未主动刷新，14:03:13 UTC原producer自然恢复ready78。

真实浏览器使用同一新测试标记，既有同意状态下先收到1次访问；显式拒绝后切平台/刷新未增加，恢复允许后3页分别操作卡片曝光和选择。14:18 UTC Query三页HTTP200/available，读回独立事件ID，诊断为test：Scout 8、SBC 6、Trio 6，含各页view/product_view/selection；没有伪造checkout/purchase。实际正式统计未混入本次测试。

已登录FS真实付款面板在14:16 UTC读取当日FCSCOUT10合计0笔/$0，明确不拆单页收入或访客付款率。用户原购物车有2件PS商品，未修改数量、优惠或信息；本轮未新增加购/下单/付款，旧版27的先前真实7项购物车证据按原范围保留，不能称本轮新Capture加购已验。

旧四包可见价另经只读源追踪及公开目录核实，来自既存main_catalog通道而非静态种子；Admin/model缓存3/7只表示现代模型报价覆盖。页面成功价无独立TTL的限制保留，四模型转换后仍须验证新的统一链路。不再将“4旧包缺现代别名/缓存投影”写成“页面完全无价格”。

PR961 / CI1851成功，main `2a5ffda91f4c759c59ce7b5ed03ca8bbd78b4399`。剩余页面18文件已按新6文件基线重建、原publisher inspect通过，未激活；导航18及四包正式业务发布仍待当前清单批准。原23包仅留历史且不可重放。
