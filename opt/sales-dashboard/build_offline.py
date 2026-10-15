# -*- coding: utf-8 -*-
"""把 web/index.html + data/dashboard.json 打包成一个「单文件离线看板」。

产物：销售数据看板_AION2_离线版.html
  · 数据已内联进 HTML，双击即可打开（file://），不需要起服务、不联网。
  · 缺点：数据是打包那一刻的快照；要新数据请重新跑本脚本或起服务版。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "web" / "index.html"
DATA = ROOT / "data" / "dashboard.json"
OUT = ROOT / "销售数据看板_AION2_离线版.html"

html = SRC.read_text(encoding="utf-8")
raw = DATA.read_text(encoding="utf-8")
# 内联到 <script> 里，防止 JSON 中出现 </script> 提前闭合
raw = raw.replace("</", "<\\/")

# 1) 在 DATA_URL 声明后注入内联数据
anchor = "const DATA_URL = 'data/dashboard.json';"
assert anchor in html, "找不到 DATA_URL 声明，index.html 结构变了"
html = html.replace(anchor, anchor + "\nconst INLINE_DATA = " + raw + ";", 1)

# 2) load() 优先用内联数据
old = """  try{
    const r = await fetch(DATA_URL+'?t='+Date.now());
    if(!r.ok) throw new Error('HTTP '+r.status+' 未找到数据文件，请先点「重新抓取」');
    RAW = await r.json();"""
new = """  try{
    if (typeof INLINE_DATA !== 'undefined' && INLINE_DATA) {
      RAW = INLINE_DATA;
    } else {
      const r = await fetch(DATA_URL+'?t='+Date.now());
      if(!r.ok) throw new Error('HTTP '+r.status+' 未找到数据文件，请先点「重新抓取」');
      RAW = await r.json();
    }"""
assert old in html, "找不到 load() 取数代码，index.html 结构变了"
html = html.replace(old, new, 1)

# 3) 离线版禁用「重新抓取」（没有后端可调）
old_btn = html[html.index("$('#btnRefresh').onclick=async()=>{"):html.index("load();\n</script>")]
html = html.replace(old_btn, """$('#btnRefresh').onclick=()=>{
  alert('这是离线单文件版，数据已内联在页面里。\\n\\n要更新数据：双击 sales_dashboard\\\\start.bat 起服务版并点「重新抓取」，\\n或重新运行 build_offline.py 重新打包。');
};
""", 1)

# 4) 顶部标注离线版
html = html.replace("</head>", "<!-- 离线单文件版：数据快照已内联，双击即可打开 -->\n</head>", 1)

OUT.write_text(html, encoding="utf-8")
size = OUT.stat().st_size
print("已生成:", OUT)
print("大小: %.2f MB" % (size / 1024 / 1024))
print("内含订单:", len(json.loads(raw.replace("<\\/", "</")).get("orders", [])))
