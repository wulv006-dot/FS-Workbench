# -*- coding: utf-8 -*-
"""交叉验证：线上 Node 版判定 与 控制台 Python 复刻版判定 是否逐字一致。
两份实现必须等价，否则控制台「名称测试器」给出的结论会骗人。
跑法：/opt/bot-console/venv/bin/python /opt/mmoexp-guardbot/_ops_xcheck.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/opt/bot-console")
os.environ["BOTCONSOLE_QUIET"] = "1"

CASES = [
    # 原有前缀型
    "MMOEXP", "mmoexp", "MmoExp", "MMOEXP Support", "MMOEXP_Official", "MMOEXP-CS",
    "MMOEXP | Store", "MMOEXP01", "mmoexp_88", "mmoEXP.team", "MM0EXP", "MMOOEXP",
    "mmo0exp", "\uff2d\uff2d\uff2f\uff25\uff38\uff30", "\u041c\u041c\u041e\u0415\u0425\u0420",
    "MMO E X P", "m.m.o.e.x.p", "The MMOEXP", "mmoexpbot", "MMOEXP-gift",
    "mmoexp official", "MMO\u200bEXP",
    # 新增：片段式（品牌词不在开头）
    "nick.mmoexp", "service_mmoexp", "david.mmoexp", "sunny_mmoexp", "SellTous_MMOEXP",
    "THE-MMOEXP", "Best_mmoexp_deals",
    # 新增：拼写容错（少一个字母）
    "service_mmoex", "nick.mmoex", "ask.mmoexp_",
    # 不该命中的
    "mmoexpert", "mmoexpo", "mmoex", "moexp", "John", "Support", "Mike", "Nicholas",
    "MMO Player", "WoW Gold Seller", "Cheap Diablo 4 Gold", "official support",
    "mmo exp lover", "MMOEXPfan2026_play", "nickmoexp", "mmoexpfan2026", "mmoexpgaming",
    "MMO Expert", "mmo experience",
]

JS = r"""
const fs = require('fs');
const g = require('/opt/mmoexp-guardbot/index.js');
g.loadConfig();
const cs = JSON.parse(fs.readFileSync('/tmp/_x_cases.json', 'utf8'));
const out = cs.map((n) => { const r = g.classify(n); return [n, !!r, r ? r.via : null]; });
fs.writeFileSync('/tmp/_x_node.json', JSON.stringify(out));
"""

with open("/tmp/_x_cases.json", "w", encoding="utf-8") as fh:
    json.dump(CASES, fh, ensure_ascii=False)
with open("/tmp/_x_node.js", "w", encoding="utf-8") as fh:
    fh.write(JS)

subprocess.run(["node", "/tmp/_x_node.js"], check=True)
node_out = json.load(open("/tmp/_x_node.json", encoding="utf-8"))

import server as S  # noqa: E402  （import 时会读配置，属只读初始化）

cfg = json.load(open("/opt/mmoexp-guardbot/config.json", encoding="utf-8"))

bad = 0
print("PASS/FAIL  名字                        Node 判定       Python 判定")
for name, nhit, nvia in node_out:
    r = S.classify(name, cfg)
    phit = bool(r and not r.get("error"))
    pvia = (r or {}).get("via")
    ok = (nhit == phit) and (nvia == pvia)
    if not ok:
        bad += 1
    print("%-8s  %-24s %-5s/%-12s %-5s/%-12s"
          % ("PASS" if ok else "FAIL", json.dumps(name, ensure_ascii=False),
             nhit, nvia, phit, pvia))

print("\n===== Node vs Python 交叉验证：%d 例，%d 处不一致 =====" % (len(CASES), bad))
hit = sum(1 for _, h, _ in node_out if h)
print("其中命中 %d 例 / 放行 %d 例" % (hit, len(CASES) - hit))
sys.exit(1 if bad else 0)
