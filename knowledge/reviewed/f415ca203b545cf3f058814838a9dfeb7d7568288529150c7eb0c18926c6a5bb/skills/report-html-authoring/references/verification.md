# 报告页面的浏览器验收步骤

目标：证明交付的那一个文件在浏览器里能用，而不是证明“文件存在”或“HTML 合法”。所有结论绑定被测文件 SHA。

## 0. 先固定被测对象

- 重建会改变 SHA。先记录当前 `sha256sum`，再验收；验收后任何修改都使结论失效，需重验受影响部分。
- 文本层面的检查（标签配对、锚点、外链、占位符、图表 JSON、SVG 越界）先用脚本跑一遍，再进浏览器。

## 1. 每个视口用独立会话

长会话在多次 `goto_url` 后可能让页面求值挂起；换一个新会话、用 `new_tab` 打开、先设视口再导航，最稳：

```python
new_tab("about:blank")
cdp("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
goto_url("file:///abs/path/report.html")
time.sleep(1.0)
```

桌面与 390px 各用一个会话（390 时 `mobile=True`），不要在同一会话里反复切换视口来判定两套布局。

## 2. 用测量代替看图

```js
(() => { const de=document.documentElement;
  return {overflow: de.scrollWidth-de.clientWidth, main: document.querySelector('main').getBoundingClientRect().width,
    kpiCols: getComputedStyle(document.querySelector('.kpis')).gridTemplateColumns,
    tables: [...document.querySelectorAll('.fs-table-scroll')].map(x=>[x.clientWidth,x.scrollWidth])};})()
```

判据：页面 `overflow == 0`；正文宽度等于范本容器（如 1180）；390px 下 KPI 两列；表格 `scrollWidth > clientWidth` 且只在自己的容器里横向滚动；没有元素越过视口右边界（排除 `.fs-table-scroll` 后代）。

## 3. 交互逐项点，读回状态

- 指标切换：点每个按钮后读 `aria-pressed`、`#metric-readout` 文本、`svg[aria-label]`，三者必须同步。
- 主题：点一次读 `document.documentElement.dataset.fsTheme`、按钮文案与 `aria-pressed`，再读 `.panel` 的背景色确认用的是令牌。
- 折叠：点 `summary` 后读 `details.open`，并读 `.preview` 的 `display`；展开时应 `none`，收起时应 `block`。
- 打印：`Emulation.setEmulatedMedia media=print` 后读 `nav` 为 `none`、`details` 为 `block`、表格 `overflow` 为 `visible`；再派发 `beforeprint`/`afterprint` 验证展开与恢复。真实打印对话框不在此覆盖，回执要写明。

## 4. 下载按“落盘再重开”验

不要把序列化字符串当下载结果。设置下载目录、点按钮、等文件出现、再从磁盘读：

```python
cdp("Page.setDownloadBehavior", behavior="allow", downloadPath="/abs/tmp")
js("document.getElementById('download').click()")
time.sleep(2.5)
```

检查文件以 `<!doctype html>` 开头、以 `</html>` 结尾、含图表 JSON 与脚本节点；再用 `file://` 打开下载稿，确认标题、指标读数与 SVG 都在。浏览器序列化会重写属性，下载稿 SHA 必然不等于源稿，比较完整性而不是比较哈希。

## 5. 截图与失败处理

- 截图能出就存；出不了（超时/无显示）就用上面的测量值作证据，并在回执写“截图未验”。
- 任何一项没做成就写未验，不写“通过”。主 Agent 或他人做的验证单独记，注明其 SHA，不与自己的检查混写。
- 有无外联请求同时用源码检查（无 `script src`、无 `fetch`/`XHR`/`WebSocket`）与浏览器网络面板证据；只有其中一项时如实说明。

## 6. 回执格式

每个被测文件写：路径、字节、SHA、视口与结果、交互项、下载重开结果、未验项、验证者。验收者、被测 SHA、时间三者缺一，结论不可复用。
