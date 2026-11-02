"""Local, opt-in FS code graph. Never executes business/deployment code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/'docs/development/graphify-scope.json'
CODE = {'.py', '.js', '.cjs', '.mjs', '.ts', '.tsx', '.jsx', '.sh', '.ps1', '.sql'}
OMIT = {'node_modules', '__pycache__', '.git', 'history', 'legacy', 'test_support', 'fixtures', 'evidence', 'captures', 'screenshots'}


def git(*args):
    return subprocess.check_output(['git','-C',str(ROOT),*args]).decode('utf-8')


def validate_scope(config):
    if config.get('version') != 2 or not isinstance(config.get('modules'),dict):
        raise ValueError('invalid graph scope schema/version')
    levels={'publisher_mapping','partial_mapping','maintained_source'}
    for name,row in config['modules'].items():
        if row.get('evidence_level') not in levels or not row.get('basis'):
            raise ValueError('missing evidence level/basis: '+name)
        if not isinstance(row.get('roots'),list) or not row['roots']:
            raise ValueError('missing source roots: '+name)
        for relative in row['roots']: safe_path(ROOT,relative)


def worktree_state(files):
    changed=set(git('diff','--name-only','-z','HEAD').split('\0'))-{''}
    return {'tracked_dirty':bool(changed),'scoped_dirty_files':sorted(changed & set(files)),
            'untracked_sources_indexed':False}


def stale_reasons(manifest,config):
    reasons=[]
    if manifest['head'] != git('rev-parse','HEAD').strip(): reasons.append('source HEAD changed')
    if manifest.get('scope_config_sha256') != hashlib.sha256(CONFIG.read_bytes()).hexdigest():
        reasons.append('scope config changed')
    files,_=inventory(ROOT,config)
    if files.keys() != manifest['files'].keys(): reasons.append('selected file set changed')
    elif any(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=v['sha256'] for f,v in manifest['files'].items()):
        reasons.append('selected source content changed')
    return reasons


def safe_path(root, relative):
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('scope path must stay inside repository: '+relative)
    p = (root/p).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError('scope path escapes repository: '+relative)
    return p


def inventory(root, config):
    tracked = set(subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode('utf-8').split('\0'))
    selected, modules = {}, []
    for name, row in config['modules'].items():
        found, missing = set(), []
        for relative in row['roots']:
            path = safe_path(root,relative)
            if not path.exists():
                missing.append(relative)
                continue
            files = path.rglob('*') if path.is_dir() else [path]
            for f in files:
                rel = f.relative_to(root).as_posix()
                if rel in tracked and f.is_file() and not OMIT.intersection(f.relative_to(path if path.is_dir() else path.parent).parts):
                    found.add(rel)
        code = sorted(f for f in found if Path(f).suffix.lower() in CODE)
        for f in code:
            selected.setdefault(f,[]).append(name)
        modules.append({'module':name,'basis':row['basis'],'evidence_level':row['evidence_level'],'code_files':len(code),'html_not_parsed':sorted(f for f in found if Path(f).suffix=='.html'),'missing_roots':missing,'production_verified':False})
    return selected, modules


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['plan','build','update','query','affected','self-test'])
    p.add_argument('question',nargs='?')
    p.add_argument('--state',type=Path,default=ROOT/'.agent_runtime/graphify')
    p.add_argument('--seed',action='append',default=[],help='exact graph node ID or label for query')
    p.add_argument('--budget',type=int,default=1200,help='query output token budget')
    args = p.parse_args()
    if args.action=='self-test':
        for rel in ('../bad','a/../../bad'):
            try: safe_path(ROOT,rel)
            except ValueError: pass
            else: raise AssertionError('escaped scope')
        assert safe_path(ROOT,'tools/fs_graphify.py')==Path(__file__).resolve()
        owners=json.loads((ROOT/'docs/collaboration/OWNERS.json').read_text(encoding='utf-8'))
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        validate_scope(config)
        bad=dict(config,version=0)
        try: validate_scope(bad)
        except ValueError: pass
        else: raise AssertionError('invalid scope version accepted')
        assert {m['moduleId'] for m in owners['modules']} <= config['modules'].keys()
        files,modules=inventory(ROOT,config)
        assert all(m['code_files']>0 and not m['missing_roots'] for m in modules)
        assert 'releases/fc-coins/fc-pricing-v3-20261026/source/conversation_http.py' in files
        assert 'releases/fs-dashboard/hermes-conversation-20261018/source/conversation_http.py' not in files
        print('scope boundaries, 17 owner modules, current HTTP source and legacy exclusion: PASS')
        return
    state=args.state.resolve()
    if state==ROOT or ROOT.is_relative_to(state):
        raise ValueError('state cannot contain the repository')
    state.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,GRAPHIFY_BACKEND='none',GRAPHIFY_NO_AUTO_REFRESH='1',GRAPHIFY_QUERY_LOG_DISABLE='1',PYTHONIOENCODING='utf-8')
    graph=state/'index/graphify-out/graph.json'
    config=json.loads(CONFIG.read_text(encoding='utf-8'))
    validate_scope(config)
    if args.action in ('query','affected'):
        if not args.question: p.error('question or exact symbol/path is required')
        manifest=json.loads((state/'scope.json').read_text(encoding='utf-8'))
        reasons=stale_reasons(manifest,config)
        if reasons:
            print('WARNING: stale graph ('+'; '.join(reasons)+'). Read current source; run update before treating this graph as current.',file=sys.stderr)
        cmd=[sys.executable,'-m','graphify',args.action,args.question,'--graph',str(graph)]
        if args.action=='query':
            cmd+=['--budget',str(args.budget)]
            for seed in args.seed: cmd+=['--seed',seed]
        subprocess.run(cmd,env=env,check=True)
        return
    files,modules=inventory(ROOT,config)
    head=git('rev-parse','HEAD').strip()
    manifest={'head':head,'worktree':worktree_state(files),'scope_config_sha256':hashlib.sha256(CONFIG.read_bytes()).hexdigest(),'scope_version':config['version'],'modules':modules,'files':{f:{'modules':names,'sha256':hashlib.sha256((ROOT/f).read_bytes()).hexdigest()} for f,names in sorted(files.items())},'limits':config['limits']}
    if args.action=='plan':
        (state/'plan.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'head':head,'modules':len(modules),'code_files':len(files),'scope':str(state/'plan.json')},ensure_ascii=False))
        return
    start=time.monotonic()
    corpus=state/'corpus'
    corpus.mkdir(exist_ok=True)
    previous=state/'scope.json'
    old=json.loads(previous.read_text(encoding='utf-8')) if previous.exists() else {'files':{}}
    for rel in old['files'].keys()-files.keys():
        f=safe_path(corpus,rel)
        if f.exists(): f.unlink()
    for rel,info in manifest['files'].items():
        dest=safe_path(corpus,rel)
        if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest()!=info['sha256']:
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/rel,dest)
    # extract reuses its official manifest/cache when the corpus is unchanged.
    cmd=[sys.executable,'-m','graphify','extract',str(corpus),'--code-only','--max-workers','2','--out',str(state/'index')]
    if old['files'].keys()-files.keys():
        # This graph is our derived corpus. A reviewed scope removal may shrink
        # it; normal unchanged/edited-file updates keep upstream's shrink guard.
        cmd.append('--force')
    subprocess.run(cmd,env=env,check=True)
    assert graph.is_file(), 'Graphify returned without a graph'
    data=json.loads(graph.read_text(encoding='utf-8'))
    assert data.get('nodes'), 'empty graph'
    # The corpus may be nested inside a different checkout. Upstream discovers
    # that enclosing Git HEAD; stamp the actual source checkout explicitly.
    data['built_at_commit']=head
    data.setdefault('graph',{})['fs_source_manifest_sha256']=hashlib.sha256(json.dumps(manifest['files'],sort_keys=True).encode()).hexdigest()
    staged_graph=graph.with_suffix('.json.tmp')
    staged_graph.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(staged_graph,graph)
    manifest['build']={'seconds':round(time.monotonic()-start,2),'nodes':len(data['nodes']),'edges':len(data.get('links',data.get('edges',[]))),'bytes':graph.stat().st_size,'graphify':'0.9.100','llm_backend':'none'}
    tmp=state/'scope.json.tmp'
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,previous)
    print(json.dumps(manifest['build'],ensure_ascii=False))


if __name__=='__main__':
    cli()
