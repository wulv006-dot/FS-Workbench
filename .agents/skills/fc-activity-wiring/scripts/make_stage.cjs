// 生成 187 发布包（候选目录 + manifest + inspect）。
//
// 用法（在仓库任意目录运行，或用 FS_REPO 指定仓库根）：
//   node make_stage.cjs <scratch目录> <发布号> <合并提交SHA> <requestId> <模块相对路径...>
// 例：
//   node make_stage.cjs "$SCRATCH" 81 9b5f587... fs-campaign-xxx-pr1190 \
//     app/activity.js app/seasonal/activity-analytics.js backend/bridge.py
//
// 做的事：
//   1. 从合并提交里用 git show 导出每个文件（LF）和 publish.py，平铺到 <scratch>/rel<发布号>/；
//   2. 按发布器的依赖校验自动补齐必须一起带的文件（会打印出来）；
//   3. 写出 stage.sh：在 187 上建 /var/tmp/fs-campaign-release<发布号>-candidate、生成 release-manifest.json、
//      运行 publish.py inspect（不改线上），并打印 MANIFEST_SHA。
// 本脚本不上传、不 apply；上传和 apply 见 references/release-and-verify.md。
const fs = require('fs');
const cp = require('child_process');

const [scratch, rel, commit, requestId, ...given] = process.argv.slice(2);
if (!scratch || !rel || !/^[0-9a-f]{40}$/.test(commit || '') || !requestId || !given.length) {
  console.error('usage: node make_stage.cjs <scratch> <releaseNo> <40-hex merge commit> <requestId> <module-relative files...>');
  process.exit(2);
}
const repo = process.env.FS_REPO || cp.execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
const MODULE = 'releases/fs-dashboard/campaign-analytics-20261023';
const dir = `${scratch}/rel${rel}`;

// 发布器的依赖校验（publish.py validate）：缺了会被拒绝。
const files = [...given];
const need = (trigger, extra) => {
  if (files.some(f => trigger.includes(f))) for (const e of extra) if (!files.includes(e)) { files.push(e); console.log('auto-added (publisher dependency):', e); }
};
need(['app/analytics/statistics-refresh.mjs', 'app/analytics/server.mjs', 'app/analytics/discount-revenue.mjs'], ['app/analytics/statistics-retry.mjs']);
need(['app/analytics/production-server.mjs'], ['app/analytics/google-traffic.mjs', 'backend/google_traffic.py']);

fs.rmSync(dir, { recursive: true, force: true });
fs.mkdirSync(dir, { recursive: true });
const flat = f => f.replace(/\//g, '__');
const show = path => cp.execFileSync('git', ['-C', repo, 'show', `${commit}:${MODULE}/${path}`], { maxBuffer: 64 * 1024 * 1024 });
for (const f of files) fs.writeFileSync(`${dir}/${flat(f)}`, show(f));
fs.writeFileSync(`${dir}/publish.py`, show('publish.py'));

const appRel = files.filter(f => f.startsWith('app/')).map(f => f.slice(4));
const targets = Object.fromEntries(files.map(f => [f, '/opt/fs-campaign-dashboard/' + (f.startsWith('app/') ? f.slice(4) : f)]));
const installs = files.map(f => `install -D -m 644 "$U/${flat(f)}" "$S/candidate/${f}"`).join('\n');
const sh = `set -euo pipefail
S=/var/tmp/fs-campaign-release${rel}-candidate
U=/tmp/rel${rel}
[ -e "$S" ] && { echo "stage exists"; exit 1; }
install -d -m 700 "$S" "$S/candidate" "$S/candidate/app" "$S/candidate/app/runtime" "$S/native"
install -m 600 /var/tmp/fs-campaign-release71-candidate/native/release_navigation_base.py "$S/native/"
install -m 600 "$U/publish.py" "$S/publish.py"
${installs}
install -m 644 /etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf "$S/candidate/navigation.conf"
install -m 644 /var/www/dashboard/fs-home/navigation.json "$S/candidate/navigation.json"
install -m 644 /var/www/dashboard/fs-home/module-registry.json "$S/candidate/module-registry.json"
install -m 644 /etc/systemd/system/fs-campaign-dashboard.service "$S/candidate/fs-campaign-dashboard.service"
python3 - "$S" <<'PY'
import json,hashlib,sys,pathlib
S=pathlib.Path(sys.argv[1]);sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
live='/opt/fs-campaign-dashboard/runtime/static-manifest.json'
raw=pathlib.Path(live).read_text();sm=json.loads(raw)
d=sm['files'] if isinstance(sm,dict) and isinstance(sm.get('files'),dict) else sm
for f in ${JSON.stringify(appRel)}:
    if f in d: d[f]=sha(S/'candidate/app'/f)
indent=2 if raw.lstrip().startswith('{\\n') or '\\n  "' in raw[:200] else None
out=json.dumps(sm,indent=indent,ensure_ascii=False)+('\\n' if raw.endswith('\\n') else '')
(S/'candidate/app/runtime/static-manifest.json').write_text(out)
T=${JSON.stringify(targets)}
T['app/runtime/static-manifest.json']='/opt/fs-campaign-dashboard/runtime/static-manifest.json'
T.update({'navigation.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf','navigation.json':'/var/www/dashboard/fs-home/navigation.json','module-registry.json':'/var/www/dashboard/fs-home/module-registry.json','fs-campaign-dashboard.service':'/etc/systemd/system/fs-campaign-dashboard.service'})
before=lambda t: sha(t) if pathlib.Path(t).exists() else None
files=[dict(beforeSha256=before(t),candidate=c,sha256=sha(S/'candidate'/c),target=t) for c,t in T.items()]
m=dict(schemaVersion=1,scope='fs-campaign-dashboard-20261023',requestId='${requestId}',releaseReady=True,
 sourceRevision='${commit}',integrationMergeCommit='${commit}',
 deploymentComposition=dict(activity_source='${commit}',full_main_deployed=False,policy_unchanged_by_this_release=True,public_configuration_unchanged=True,shared_configuration_unchanged=True,runtime_origin='https://www.mmoexp.com',static_manifest_harmonised=True,line_endings='LF from merge commit; live CRLF copies had identical content'),
 concurrentModuleGuards={},targets=T,files=files,
 unchangedRequired=[dict(path=p,sha256=sha(p)) for p in ('/opt/auth-portal/auth_portal.py','/opt/fs-access-policy/rbac.py')],
 preservedBusinessState={p:sha(p) for p in ('/var/lib/fs-campaign-dashboard/backend/policy.json','/var/lib/fs-campaign-public/current.json')})
(S/'release-manifest.json').write_text(json.dumps(m,indent=2))
for r in files: print(('CHANGED ' if r['beforeSha256']!=r['sha256'] else 'same    ')+('NEW ' if r['beforeSha256'] is None else '')+r['candidate'],r['sha256'][:12])
print('static-manifest keys',len(d))
PY
chmod 600 "$S/release-manifest.json"
cd "$S" && python3 publish.py inspect --manifest "$S/release-manifest.json"
echo "MANIFEST_SHA $(sha256sum $S/release-manifest.json | cut -c1-64)"
rm -rf "$U"
`;
fs.writeFileSync(`${dir}/stage.sh`, sh);
console.log(`stage ready: ${files.length} files in ${dir}`);
