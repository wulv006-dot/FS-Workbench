"""Exact independent v3 inventory and source/diff verification; local only."""
from datetime import datetime,timezone
import ast
import difflib
import hashlib
import json
from pathlib import Path


def main():
    source=Path(__file__).resolve().parent;root=source.parent
    docs=root/'docs/planning/registration-approval-candidate-v5-20261006'
    baseline=json.loads((docs/'v4-baseline.json').read_text(encoding='utf-8'))
    def info(path):
        content=path.read_bytes();return {'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    files={str(p.relative_to(source)).replace('\\','/'):info(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.html','.js','.css')}
    old_v2=json.loads((docs/'v2-baseline.json').read_text(encoding='utf-8'))
    for name,item in old_v2['files'].items():assert info(root/old_v2['source']/name)==item,name
    old_v3=json.loads((docs/'v3-baseline.json').read_text(encoding='utf-8'))
    for name,item in old_v3['files'].items():assert info(root/old_v3['source']/name)==item,name
    diff=[]
    for name,item in baseline['files'].items():
        old=root/baseline['source']/name;assert info(old)==item,name
        a=old.read_text(encoding='utf-8');b=(source/name).read_text(encoding='utf-8')
        if a!=b:diff.extend(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='v4/'+name,tofile='v5/'+name))
    (docs/'v4-to-v5.diff').write_text(''.join(diff),encoding='utf-8')
    provenance=json.loads((docs/'native-source-provenance.json').read_text(encoding='utf-8'))
    for path,item in provenance['inputs'].items():assert info(root/path)==item,path
    portal_path='ui_shell_20261006/navigation/auth_unification/auth_portal.py'
    original=(root/portal_path).read_text(encoding='utf-8');export=(source/'native_portal_functions.py').read_text(encoding='utf-8')
    def functions(text):return {n.name:ast.get_source_segment(text,n) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
    before,after=functions(original),functions(export)
    for name in provenance['portal_functions']:assert before[name]==after[name],name
    policy_path='fs_platform_integration_20261005/data/raw/chenchao-source/fs-platform-src/opt/fs-access-policy/access_policy.py'
    assert (root/policy_path).read_bytes()==(source/'native_access_policy.py').read_bytes()
    board_path='taskboard_module_20261001/server/taskboard_server.py'
    assert functions((root/board_path).read_text(encoding='utf-8'))['member_state']==functions((source/'native_taskboard_member.py').read_text(encoding='utf-8'))['member_state']
    inventory={'at':datetime.now(timezone.utc).isoformat(),'source':source.name,'releaseReady':False,'uploadApproved':False,'productionActions':[],
        'files':files,'v4_baseline':baseline,'changed_files':[n for n in baseline['files'] if files[n]!=baseline['files'][n]],
        'new_files':sorted(set(files)-set(baseline['files'])),'source_provenance':provenance,'native_functions_exact':True,
        'central_policy_exact':True,'taskboard_member_function_exact':True,
        'notes':['local approved references; not current production SHA','synthetic authentication inputs/business payload only','no runtime credentials/group records/databases in inventory']}
    manifest=json.loads((root/'server_187/manifest.json').read_text(encoding='utf-8-sig'))
    assert source.name not in json.dumps(manifest,ensure_ascii=False)
    content=json.dumps(inventory,ensure_ascii=False,indent=2)+'\n'
    (docs/'manifest.json').write_text(content,encoding='utf-8');(docs/'inventory.json').write_text(content,encoding='utf-8')
    print(json.dumps({'files':len(files),'v4_18_SHA_preserved':True,'native_source_exact':True,'releaseReady':False}))


if __name__=='__main__':main()
