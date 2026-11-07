# 模块版式配方：编号分项与进度图

两段可直接粘贴的 CSS/标记，用于把“模块一 · 主判断与业务影响”从密排段落改成编号分项，把目标表改成进度图。样式走报告自身的 CSS 变量（`--surface-2/--accent/--track/--warn/--up/--down`），自动跟随浅色、深色与打印。

## 1. 编号分项（替代 4–5 段正文）

```css
.points{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px;}
.points>li{display:grid;grid-template-columns:96px minmax(0,1fr);gap:12px;padding:9px 11px;
  background:var(--surface-2);border-radius:8px;align-items:start;}
.points .pt{font-size:12.5px;font-weight:700;color:var(--accent);line-height:1.5;}
.points .kv{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;line-height:1.5;}
.points .kv>span{display:inline-flex;gap:5px;align-items:baseline;white-space:nowrap;font-variant-numeric:tabular-nums;}
.points .kv em{font-style:normal;color:var(--muted);font-size:11.5px;}
.points .read{display:block;font-size:12.5px;color:var(--muted);margin-top:3px;}
@media (max-width:560px){.points>li{grid-template-columns:1fr;gap:4px;}}
```

```html
<ol class="points">
  <li><span class="pt">① 经营面</span><div><div class="kv">
    <span><em>收入</em><b class="neg">$20.95万</b><b class="neg">-10.7%</b></span>
    <span><em>订单</em><b class="neg">3,150</b><b class="neg">-12.0%</b></span>
    <span><em>客单</em><b>$66.51</b><b class="pos">+1.4%</b></span>
  </div><span class="read">一句话解读，不复述上面的数字。</span></div></li>
</ol>
```

要点：`<b class="pos">` 走红涨（`--up`）、`<b class="neg">` 走绿跌（`--down`），单位与符号照原值写；`read` 只写结论，不重复标签里的数值；项名固定 4–6 个，从左到右就是读者的问题顺序（结果→用户→市场→结构→节点）。业务影响留在单独的 `.impact` 框，不塞进 `<ol>`。

## 2. 目标进度图（替代多行表格）

```css
.prog-group{margin:10px 0 4px;} .prog-name{font-size:12px;font-weight:700;color:var(--accent);margin-bottom:4px;}
.prog-row{display:grid;grid-template-columns:44px minmax(0,1fr) 56px;gap:10px;align-items:center;margin:5px 0;}
.prog-lab{font-size:12px;color:var(--muted);}
.prog-track{position:relative;height:16px;background:var(--track);border-radius:3px;overflow:hidden;}
.prog-fill{display:block;height:100%;background:var(--accent);border-radius:3px;}
.prog-fill.risk{background:var(--warn);}
.prog-time{position:absolute;top:0;bottom:0;left:58.1%;width:1px;background:var(--zero);opacity:.9;}
.prog-val{font-size:12.5px;font-weight:600;text-align:right;font-variant-numeric:tabular-nums;}
.prog-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:11.5px;color:var(--muted);margin:8px 0 2px;}
```

```html
<div class="prog" role="img" aria-label="目标完成度与时间进度 58.1% 对照">
  <div class="prog-group"><div class="prog-name">FC</div>
    <div class="prog-row"><span class="prog-lab">收入</span>
      <span class="prog-track"><span class="prog-fill" style="width:72.0%"></span><span class="prog-time"></span></span>
      <span class="prog-val">72.0%</span></div>
  </div>
  <div class="prog-legend"><span>目标完成度</span><span>时间进度 58.1%（18/31 天）</span></div>
</div>
<details><summary>明细表：月累计 / 月目标 / 进度</summary><div class="inner">…原表格…</div></details>
```

要点：进度条的宽度百分比直接来自原值，超过 100% 的封顶到 100% 但**数字仍写原值**；低于时间进度的加 `.risk`；时间参照线用 `left:<时间进度>%` 一处变量，改两处容易不一致；原表格整体搬进 `<details>`，不要删——它是下钻与对账的入口。

## 3. 改稿流程（不重跑任务）

1. 读原稿，**只**替换被点名的 `<article>` 块；用 `<article class="judgment">…</article>` 这类块级匹配做定点替换，替换前后各数一次块数与条目数。
2. 数字从原稿抄，不从记忆或新查询重算；改完用 `html.parser` 过一遍配对，再进浏览器量一遍（图元宽度、颜色、窄屏溢出）。
3. 另存 v2 文件名，回复里注明“本地改稿，FS 归档仍是原稿”，并说明这些改动纯版式、数值未变。
