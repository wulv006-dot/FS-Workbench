"""Join existing private ES flags to normalized paid orders; no customer data to UI."""
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import re
import subprocess


def project_dataset(dataset, query):
    if dataset is None:return {'status':'missing'}
    complete=(dataset.get('status')=='available' and not dataset.get('parse_failures') and not dataset.get('failed_files') and type(dataset.get('declared_files')) is int and dataset['declared_files']==len(dataset.get('hashes',[])) and bool(dataset.get('hashes')))
    found={};conflicts=set();unknown_time=missing_keys=outside=0
    for row in dataset.get('rows',[]):
        if row.get('游戏','').strip()!='FC 27':continue
        ident=row.get('订单号','')
        if not re.fullmatch(r'[a-f0-9]{64}',ident):missing_keys+=1;continue
        try:when=datetime.strptime(row.get('付款时间',''),'%Y/%m/%d %H:%M:%S')
        except (ValueError,TypeError):unknown_time+=1;continue
        if not query['start']<=when.date().isoformat()<=query['end']:outside+=1;continue
        flag={'是':'new','否':'not_new'}.get(row.get('是否新客户','').strip(),'unknown')
        item={'order_hash':ident,'flag':flag,'payment_day':when.date().isoformat()}
        signature=row.get('_signature') or hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if ident in found and found[ident][1]!=signature:conflicts.add(ident)
        found[ident]=(item,signature)
    return {'status':'available' if complete and not (conflicts or unknown_time or missing_keys or outside) else 'partial',
            'rows':[item for ident,(item,_) in found.items() if ident not in conflicts],
            'coverage':{'file_set_complete':complete,'conflicting_orders':len(conflicts),'unknown_payment_time':unknown_time,'missing_order_hash':missing_keys,'outside_period':outside,'fc_es_orders':len(found),'declared_files':dataset.get('declared_files'),'read_files':len(dataset.get('hashes',[]))},
            'source_version':hashlib.sha256(json.dumps({'hashes':dataset.get('hashes'),'rule':'cohort-es-paid-join-v1'},sort_keys=True).encode()).hexdigest(),
            'captured_at':dataset.get('captured_at'),'origin':dataset.get('origin')}


def read_archive(query):
    """Existing container safely parses its archive; only pseudonymous flags leave it."""
    prefix='import sys,json,hashlib,re\nfrom datetime import datetime\nsys.path.insert(0,"/usr/local/bin")\nfrom es_order_structure import archived_dataset\n'
    script=prefix+inspect.getsource(project_dataset)+'\nq=json.loads(sys.argv[1])\nprint(json.dumps(project_dataset(archived_dataset(q),q),ensure_ascii=False))\n'
    result=subprocess.run(['docker','exec','-i','fc27-p2pah-session','python3','-',json.dumps({'profile':'FC27','start':query['start'],'end':query['end']})],input=script.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
    if result.returncode or len(result.stdout)>8*1024*1024:raise ValueError('cohort_es_archive_unavailable_or_size')
    value=json.loads(result.stdout)
    if value.get('status') not in ('available','partial','missing'):raise ValueError('cohort_es_archive_contract')
    return value


def archive_for(detail,query):
    value=read_archive(query)
    if value['status']=='missing':
        from es_order_structure import reader_for
        prior=reader_for(detail).get({'profile':'FC27','start':query['start'],'end':query['end'],'group_by':'new_customer','status':'all'})
        if prior.get('status') in ('available','partial'):
            value=read_archive(query)
            if value['status']!='missing':return value
        return {'status':'pending' if prior.get('status')=='pending' else 'unavailable','reason':'cohort_es_archive_not_ready','retryAfter':prior.get('retryAfter',3)}
    return value


def join_paid(rows,es,query):
    """All subsequent paid rows count; only acquisition anchors use ES new flags."""
    flags={r['order_hash']:r for r in es.get('rows',[])}
    selected=[];matched=missing=unknown=excluded=excluded_new=marked_new=stable_new=acquisition=day_mismatches=0
    identities={};conflicts=0
    for original in rows:
        row=dict(original);row['customer']='unknown'
        when=datetime.fromisoformat(row['paid_at']).astimezone(timezone(timedelta(hours=8)))
        row['paid_at']=when.isoformat()
        if query['start']<=when.date().isoformat()<=query['end']:
            acquisition+=1
            ident=hashlib.sha256(row['id'].encode()).hexdigest()
            flag=flags.get(ident)
            if flag is None:missing+=1
            else:
                matched+=1
                if flag.get('payment_day')!=when.date().isoformat():day_mismatches+=1
                if flag['flag']=='unknown':unknown+=1
                if flag['flag']=='new':
                    marked_new+=1
                    if row.get('customer_key'):row['customer']='new';stable_new+=1
                    else:excluded_new+=1
            if ident in identities and identities[ident]!=row.get('customer_key'):conflicts+=1
            identities[ident]=row.get('customer_key')
        if not row.get('customer_key'):excluded+=1;continue
        selected.append(row)
    return selected,{'link_complete':es.get('status')=='available' and not (missing or unknown or conflicts or day_mismatches),'acquisition_paid_orders':acquisition,'matched_es_orders':matched,'unmatched_es_orders':missing,'unknown_es_flags':unknown,'payment_day_mismatches':day_mismatches,'conflicting_order_identities':conflicts,'es_new_marked_paid_orders':marked_new,'stable_es_new_marked_paid_orders':stable_new,'excluded_identity_orders':excluded,'excluded_es_new_identity_orders':excluded_new,'es_source_version':es.get('source_version'),'es_file_coverage':es.get('coverage'),
        'excluded_identity_orders_scope':'分母范围：所选站点/平台从获取窗起日至complete_through的全部已付订单，含新/非新及后续付款；不是ES新客标记订单子集，不以es_new_marked_paid_orders为分母。',
        'excluded_identity_orders_unit':'订单，非去重客户人数',
        'excluded_es_new_identity_orders_scope':'分母：es_new_marked_paid_orders，即所选站点/平台获取窗内ES新客标记已付订单；不含获取窗外后续付款。',
        'excluded_es_new_identity_orders_unit':'订单，非去重客户人数'}
