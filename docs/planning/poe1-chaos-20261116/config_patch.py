"""PoE1 chaos configuration delta; no credentials, no price writes."""
import copy, fcntl, hashlib, json, os, sqlite3, sys
from pathlib import Path

ROOT=Path('/opt/d4follow')
RELEASE=Path('/opt/poe1-chaos-release-20261116')
CFG=ROOT/'config.json'
CID=ROOT/'_p2pah_srv/item_cid.json'
CHAOS={'key':'chaos','币种名称':'Chaos Orb','启用':True,
       '来源URL':'https://www.dd373.com/s-mnh4dv-c-2u08tm-n75hgf-n4p04e.html',
       '最低成本':0.0001,'最高成本':10,
       'DD373':{'GameId':'a3b786c4-31db-4857-8686-6a55dc95f6dd',
                'GameOtherId':'14bb3f32-73d7-46b9-88d6-2443ded32523_865b86e20a834011864f881dff692549',
                'GameShopTypeId':'07b8af45-64d3-4caf-8b18-e48b04cf662b'},
       '商品':[{'id':'38588307','key':'POE1_CHAOS','名称':'Chaos Orb','倍数':1,
                '后台每份数量':1,'最少购买量':100},
               {'id':'71488585','key':'POE1_CHAOS_X1000','名称':'Chaos Orb(1000+100 Free)',
                '倍数':1000,'付费数量':1000,'赠送数量':100,'后台每份数量':1}]}
DELTAS=[('config',['POE1定价','附加币种'],[CHAOS]),
        ('config',['p2pah','商品ID映射','POE1_CHAOS'],'38588307'),
        ('config',['p2pah','商品ID映射','POE1_CHAOS_X1000'],'71488585'),
        ('config',['p2pah','商品所属游戏','POE1_CHAOS'],'流放之路1'),
        ('config',['p2pah','商品所属游戏','POE1_CHAOS_X1000'],'流放之路1'),
        ('cid',['games','157','id2cid','38588307'],'76'),
        ('cid',['games','157','id2cid','71488585'],'76')]

def get(doc,path):
    for key in path[:-1]: doc=doc.get(key,{})
    return {'exists':path[-1] in doc,'value':doc.get(path[-1])}

def put(doc,path,value):
    for key in path[:-1]: doc=doc.setdefault(key,{})
    if value['exists']: doc[path[-1]]=value['value']
    else: doc.pop(path[-1],None)

def atomic(path,body):
    tmp=path.with_name(path.name+'.chaos-tmp')
    with open(tmp,'wb') as stream:
        os.chmod(tmp,0o600)
        stream.write(body);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)

def encode(doc):return (json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode()

def main():
    mode=sys.argv[1]
    RELEASE.mkdir(mode=0o700,exist_ok=True)
    with open(ROOT/'data/.console-config.lock','a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        raw={'config':CFG.read_bytes(),'cid':CID.read_bytes()}
        docs={k:json.loads(v) for k,v in raw.items()}
        receipt=RELEASE/'config-delta.json'
        if mode=='prepare':
            assert docs['config']['POE1定价']['后台']=={'gid':'157','aid':'18858','cid':'76'}
            edits=[]
            for key,path,value in DELTAS:
                before=get(docs[key],path)
                if before['exists']: raise RuntimeError('field already exists: '+'.'.join(path))
                edits.append({'file':key,'path':path,'before':before,'after':{'exists':True,'value':value}})
            for key,body in raw.items():
                with open(RELEASE/(key+'.before.json'),'xb') as stream:
                    os.chmod(stream.name,0o600);stream.write(body)
            with open(receipt,'x') as stream: json.dump({'state':'prepared','edits':edits},stream,ensure_ascii=False,indent=2)
            print('prepared: 7 fields; production configuration unchanged')
            return
        rec=json.loads(receipt.read_text())
        if mode=='rollback':
            con=sqlite3.connect('file:'+str(ROOT/'data/iggm_follow.db')+'?mode=ro',uri=True)
            pending=con.execute("select id from local_job where title like 'PoE1%' and status in ('pending','dispatched')").fetchall()
            con.close()
            if pending: raise RuntimeError('PoE1 jobs in flight; reconcile original jobs first')
        elif mode!='apply': raise ValueError(mode)
        expected_state='prepared' if mode=='apply' else 'applied'
        if rec['state']!=expected_state: raise RuntimeError('receipt state '+rec['state'])
        for edit in rec['edits']:
            expect=edit['before' if mode=='apply' else 'after']
            if get(docs[edit['file']],edit['path'])!=expect: raise RuntimeError('field CAS conflict: '+'.'.join(edit['path']))
        for edit in rec['edits']:
            put(docs[edit['file']],edit['path'],edit['after' if mode=='apply' else 'before'])
        for key,path in [('cid',CID),('config',CFG)]:
            if path.read_bytes()!=raw[key]:raise RuntimeError('file CAS conflict: '+key)
        # Mapping first; the currency becomes active only in the final config write.
        atomic(CID,encode(docs['cid']))
        atomic(CFG,encode(docs['config']))
        rec['state']='applied' if mode=='apply' else 'rolled-back'
        rec['hashes']={key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in [('config',CFG),('cid',CID)]}
        atomic(receipt,encode(rec))
        print(json.dumps({'state':rec['state'],'changed_fields':len(rec['edits']),'price_writes':0}))

if __name__=='__main__':main()
