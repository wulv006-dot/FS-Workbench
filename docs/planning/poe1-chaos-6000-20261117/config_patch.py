"""Change only chaos sampling quantity; preserve other configuration/state."""
import fcntl, hashlib, json, os, sqlite3, sys
from pathlib import Path
ROOT=Path('/opt/d4follow')
RELEASE=Path('/opt/poe1-6000-release-20261117')
FIELD='采样目标数量'

def write(path,body):
    tmp=path.with_name(path.name+'.poe1-6000-tmp')
    with open(tmp,'wb') as stream:
        os.chmod(tmp,0o600);stream.write(body);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)

def main():
    mode=sys.argv[1]
    RELEASE.mkdir(mode=0o700,exist_ok=True)
    path=ROOT/'config.json';receipt=RELEASE/'config-delta.json'
    with open(ROOT/'data/.console-config.lock','a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        raw=path.read_bytes();cfg=json.loads(raw)
        matches=[x for x in cfg['POE1定价']['附加币种'] if x['key']=='chaos']
        if len(matches)!=1:raise RuntimeError('chaos group not unique')
        group=matches[0]
        assert [x['id'] for x in group['商品']]==['38588307','71488585']
        if mode=='prepare':
            if FIELD in group:raise RuntimeError('quantity already configured; inspect first')
            rec={'state':'prepared','before':{'exists':False,'value':None},'after':6000,
                 'before_sha':hashlib.sha256(raw).hexdigest()}
            with open(RELEASE/'config.before.json','xb') as stream:
                os.chmod(stream.name,0o600);stream.write(raw)
            with open(receipt,'x') as stream:json.dump(rec,stream,ensure_ascii=False,indent=2)
            print('prepared; production unchanged');return
        rec=json.loads(receipt.read_text())
        if mode=='apply':
            if rec['state']!='prepared' or FIELD in group:raise RuntimeError('config field CAS mismatch')
            group[FIELD]=6000
        elif mode=='rollback':
            if rec['state']!='applied' or group.get(FIELD)!=6000:raise RuntimeError('config field CAS mismatch')
            con=sqlite3.connect('file:'+str(ROOT/'data/iggm_follow.db')+'?mode=ro',uri=True)
            if con.execute("select count(*) from local_job where title like 'PoE1%' and status in ('pending','dispatched')").fetchone()[0]:
                raise RuntimeError('PoE1 jobs in flight; reconcile original jobs first')
            con.close()
            group.pop(FIELD)
        else:raise ValueError(mode)
        if path.read_bytes()!=raw:raise RuntimeError('config file CAS mismatch')
        write(path,(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode())
        rec.update(state='applied' if mode=='apply' else 'rolled-back',
                   after_sha=hashlib.sha256(path.read_bytes()).hexdigest())
        write(receipt,(json.dumps(rec,ensure_ascii=False,indent=2)+'\n').encode())
        print(json.dumps({'state':rec['state'],'changed_field':'POE1定价.附加币种[chaos].采样目标数量','value':group.get(FIELD)}))

if __name__=='__main__':main()
