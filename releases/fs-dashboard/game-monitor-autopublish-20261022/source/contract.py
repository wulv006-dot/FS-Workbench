"""Data-only game content updates; the existing page and executable code stay fixed."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from jsparse import Parser

MARKERS = {'game':'window.GAME_TIMELINE_DATA =', 'guide':'window.GAME_GUIDE =',
           'tools':'const GAME_TOOLS_MAP=', 'playbook':'const PLAYBOOK=', 'fallback_intel':'const SA_INTEL='}
DRAFT = 'Hermes经营草稿·待运营确认'
DEPTS = ['产品','设计','引流','投放','私域','邮件','广告','技术','生产']
DIMS = ['version','market','kol_social','seo','content','esports','exploit']

def require(ok, message):
    if not ok: raise ValueError(message)

def sha(raw): return hashlib.sha256(raw).hexdigest()

def strict_json(raw):
    def pairs(rows):
        out={}
        for key,value in rows:
            require(key not in out,'duplicate_json_key');out[key]=value
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False,'non_finite_json'))

def literal(text, marker):
    require(text.count(marker)==1,'literal_marker_ambiguous')
    i=text.index(marker)+len(marker)
    p=Parser(text,i);p.ws();start=p.i;value=p.value()
    return start,p.i,value

def members(text, start, array=False):
    p=Parser(text,start);require(text[p.i]==('[' if array else '{'),'literal_container_required');p.i+=1
    while True:
        p.ws()
        if text[p.i] in ']}':return
        key=None
        if not array:
            key=p.key();p.ws();require(text[p.i]==':','literal_colon');p.i+=1
        p.ws();begin=p.i;value=p.value();yield key,begin,p.i,value
        p.ws()
        if text[p.i]==',':p.i+=1
        else:require(text[p.i] in ']}','literal_separator')

def slots(text):
    result={};main_start,_,main=literal(text,MARKERS['game'])
    games=next(x for x in members(text,main_start) if x[0]=='games')
    identities=[g['key'] for g in main['games']]
    require(len(set(identities))==len(identities),'duplicate_game_identity')
    for _,start,end,game in members(text,games[1],True):result[game['key']]={'game':(start,end,game)}
    for block in ('guide','tools','playbook','fallback_intel'):
        start,end,table=literal(text,MARKERS[block])
        name='intel' if block=='fallback_intel' else block
        for key,a,b,value in members(text,start):
            if key in result:result[key][name]=(a,b,value)
        for key in result:
            if name not in result[key]:result[key][name]=(end-1,end-1,None)
    mapping=re.search(r'const GAMEBRIEFS=\{([^}]+)\}',text)
    require(mapping is not None,'brief_mapping_missing')
    for key,var in re.findall(r'"([a-z0-9-]+)"\s*:\s*([A-Z][A-Z0-9_]+)',mapping[1]):
        if key in result:result[key]['intel']=literal(text,'const '+var+'=')
    for key,marker in [('ea-sports-fc','window.FCBRIEF ='),('aion2','const AION2BRIEF=')]:
        if key in result:result[key]['intel']=literal(text,marker)
    return result

def snapshot(raw):
    text=raw.decode('utf8')
    return {key:{block:row[2] for block,row in value.items()} for key,value in slots(text).items()}

def safe_changes(old,new):
    if old==new:return
    require(isinstance(new,(dict,list,str,int,float,bool)) or new is None,'unsupported_value')
    if isinstance(new,str):
        require(len(new)<=15000 and not re.search(r'<|>|\$\{|javascript\s*:|data\s*:|file\s*:|ftp\s*:',new,re.I) and not new.startswith(('//','../')),'executable_content_refused')
        if new.startswith(('http:','https:')):
            url=urlsplit(new);require(url.scheme=='https' and url.hostname and not url.username and not url.password,'https_url_required')
    elif isinstance(new,dict):
        require(len(new)<=150,'object_too_large')
        for key,value in new.items():
            require(isinstance(key,str) and key not in ('__proto__','constructor','prototype'),'unsafe_property')
            safe_changes(old.get(key) if isinstance(old,dict) else None,value)
    elif isinstance(new,list):
        require(len(new)<=300,'array_too_large')
        for i,value in enumerate(new):safe_changes(old[i] if isinstance(old,list) and i<len(old) else None,value)

def sop(data):
    pb=data.get('playbook',{});gd=data.get('guide',{});tools=data.get('tools',{})
    require(80<=len(re.sub(r'\s','',pb.get('overview','')))<=150,'overview_length')
    require(100<=len(re.sub(r'\s','',pb.get('core','')))<=200,'core_length')
    require(3<=len(pb.get('tips',[]))<=5 and len(pb.get('gallery',[]))==4,'tips_gallery_count')
    biz=pb.get('biz',[]);require(4<=len(biz)<=7,'business_count')
    require(len({x['name'] for x in biz})==len(biz),'duplicate_business')
    require(all(1<=x['star']<=5 and DRAFT in x.get('desc','') and (x['star']<4 or all(x.get(k) for k in ('why','how','eff'))) for x in biz),'business_draft_contract')
    require([x[0] for x in pb.get('dept',[])]==DEPTS,'department_order')
    require(all(DRAFT in x[1] and len(x[1])>25 for x in pb['dept']),'department_draft_contract')
    require(all(DRAFT in x for x in pb['tips']),'tips_draft_contract')
    require(len(tools.get('tools',[]))>=4 and len(tools.get('wikis',[]))==2,'tools_wiki_count')
    require(all(urlsplit(x.get('url','')).scheme=='https' for x in tools['tools']+tools['wikis']),'tool_https_required')
    require(len(gd.get('classes',[]))>=1 and len(gd.get('clsDocs',[]))>=4,'class_depth_count')
    require(len({x['en'] for x in gd['clsDocs']})==len(gd['clsDocs']),'duplicate_class')
    require(all(all(x.get(k) for k in ('intro','str','weak','stat','gear','skills','loop','build','aud','tip')) for x in gd['clsDocs']),'class_depth_fields')
    require(4<=len(gd.get('play',[]))<=5 and len(gd.get('terms',[]))>=10 and 3<=len(gd.get('eco',[]))<=5 and len(gd.get('ops',[]))==4,'guide_counts')
    require(all(DRAFT in x[0] for x in gd['ops']),'operations_draft_contract')
    intel=data.get('intel',{})
    if 'cats' in intel:
        require([x['code'] for x in intel['cats']]==DIMS,'intelligence_dimensions')
        require(all(len(x['items'])>=2 for x in intel['cats']),'intelligence_items')
    else:
        require(set(DIMS)<=set(intel.get('items',{})),'intelligence_dimensions')
        require(all(isinstance(intel['items'][key],list) and len(intel['items'][key])>=2 for key in DIMS),'intelligence_items')

def build(before,request,now=None):
    require(set(request)=={'schema','run_id','base_sha256','updates','sources','summary'},'request_schema')
    require(request['schema']==1 and re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}',request['run_id']),'request_identity')
    require(request['base_sha256']==sha(before),'live_baseline_drift')
    require(isinstance(request['summary'],str) and 5<=len(request['summary'])<=1000,'change_summary_required')
    updates=request['updates'];require(isinstance(updates,dict) and 1<=len(updates)<=5,'bounded_game_batch')
    now=now or datetime.now(timezone.utc)
    require(isinstance(request['sources'],list) and 1<=len(request['sources'])<=100,'sources_required')
    covered=set()
    for source in request['sources']:
        require(set(source)=={'game','url','retrieved_at','version','claim','kind'},'source_schema')
        url=urlsplit(source['url'])
        require(url.scheme=='https' and url.hostname and not url.username and not url.password,'source_https_required')
        require(source['game'] in updates and source['kind'] in ('official','community','judgment'),'source_scope')
        require(source['version'] and len(source['claim'])>=10,'source_version_claim_required')
        stamp=datetime.fromisoformat(source['retrieved_at'].replace('Z','+00:00'))
        require(stamp.utcoffset() is not None and -60<=(now-stamp).total_seconds()<=14*86400,'fresh_source_time_required')
        covered.add(source['game'])
    require(covered==set(updates),'source_coverage_required')
    text=before.decode('utf8');available=slots(text);replacements=[];insertions={};changed=[]
    for game,blocks in updates.items():
        require(game in available and isinstance(blocks,dict) and blocks,'existing_game_required')
        data={k:copy.deepcopy(v[2]) for k,v in available[game].items()}
        for block,value in blocks.items():
            require(block in ('game','playbook','guide','tools','intel') and block in available[game],'existing_block_required')
            a,b,old=available[game][block]
            require(isinstance(value,dict),'data_object_required')
            if block=='game':
                fixed=set(old)-{'platforms','monetization','services','key_services','intro','platform_pricing','official_site','cover_url','asset_urls'}
                require(set(value)==set(old) and all(value[k]==old[k] for k in fixed),'game_identity_or_events_changed')
            safe_changes(old,value)
            if old!=value:
                encoded=json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
                if old is None:insertions.setdefault((a,b),[]).append(json.dumps(game)+':'+encoded)
                else:replacements.append((a,b,encoded))
                data[block]=value;changed.append(game+':'+block)
        sop(data)
    for (a,b),values in insertions.items():replacements.append((a,b,('' if text[:a].rstrip().endswith((',','{')) else ',')+','.join(values)))
    for a,b,value in sorted(replacements,reverse=True):text=text[:a]+value+text[b:]
    after=text.encode('utf8')
    require(len(after)<=4*1024*1024,'page_too_large')
    # Parsing each target again catches text-context and duplicate-property surprises.
    actual=snapshot(after);original=snapshot(before)
    for game in original:
        expected=copy.deepcopy(original[game])
        for block,value in updates.get(game,{}).items():expected[block]=value
        require(actual[game]==expected,'non_target_or_literal_drift')
    return after,{'schema':1,'run_id':request['run_id'],'before_sha256':sha(before),'after_sha256':sha(after),'changed':changed,'games':list(updates),'source_count':len(request['sources'])}

def verify_candidate(folder):
    request=strict_json((folder/'request.json').read_bytes())
    before=(folder/'before.html').read_bytes();after,proof=build(before,request)
    require(after==(folder/'index.html').read_bytes(),'candidate_bytes_drift')
    require(proof==strict_json((folder/'proof.json').read_bytes()),'candidate_proof_drift')
    return proof
