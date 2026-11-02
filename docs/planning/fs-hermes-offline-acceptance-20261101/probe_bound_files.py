"""Historical real-source boundary check; intentionally fails until property holds."""
import json,os,subprocess,sys,tempfile,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_support import read_sources,install_guard
ROOT=Path(__file__).resolve().parent
REPO=Path(os.environ.get('FS_ACCEPTANCE_REPO',str(ROOT.parents[2]))).resolve()
SHA='4e31c61ff39064377ce277e3c2dc55c5b7ee5b58'
names=['conversation_store','conversation_files','conversation_file_bindings']
sources=read_sources(REPO,SHA,{'conversation_store': 'releases/fs-dashboard/hermes-conversation-20261018/source/conversation_store.py', 'conversation_files': 'releases/fs-dashboard/hermes-conversation-20261018/source/conversation_files.py', 'conversation_file_bindings': 'releases/fs-dashboard/hermes-conversation-20261018/source/conversation_file_bindings.py'})
install_guard()
for name,source in sources.items():
    m=types.ModuleType(name);sys.modules[name]=m;exec(compile(source,SHA+':'+name,'exec'),m.__dict__)
from conversation_store import ConversationStore
from conversation_files import ConversationFiles
from conversation_file_bindings import context_factory
rows=[]
with tempfile.TemporaryDirectory() as directory:
    store=ConversationStore(directory);cid=store.create('synthetic-alice')['conversation_id']
    item=ConversationFiles(store).save('synthetic-alice',cid,'synthetic.csv',b'a,b\n1,2\n','upload_0001')
    turn=store.reserve_turn('synthetic-alice',cid,'Read fixture','turn_0001',[item['file_id']])['turn_id']
    store.set_state('synthetic-alice',cid,turn,'running')
    for value in (1,'false',{'allowed':False}):
        context=context_factory(store,'synthetic-alice',cid,turn,lambda _:value)
        try:context.read_table(item['file_id']);denied=False
        except PermissionError:denied=True
        rows.append({'input':value,'expected':'PermissionError','denied':denied})
print(json.dumps({'commit':SHA,'production_exploit_proven':False,'cases':rows}))
raise SystemExit(0 if all(r['denied'] for r in rows) else 1)
