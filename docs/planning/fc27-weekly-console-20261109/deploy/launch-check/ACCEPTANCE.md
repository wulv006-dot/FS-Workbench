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

按总控回执，CI1848的425项Node检查通过，但weekly-console浏览器用例因popup通知/close时序失败，不能记为整次CI通过。后端代理随后只修测试等待close的时序，相关23 checks连续三次通过。**本记录写入时CI1849仍在运行，尚无正式通过结论。**

生产部署、公开页面、新正式追踪及本轮业务新绑定的发布/真实入口验收，均由总控取得实际回执后另行补充。本节不将先前版本27的交易证据复述为本轮新验收；旧证据仅按其原范围参见[既有独立编辑流程验收](../paged-workflow/ACCEPTANCE.md)及[既有商业接入验收](../commerce/ACCEPTANCE.md)。
