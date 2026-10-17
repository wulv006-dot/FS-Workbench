"""Prepare a private inspect-only learning payload; never connect or publish."""
import argparse, hashlib, json
from pathlib import Path

SHA=lambda raw:hashlib.sha256(raw).hexdigest()
BASE='/var/lib/fs-hermes-fc/profile/skills/ops-report-brief/ops-report-family/'
NAMES=('approved-daily-20261016.md','approved-weekly-20261005-11.md')
APPROVED=('c5a4e07af3dd042e0d24e4ee5ccabb7097994bf730a2c811eed5693d31f2ce2e','0fe482e58a1a4a5ceda57a8bde0000acc65dbe6ba7cc187543fe1d6c031b4a4e')
TARGETS=('/opt/fs-hermes-fc/business_context.py','/opt/fs-hermes-fc/learning-loop.md',BASE+'SKILL.md',*(BASE+'references/'+n for n in NAMES))
BASELINES=('3a3d35bfe970cbac0343e322ce75374374544e29b5056c775efde898c1446706','2c5e2787bba292a27fd1b924f2c159c33a39e50e9f303b49abcceeae51426fbd','50ca9420279e5541872e7049a423fc4f9b85609f3b8790da99c2e6772d278a18',None,None)
REVISION='''\n\n## 2026-10-17 用户确认的报告方法修订（替代相反旧约定）
本节明确替代前文“沿用原版”“必须5个固定小标题”“首批只FC”等相反约定。按当前任务授权与真实可用游戏范围组织日报、周报及月报；本修订不启用月报专项调度，不扩大写入、模型或预算权限。
下列方法用于组织判断与可读报告；两份references/approved-*.md是注明历史期间的审核案例，只学习分析与呈现方法。案例金额、日期、订单、活动及结论不得替代新任务冻结证据；缺少当前证据不得抄写旧值或旧结论。新任务保留knowledgeSHA及每文件SHA，旧报告与冻结知识不重写。
'''

def regular(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('regular_source_required')
    return path.read_bytes()

def check(folder):
    folder=Path(folder);m=json.loads((folder/'learning-manifest.json').read_text(encoding='utf8'))
    if tuple(r['target'] for r in m['files'])!=TARGETS or tuple(r['beforeSha256'] for r in m['files'])!=BASELINES:raise ValueError('exact_learning_targets_required')
    if m['releaseReady'] is not False or m['productionWrites']!=0 or m['requiresLockedAdmissionGate'] is not True:raise ValueError('inspect_only_required')
    for r in m['files']:
        raw=regular(folder/r['candidate'])
        if SHA(raw)!=r['sha256'] or len(raw)!=r['bytes']:raise ValueError('payload_drift')
        if r['owner']!='0:0' or r['mode'] not in ('0o600','0o644'):raise ValueError('private_owner_required')
    return m

def prepare(audit,family,method,daily,weekly,out):
    out=Path(out)
    if out.exists():raise ValueError('new_output_required')
    a=json.loads(regular(audit));f=json.loads(regular(family));rows={r['path']:r for r in a['files']+f['files']}
    for target,expected in zip(TARGETS,BASELINES):
        row=rows[target]
        if expected is None:
            if row['exists'] or row['is_symlink']:raise ValueError('new_reference_already_exists')
        elif row['is_symlink'] or row['sha256']!=expected or SHA(row['text'].encode())!=expected:raise ValueError('active_source_drift')
    examples=[regular(daily),regular(weekly)]
    if tuple(map(SHA,examples))!=APPROVED:raise ValueError('approved_example_sha_required')
    methods=regular(method);methods.decode('utf8')
    loader=regular(Path(__file__).with_name('business_context.py'))
    original=rows[TARGETS[0]]['text'].encode();anchor=b" 'ops-report-brief/ops-report-family/references/report-input-fields.md',"
    added=anchor+b''.join(b"\n 'ops-report-brief/ops-report-family/references/"+n.encode()+b"'," for n in NAMES)
    if loader!=original.replace(anchor,added):raise ValueError('loader_only_explicit_paths_required')
    suffix=REVISION.encode()+b'\n'+methods
    entry=('\n\n## 2026-10-17 已审核历史案例入口\n通用报告方法以runtime/learning-loop.md末尾2026-10-17修订为准。历史案例仅学习方法，不作当前事实：'+', '.join('references/'+n for n in NAMES)+'。\n').encode()
    payload=[loader,rows[TARGETS[1]]['text'].encode()+suffix,rows[TARGETS[2]]['text'].encode()+entry,*examples]
    # Current bundle includes family+loop; count their appendices and both references.
    total=155237+len(suffix)+len(entry)+sum(map(len,examples))
    if any(len(b)>131072 for b in payload) or total>262144:raise ValueError('learning_size_limit')
    out.mkdir(parents=True);(out/'private-payload').mkdir()
    files=[]
    for i,(target,before,raw) in enumerate(zip(TARGETS,BASELINES,payload)):
        rel='private-payload/'+str(i)+'-'+Path(target).name;(out/rel).write_bytes(raw)
        files.append(dict(target=target,candidate=rel,beforeSha256=before,sha256=SHA(raw),bytes=len(raw),owner=rows[target].get('owner','0:0'),mode=rows[target].get('mode','0o600')))
    protected=[{k:r[k] for k in ('path','sha256')} for r in a['files'] if r['path'] not in TARGETS]
    m=dict(contract='hermes-private-learning-20261017-v1',releaseReady=False,productionWrites=0,requiresLockedAdmissionGate=True,files=files,unchangedRequired=protected,estimatedBundleBytes=total,methodSha256=SHA(methods),approvedExampleSha256=list(APPROVED),serviceScope=['fs-hermes-fc.service'],timersChanged=False,modelChanged=False,budgetChanged=False,rollbackOrder='restore all five targets from locked backups; remove only newly created references; retain old knowledge snapshots')
    (out/'learning-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    check(out);return m

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check');
    for n in ('audit','family','method','daily','weekly','output'):p.add_argument('--'+n)
    a=p.parse_args();m=check(a.check) if a.check else prepare(a.audit,a.family,a.method,a.daily,a.weekly,a.output)
    print(json.dumps({'releaseReady':m['releaseReady'],'targets':len(m['files']),'estimatedBundleBytes':m['estimatedBundleBytes']}))
