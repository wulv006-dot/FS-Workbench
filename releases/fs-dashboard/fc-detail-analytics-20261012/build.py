"""Build only this FC increment from the hash-verified active frontend."""
from pathlib import Path
import hashlib, json, re, shutil

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / ('fs_on_demand_20261012' if (ROOT.parent/'fs_on_demand_20261012').exists() else 'on-demand-20261012') / 'entry-native-boundary-final/frontend'
OUT = ROOT / 'frontend'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert digest(BASE / 'assets/business.js') == '0cfd490311edf76c22a7e1d0392c1936e42fd9b70e4e8d0c8bf11900445b9b57'
assert digest(BASE / 'assets/business.html') == '82ea9b8f540ff54d2ce90b6e37802df72d5a8e8f7b0f28f71bd666441db00537'

def replace(text, old, new):
    assert text.count(old) == 1, old[:90]
    return text.replace(old, new, 1)

def build():
    for folder in ('assets', 'candidate'):
        for path in (BASE / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                target = OUT / folder / path.relative_to(BASE / folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    original = (BASE / 'assets/business.js').read_text('utf-8')
    original = replace(original, 'const globalThis=window;', "const globalThis=window;\nlet fcDetailState={key:'',data:null,error:'',tab:scope.seed?.fc_tab||'overview'};")
    original = replace(original, ' const revenue=mainMetrics.revenueUsd.value,rate=mainMetrics.profitMarginPct.value;', " if(profile?.key==='FC27'&&fcDetailState.data?.coverage.paid_complete&&fcDetailState.data.query.start===currentSelection().start&&fcDetailState.data.query.end===currentSelection().end){\n  const t=fcDetailState.data.totals;for(const [key,value]of [['orders',t.orders],['revenueUsd',t.unpriced_orders?null:t.revenue_usd]])mainMetrics[key]={value,status:value===null?'not_provided':'available',source:'Admin订单明细',scope:fcDetailState.data.scope_label+' · 当前筛选',stale:fcDetailState.data.stale};\n }\n const revenue=mainMetrics.revenueUsd.value,rate=mainMetrics.profitMarginPct.value;")
    original = replace(original, 'function workspaceState(){', (OUT / 'fc-detail.js').read_text('utf-8') + '\nfunction workspaceState(){')
    original = replace(original, "  b_section:scope.section||'overview',b_metrics:scope.metrics?'all':'core',snapshotId:snapshot?.snapshotId,", "  fc_tab:KEY==='FC27'?fcDetailState.tab:'',b_section:scope.section||'overview',b_metrics:scope.metrics?'all':'core',snapshotId:snapshot?.snapshotId,")
    original = replace(original, ' workspaceRestoring=true;', " workspaceRestoring=true;fcDetailState.tab=fcTabs.some(r=>r[0]===s.fc_tab)?s.fc_tab:'overview';")
    original = replace(original, ' requestDailyProfit();workspaceFCTypes();', ' requestDailyProfit();workspaceFCTypes();fcDetailSync();')
    original = replace(original, "for(const c of cards)c.hidden=!scope.metrics&&c.dataset.core==='false';", "for(const c of cards)c.hidden=!scope.metrics&&(KEY==='FC27'?Number(c.style.order)>3:c.dataset.core==='false');")
    original = replace(original, 'function workspaceClearRanges(){', "function workspaceClearRanges(){\n fcDetailState.key='';")
    original = replace(original, 'function rowsInRange(){', "function rowsInRange(){\n if(KEY==='FC27'&&fcDetailState.data?.coverage.paid_complete&&GRAIN==='day'&&fcDetailState.data.query.start===currentSelection().start&&fcDetailState.data.query.end===currentSelection().end)return fcDetailState.data.trend.map(r=>({date:r.date,ts:r.date,orders:r.orders,amount:r.revenue_usd}));")
    (OUT / 'assets/business.js').write_text(original, 'utf-8', newline='\n')
    css = (BASE / 'assets/business.css').read_text('utf-8') + '\n' + (OUT / 'fc-detail.css').read_text('utf-8')
    css = css.replace('var(--text)', 'var(--tx)').replace('var(--panel,#fff)', 'var(--surface)').replace('var(--muted,#667080)', 'var(--tx2)').replace('var(--accent,#e7efff)', 'var(--ac-soft)').replace('var(--link,#477ec8)', 'var(--ac)')
    (OUT / 'assets/business.css').write_text(css, 'utf-8', newline='\n')
    shell = (BASE / 'assets/shell.js').read_text('utf-8')
    shell = replace(shell, "const allowed=['b_group'", "const allowed=['fc_tab','b_group'")
    shell = replace(shell, 'allowed.filter(k=>k.startsWith(prefix))', "allowed.filter(k=>k.startsWith(prefix)||(prefix==='b_'&&k==='fc_tab'))")
    (OUT / 'assets/shell.js').write_text(shell, 'utf-8', newline='\n')
    # A new immutable directory; all unrelated payloads retain their original content.
    old = json.loads((BASE / 'release-contract.json').read_text('utf-8'))['releaseId']
    version = 'workspace-native-20261006-' + hashlib.sha256((original + css + shell).encode()).hexdigest()[:12]
    for folder in ('assets', 'candidate'):
        for path in (OUT / folder).rglob('*'):
            if path.is_file(): path.write_bytes(path.read_bytes().replace(old.encode(), version.encode()))
    manifest = json.loads((BASE / 'release-contract.json').read_text('utf-8').replace(old, version))
    manifest['scope'] = 'FC27 detailed analysis only; main and satellite groups; existing auth/readers/publishers'
    baseline = json.loads((ROOT/'baseline-readback.json').read_text('utf-8-sig'))
    for row in manifest['targets']:
        assert digest(BASE / row['candidate']) == baseline['hashes'][row['target']], 'active frontend changed'
        row['beforeSha256'] = baseline['hashes'][row['target']]
    for row in manifest['unchangedRequired']:
        if row['path'] in ('/etc/nginx/conf.d/iggm-web.conf','/var/www/dashboard/fs-home/navigation.json'): row['sha256'] = baseline['hashes'][row['path']]
    for row in manifest['immutableAssets'] + manifest['targets']: row['sha256'] = digest(OUT / row['candidate'])
    # The only preceding backend change; freeze its new hash in the frontend guard.
    for row in manifest['unchangedRequired']:
        if row['path'] == '/opt/fs-exact-range-20261001/range_api.py': row['sha256'] = digest(ROOT / 'source/range_api.py')
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    for name in ('release-contract.json', 'release-manifest.json'): (OUT / name).write_bytes(raw)
    publisher = (BASE / 'release_workspace.py').read_text('utf-8')
    publisher = re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '" + hashlib.sha256(raw).hexdigest() + "'", publisher)
    (OUT / 'release_workspace.py').write_text(publisher, 'utf-8', newline='\n')
    return version

if __name__ == '__main__': print(build())
