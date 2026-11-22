"""Sunday campaign drafts under a revocable user delegation; no stored sessions."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import re
import subprocess
import tempfile
import uuid

from pilot import digest,encoded
from campaign_public_sources import PublicSources

CONTRACT='campaign_weekly_run_v1'
RULES='fc27_weekly_selection_v1'
ENDPOINT='/internal/hermes/campaign-weekly'
ZONE=timezone(timedelta(hours=8),'Asia/Shanghai')
SCHEDULE=dict(weekday=6,hour=12,minute=0,timezone='Asia/Shanghai')
PREPARE_REJECTIONS={
    'WEEKLY_SBC_CORE_COVERAGE_INCOMPLETE','WEEKLY_SBC_CORE_POOL_EMPTY',
    'WEEKLY_SBC_COMPANION_POOL_INSUFFICIENT','WEEKLY_NEWEST_COVERAGE_INCOMPLETE',
    'WEEKLY_NEWEST_POOL_INSUFFICIENT','WEEKLY_NEWEST_POOL_UNVERIFIED',
    'WEEKLY_POPULAR_TOP_THREE_UNAVAILABLE',
}


def operation(value):
    if type(value) is not str or not re.fullmatch('[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}',value):raise ValueError('campaign_weekly_operation')
    return value


def node_cli(body):
    payload=encoded(body).encode()
    if len(payload)>1000000:raise ValueError('campaign_cli_input_size')
    with tempfile.TemporaryFile() as output:
        try:result=subprocess.run(['/usr/local/bin/node','/opt/fs-campaign-dashboard/analytics/weekly-cli.mjs'],input=payload,stdout=output,stderr=subprocess.DEVNULL,timeout=180)
        except subprocess.TimeoutExpired:raise RuntimeError('campaign_cli_outcome_unknown') from None
        output.seek(0);raw=output.read(1000001)
    if len(raw)>1000000:raise ValueError('campaign_cli_output_size')
    value=json.loads(raw)
    if type(value) is not dict or value.get('operation_id')!=body['operation_id']:raise ValueError('campaign_cli_identity')
    if result.returncode:
        code=value.get('error')
        known={'REVISION_CONFLICT','WEEKLY_SELECTION_RULE_MISMATCH','INVALID_WEEKLY_HERMES_INPUT','WEEKLY_OPERATION_OWNER_MISMATCH','REQUEST_CONFLICT'}
        if body['action']=='prepare' and value.get('status')=='failed':known.update(PREPARE_REJECTIONS)
        raise ValueError(code if code in known else 'campaign_cli_outcome_unknown')
    return value


def checked_trio_review(review):
    def model_id(value):
        return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value)

    def plain(value, limit):
        return isinstance(value, str) and 0 < len(value) <= limit and not re.search(r'[<>\x00-\x1f\x7f]', value)

    if (type(review) is not dict or set(review) != {'keep_model_id', 'exclude_model_ids', 'evidence'}
            or not model_id(review['keep_model_id'])):
        raise ValueError('campaign_trio_review')
    excluded = review['exclude_model_ids']
    if (type(excluded) is not list or len(excluded) != 2 or not all(map(model_id, excluded))
            or len(set(excluded)) != 2 or review['keep_model_id'] in excluded):
        raise ValueError('campaign_trio_review')
    from campaign_evidence import source_url
    if type(review['evidence']) is not list or not 1 <= len(review['evidence']) <= 5:
        raise ValueError('campaign_trio_review')
    for source in review['evidence']:
        if (type(source) is not dict or set(source) != {'url','title','observed_at','metric','sample','cards'}
                or not plain(source['title'], 180) or not plain(source['observed_at'], 40)):
            raise ValueError('campaign_trio_review')
        url = urlsplit(source_url(source['url']))
        if (url.hostname not in {'futbin.com','www.futbin.com','fut.gg','www.fut.gg'} or url.fragment
                or url.geturl() != source['url']
                or datetime.fromisoformat(source['observed_at'].replace('Z','+00:00')).tzinfo is None):
            raise ValueError('campaign_trio_review')
        metric, sample, cards = source['metric'], source['sample'], source['cards']
        if metric not in ('tier_votes', 'games_played', 'trend_rank') or type(cards) is not list or not 1 <= len(cards) <= 27:
            raise ValueError('campaign_trio_review')
        if (metric == 'tier_votes' and (type(sample) is not int or not 1 <= sample <= 100_000_000)
                or metric != 'tier_votes' and sample is not None):
            raise ValueError('campaign_trio_review')
        for card in cards:
            if (type(card) is not dict or set(card) != {'model_id','item_id','rating','version','value'}
                    or not model_id(card['model_id']) or not model_id(card['item_id'])
                    or type(card['rating']) is not int or not 1 <= card['rating'] <= 99
                    or not plain(card['version'], 80)):
                raise ValueError('campaign_trio_review')
            value = card['value']
            if (metric == 'tier_votes' and value not in ('S','A','B','C','D','F')
                    or metric != 'tier_votes' and (type(value) is not int or not 1 <= value <= 100_000_000)):
                raise ValueError('campaign_trio_review')
    return review


def reviewed_trio_evidence(review, players):
    current = {str(player['model_id']): player['name'].rsplit('/', 3) for player in players}
    keep, excluded = review['keep_model_id'], review['exclude_model_ids']
    if keep not in current:
        raise ValueError('WEEKLY_TRIO_REVIEW_MISMATCH')
    context = (f'This manual Trio review requires: keep Admin model {keep}; omit {", ".join(excluded)}. '
               'Choose two other cards with their own cited version-level evidence below. Preserve the default Admin price preference. '
               'Consider usage/popularity and team fit before price within budget; do not rank the cards by lowest price. '
               'A tier-vote sample is the total ballots for the tier list, not games played, sales, or votes for that one card. '
               'State a metric gap when the exact card has no observed usage data. Cite each matching source index.\n')
    sources, supported = [], set()
    for index, source in enumerate(review['evidence']):
        sources.append({field:source[field] for field in ('url','title','observed_at')})
        metric = source['metric']
        for card in source['cards']:
            model_id = card['model_id']
            if model_id not in current:
                continue
            card_title = current[model_id]
            if len(card_title) != 4 or card_title[1].strip() != str(card['rating']) or card_title[3].strip().casefold() != card['version'].casefold():
                raise ValueError('WEEKLY_TRIO_REVIEW_MISMATCH')
            sample = f" in a list with {source['sample']} total ballots" if metric == 'tier_votes' else ''
            context += (f"Source {index}: Admin model {model_id}, FC27 item {card['item_id']}, "
                        f"{card['rating']} {card['version']}, {metric} = {card['value']}{sample}.\n")
            supported.add(model_id)
    if len(supported - {keep, *excluded}) < 2:
        raise ValueError('WEEKLY_TRIO_REVIEW_MISMATCH')
    return dict(status='partial', sources=sources, context=context, coverage=dict(
        players=len(players), verified_documents=len(sources), categories=['card_version'],
        version_matched_cards=len(supported), failures=[] if any(source['metric']=='games_played' for source in review['evidence']) else ['card_version_games_unobserved']))


def check_trio_review_result(prepared, model_result):
    review = prepared.get('trio_review')
    if not review:
        return
    keys = {player['key']:str(player['model_id']) for player in prepared['trio_players']}
    choices = {keys[row['product_key']]: row for row in model_result['recommendations']
               if row['page_id']=='fc27-trio' and row['product_key'] in keys}
    keep, excluded = review['keep_model_id'], review['exclude_model_ids']
    if len(choices) != 3 or keep not in choices or set(choices).intersection(excluded):
        raise ValueError('WEEKLY_TRIO_REVIEW_MISMATCH')
    for model_id, row in choices.items():
        if model_id == keep:
            continue
        if not any(i in row['evidence_indices'] and any(card['model_id']==model_id for card in source['cards'])
                   for i, source in enumerate(review['evidence'])):
            raise ValueError('WEEKLY_TRIO_REVIEW_MISMATCH')


class CampaignDelegation:
    campaign_delegation=True
    def __init__(self,scheduler,owner,revision):self.scheduler,self.owner,self.revision=scheduler,owner,revision
    def authorized(self,host,owner):
        if self.scheduler.host is not host or getattr(host,'campaign_weekly',None) is not self.scheduler or owner!=self.owner:return False
        grant=self.scheduler.config()
        return grant['enabled'] is True and grant['owner']==owner and grant['revision']==self.revision and host.authorizer(owner) is True


class CampaignWeekly:
    def __init__(self,host,recommendations,*,cli=node_cli,evidence=None):
        self.host,self.recommendations,self.cli=host,recommendations,cli
        self.evidence=evidence
        self.public_sources=PublicSources(host.tasks,clock=host.clock)
        with host.tasks.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS campaign_weekly_grant(id INTEGER PRIMARY KEY,revision INTEGER,owner TEXT,enabled INTEGER,operation_id TEXT,granted_at TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS campaign_weekly_changes(owner TEXT,operation_id TEXT,request_hash TEXT,result TEXT,PRIMARY KEY(owner,operation_id))')
            db.execute('CREATE TABLE IF NOT EXISTS campaign_weekly_runs(operation_id TEXT PRIMARY KEY,owner TEXT,trigger TEXT,due_day TEXT UNIQUE,grant_revision INTEGER,state TEXT,stage TEXT,prepared TEXT,model_input TEXT,result TEXT,created_at TEXT)')
            # The original model and center IDs survive a host restart; no stage is automatically replayed.
            db.execute("UPDATE campaign_weekly_runs SET state='unknown' WHERE state='pending'")
        host.campaign_weekly=self
    def config(self):
        with self.host.tasks.db() as db:row=db.execute('SELECT * FROM campaign_weekly_grant WHERE id=1').fetchone()
        return dict(revision=row['revision'],owner=row['owner'],enabled=bool(row['enabled']),operation_id=row['operation_id'],schedule=SCHEDULE,scope='prepare_model_apply_center_draft',publication=False) if row else dict(revision=0,owner=None,enabled=False,operation_id=None,schedule=SCHEDULE,scope='prepare_model_apply_center_draft',publication=False)
    def configure(self,body,owner,cookie):
        if type(cookie) is not str:raise PermissionError('campaign_session_required')
        self.recommendations.authorized(owner,cookie)
        if type(body) is not dict or set(body)!={'action','operation_id','revision','enabled'} or body['action']!='configure' or type(body['revision']) is not int or body['revision']<0 or type(body['enabled']) is not bool:raise ValueError('campaign_schedule_fields')
        operation(body['operation_id']);request_hash=digest(body)
        with self.host.tasks.db() as db:
            db.execute('BEGIN IMMEDIATE');prior=db.execute('SELECT request_hash,result FROM campaign_weekly_changes WHERE owner=? AND operation_id=?',(owner,body['operation_id'])).fetchone()
            if db.execute('SELECT 1 FROM campaign_weekly_runs WHERE operation_id=?',(body['operation_id'],)).fetchone():raise ValueError('campaign_request_conflict')
            if prior:
                if prior['request_hash']!=request_hash:raise ValueError('campaign_request_conflict')
                return json.loads(prior['result'])
            row=db.execute('SELECT revision FROM campaign_weekly_grant WHERE id=1').fetchone();revision=row[0] if row else 0
            if revision!=body['revision']:raise ValueError('campaign_schedule_revision')
            value=dict(status='configured',operation_id=body['operation_id'],revision=revision+1,owner=owner,enabled=body['enabled'],schedule=SCHEDULE,scope='prepare_model_apply_center_draft',publication=False)
            db.execute('INSERT OR REPLACE INTO campaign_weekly_grant VALUES(1,?,?,?,?,?)',(revision+1,owner,int(body['enabled']),body['operation_id'],self.host.clock().isoformat()))
            db.execute('INSERT INTO campaign_weekly_changes VALUES(?,?,?,?)',(owner,body['operation_id'],request_hash,encoded(value)))
        return value
    def _record(self,key,owner):
        operation(key)
        with self.host.tasks.db() as db:row=db.execute('SELECT * FROM campaign_weekly_runs WHERE operation_id=? AND owner=?',(key,owner)).fetchone()
        return dict(row) if row else None
    def lookup(self,key,owner,authority):
        self.recommendations.authorized(owner,authority);row=self._record(key,owner)
        if row is None:
            with self.host.tasks.db() as db:grant=db.execute('SELECT result FROM campaign_weekly_changes WHERE owner=? AND operation_id=?',(owner,key)).fetchone()
            if grant:return json.loads(grant['result'])
            raise LookupError('campaign_weekly_not_found')
        return json.loads(row['result']) if row['result'] else dict(status=row['state'],operation_id=key,stage=row['stage'],trigger=row['trigger'],publication=False)
    def status(self,owner,cookie):
        self.recommendations.authorized(owner,cookie)
        with self.host.tasks.db() as db:rows=db.execute('SELECT operation_id,state,stage,trigger,created_at,result FROM campaign_weekly_runs WHERE owner=? ORDER BY rowid DESC LIMIT 20',(owner,)).fetchall()
        return dict(config=self.config(),runs=[dict(row) | {'result':json.loads(row['result']) if row['result'] else None} for row in rows])
    def run(self,key,owner,authority,*,trigger='manual',due_day=None,trio_review=None):
        operation(key);self.recommendations.authorized(owner,authority)
        if trigger not in ('manual','scheduled') or trigger=='scheduled' and not isinstance(authority,CampaignDelegation):raise PermissionError('campaign_delegation_required')
        if trio_review is not None:
            if trigger != 'manual' or not isinstance(authority, str):
                raise PermissionError('campaign_manual_review_required')
            trio_review=checked_trio_review(trio_review)
        revision=authority.revision if isinstance(authority,CampaignDelegation) else None
        with self.host.tasks.db() as db:
            db.execute('BEGIN IMMEDIATE');prior=db.execute('SELECT owner,prepared FROM campaign_weekly_runs WHERE operation_id=?',(key,)).fetchone()
            if db.execute('SELECT 1 FROM campaign_weekly_changes WHERE operation_id=?',(key,)).fetchone():raise ValueError('campaign_request_conflict')
            if prior:
                if prior['owner']!=owner:raise PermissionError('campaign_owner')
                existing=json.loads(prior['prepared']) if prior['prepared'] else {}
                if existing.get('trio_review')!=trio_review:raise ValueError('campaign_request_conflict')
            else:
                initial=encoded({'trio_review':trio_review}) if trio_review is not None else None
                db.execute("INSERT INTO campaign_weekly_runs VALUES(?,?,?,?,?,'pending','prepare',?,NULL,NULL,?)",
                           (key,owner,trigger,due_day,revision,initial,self.host.clock().isoformat()))
        if prior:return self.lookup(key,owner,authority)
        try:self.host.pool.submit(self._execute,key,owner,authority,trio_review)
        except RuntimeError:self._update(key,state='failed',result=dict(status='failed',operation_id=key,error='campaign_queue_unavailable',publication=False))
        return self.lookup(key,owner,authority)
    def _update(self,key,**values):
        allowed={'state','stage','prepared','model_input','result'}
        if set(values)-allowed:raise ValueError('campaign_weekly_update')
        fields={name:encoded(value) if name in ('prepared','model_input','result') else value for name,value in values.items()}
        with self.host.tasks.db() as db:db.execute('UPDATE campaign_weekly_runs SET '+','.join(name+'=?' for name in fields)+' WHERE operation_id=?',tuple(fields.values())+(key,))
    def _execute(self,key,owner,authority,trio_review=None):
        stage='prepare';evidence=None
        try:
            self.recommendations.authorized(owner,authority)
            prepared=self.cli(dict(contract=CONTRACT,action='prepare',operation_id=key,owner=owner))
            self.recommendations.authorized(owner,authority)
            if prepared.get('status')=='disabled':
                self._update(key,state='disabled',result=dict(status='disabled',operation_id=key,stage=stage,reason='hermes_disabled',publication=False));return
            if prepared.get('status')!='prepared' or prepared.get('operation_id')!=key or prepared.get('rules_version')!=RULES:raise ValueError('campaign_prepare_contract')
            operation(prepared.get('plan_ref'));value=prepared['input']
            if trio_review is not None:prepared['trio_review']=trio_review
            self._update(key,prepared=prepared,stage='evidence');stage='evidence'
            players=prepared.get('trio_players')
            if type(players) is not list or not 1<=len(players)<=300:raise ValueError('campaign_player_pool')
            if trio_review is not None:
                evidence=reviewed_trio_evidence(trio_review,players)
            elif self.evidence is None:
                from campaign_evidence import collect_player_evidence
                evidence=collect_player_evidence([dict(name=p['name'].split('/',1)[0].strip(),model_id=p['model_id']) for p in players],self.host.clock())
            else:evidence=self.evidence(players,self.host.clock())
            prepared['research']=dict(status=evidence.get('status'),coverage=evidence.get('coverage'))
            self._update(key,prepared=prepared)
            self.recommendations.authorized(owner,authority)
            original=value['sbc_update']['sources'];value['sbc_update']['sources']=evidence['sources']+original
            value['sbc_update']['context']+='\nTrio external evidence (source indices start at 0; prior SBC source indices shift by '+str(len(evidence['sources']))+'):\n'+evidence['context']
            if trio_review is None:
                value['sbc_update']['context']+='\nWhere external evidence is partial or absent, infer from the real product metadata only; leave evidence_indices empty and state that the inference is not externally verified. This is a provisional draft for review, not publication.'
            from campaign_recommendations import checked_input
            value=checked_input(value)
            current=self.cli(dict(contract=CONTRACT,action='prepare',operation_id=key,owner=owner))
            self.recommendations.authorized(owner,authority)
            if current.get('status')=='disabled':
                self._update(key,state='disabled',result=dict(status='disabled',operation_id=key,stage=stage,reason='hermes_disabled',publication=False,evidence_coverage=evidence.get('coverage')));return
            if current.get('status')!='prepared' or current.get('plan_ref')!=prepared['plan_ref'] or current.get('input',{}).get('source_revision')!=value['source_revision']:raise ValueError('campaign_prepare_contract')
            self._update(key,model_input=value,stage='model');stage='model'
            body=dict(contract='campaign_recommendation_v1',operation_id=key,input=value)
            admitted=self.recommendations.submit(body,owner,authority,dispatch=False)
            if admitted['status']=='pending':self.recommendations._execute(owner,key,authority)
            model=self.recommendations.lookup(key,owner,authority) if admitted['status']=='pending' else admitted
            if model['status']!='completed':
                self._update(key,state=model['status'],result=dict(model,publication=False,evidence_coverage=evidence.get('coverage'),external_status=evidence.get('status')));return
            check_trio_review_result(prepared,model['result'])
            self.recommendations.authorized(owner,authority);self._update(key,stage='apply_draft');stage='apply_draft'
            applied=self.cli(dict(contract=CONTRACT,action='apply_draft',operation_id=key,owner=owner,plan_ref=prepared['plan_ref'],recommendation=model['result'],evidence_sources=value['sbc_update']['sources']))
            if applied.get('status')=='disabled':
                self._update(key,state='disabled',result=dict(status='disabled',operation_id=key,stage=stage,reason='hermes_disabled',publication=False,receipt=model.get('receipt'),can_resume=True,evidence_coverage=evidence.get('coverage')));return
            if applied.get('status')!='draft_saved' or applied.get('operation_id')!=key:raise ValueError('campaign_apply_contract')
            self._update(key,state='completed',result=dict(status='completed',operation_id=key,publication=False,draft=applied,receipt=model.get('receipt'),evidence_coverage=evidence.get('coverage'),external_status=evidence.get('status'),provisional=evidence.get('status')!='available',review_required=True))
        except Exception as error:
            # An interrupted model or draft save retains its original ID; status refresh never dispatches it again.
            known={'REVISION_CONFLICT','WEEKLY_SELECTION_RULE_MISMATCH','WEEKLY_TRIO_REVIEW_MISMATCH','INVALID_WEEKLY_HERMES_INPUT','WEEKLY_OPERATION_OWNER_MISMATCH'}
            state='unknown' if stage in ('model','apply_draft') and str(error) not in known else 'failed'
            codes=known|{'REQUEST_CONFLICT','campaign_prepare_contract','campaign_player_pool','campaign_apply_contract','campaign_cli_failed','campaign_cli_outcome_unknown','campaign_session_required'}
            if stage in ('prepare','evidence'):codes.update(PREPARE_REJECTIONS)
            model_record=self.recommendations._record(key,owner)
            model_result=json.loads(model_record['result']) if model_record and model_record['result'] else {}
            self._update(key,state=state,result=dict(status=state,operation_id=key,stage=stage,error=str(error) if type(error) in (ValueError,RuntimeError,PermissionError) and str(error) in codes else 'campaign_weekly_failed',error_type=type(error).__name__,publication=False,evidence_coverage=evidence.get('coverage') if evidence else None,receipt=model_result.get('receipt')))
    def supplement_sources(self,key,owner,cookie,request):
        operation(key)
        self.recommendations.authorized(owner,cookie)
        with self.host.tasks.db() as db:
            if any(db.execute('SELECT 1 FROM '+table+' WHERE operation_id=?',(key,)).fetchone()
                   for table in ('campaign_weekly_runs','campaign_weekly_changes')):
                raise ValueError('campaign_request_conflict')
        return self.public_sources.submit(key,owner,request)

    def reconcile(self,key,owner,authority):
        self.recommendations.authorized(owner,authority)
        source_receipt=self.public_sources.lookup(operation(key),owner)
        if source_receipt:
            return source_receipt
        row=self._record(key,owner)
        if row is None:return self.lookup(key,owner,authority)
        if row['state'] not in ('unknown','awaiting_apply','disabled'):return self.lookup(key,owner,authority)
        prepared=json.loads(row['prepared']) if row['prepared'] else None
        if row['stage']=='apply_draft' and prepared:
            inspected=self.cli(dict(contract=CONTRACT,action='inspect_operation',operation_id=key,owner=owner,plan_ref=prepared['plan_ref']))
            self.recommendations.authorized(owner,authority)
            if inspected.get('status')=='draft_saved':
                model=self.recommendations.lookup(key,owner,authority)
                result=dict(status='completed',operation_id=key,publication=False,draft=inspected,receipt=model.get('receipt'),evidence_coverage=prepared.get('research',{}).get('coverage'),reconciled=True)
                return self._reconcile_result(row,result,owner,authority)
        if row['stage'] in ('model','apply_draft'):
            model=self.recommendations.lookup(key,owner,authority)
            if row['stage']=='model' and model['status'] in ('unavailable','failed'):
                result=dict(model,publication=False,evidence_coverage=prepared.get('research',{}).get('coverage') if prepared else None,external_status=prepared.get('research',{}).get('status') if prepared else None,reconciled=True)
                return self._reconcile_result(row,result,owner,authority)
            if model['status']=='completed':
                result=dict(status='awaiting_apply' if row['stage']=='model' else 'unknown',operation_id=key,publication=False,receipt=model.get('receipt'),can_resume=True,evidence_coverage=prepared.get('research',{}).get('coverage') if prepared else None)
                return self._reconcile_result(row,result,owner,authority)
        return self.lookup(key,owner,authority)
    def _reconcile_result(self,row,result,owner,authority):
        # A read begun before resume/apply finishes must not overwrite the newer result.
        with self.host.tasks.db() as db:
            changed=db.execute('UPDATE campaign_weekly_runs SET state=?,result=? WHERE operation_id=? AND owner=? AND state=? AND stage=? AND result IS ?',
                (result['status'],encoded(result),row['operation_id'],owner,row['state'],row['stage'],row['result']))
        return result if changed.rowcount==1 else self.lookup(row['operation_id'],owner,authority)
    def resume(self,key,owner,cookie):
        if type(cookie) is not str:raise PermissionError('campaign_manual_resume_required')
        result=self.reconcile(key,owner,cookie)
        if result.get('status')=='completed':return result
        if result.get('can_resume') is not True:raise ValueError('campaign_original_model_unresolved')
        with self.host.tasks.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("UPDATE campaign_weekly_runs SET state='pending',stage='apply_draft',result=NULL WHERE operation_id=? AND owner=? AND state IN ('unknown','awaiting_apply')",(key,owner))
        if changed.rowcount!=1:return self.lookup(key,owner,cookie)
        try:self.host.pool.submit(self._apply_existing,key,owner,cookie)
        except RuntimeError:self._update(key,state='unknown',result=result)
        return self.lookup(key,owner,cookie)
    def _apply_existing(self,key,owner,authority):
        row=self._record(key,owner);prepared=json.loads(row['prepared']);value=json.loads(row['model_input'])
        try:
            self.recommendations.authorized(owner,authority);model=self.recommendations.lookup(key,owner,authority)
            if model['status']!='completed':raise ValueError('campaign_original_model_unresolved')
            check_trio_review_result(prepared,model['result'])
            result=self.cli(dict(contract=CONTRACT,action='apply_draft',operation_id=key,owner=owner,plan_ref=prepared['plan_ref'],recommendation=model['result'],evidence_sources=value['sbc_update']['sources']))
            if result.get('status')=='disabled':
                self._update(key,state='disabled',result=dict(status='disabled',operation_id=key,stage='apply_draft',reason='hermes_disabled',can_resume=True,publication=False,receipt=model.get('receipt'),evidence_coverage=prepared.get('research',{}).get('coverage')));return
            if result.get('status')!='draft_saved' or result.get('operation_id')!=key:raise ValueError('campaign_apply_contract')
            self._update(key,state='completed',result=dict(status='completed',operation_id=key,publication=False,draft=result,receipt=model.get('receipt'),evidence_coverage=prepared.get('research',{}).get('coverage'),resumed=True))
        except Exception as error:
            known={'REVISION_CONFLICT','WEEKLY_SELECTION_RULE_MISMATCH','WEEKLY_TRIO_REVIEW_MISMATCH','INVALID_WEEKLY_HERMES_INPUT','WEEKLY_OPERATION_OWNER_MISMATCH'}
            state='failed' if type(error) is ValueError and str(error) in known else 'unknown'
            safe=str(error) if type(error) in (ValueError,RuntimeError) and str(error) in known|{'REQUEST_CONFLICT','campaign_apply_contract','campaign_cli_outcome_unknown','campaign_original_model_unresolved'} else 'campaign_original_apply_unresolved'
            model_record=self.recommendations._record(key,owner);model_result=json.loads(model_record['result']) if model_record and model_record['result'] else {}
            self._update(key,state=state,result=dict(status=state,operation_id=key,publication=False,stage='apply_draft',error=safe,error_type=type(error).__name__,evidence_coverage=prepared.get('research',{}).get('coverage'),receipt=model_result.get('receipt')))
    def tick(self):
        with self.host.lock:self._tick()
    def _tick(self):
        grant=self.config()
        if not grant['enabled'] or not grant['owner']:return
        now=self.host.clock().astimezone(ZONE)
        if now.weekday()!=6 or now.hour<12:return
        authority=CampaignDelegation(self,grant['owner'],grant['revision'])
        self.recommendations.authorized(grant['owner'],authority);day=now.date().isoformat()
        with self.host.tasks.db() as db:old=db.execute('SELECT operation_id FROM campaign_weekly_runs WHERE due_day=?',(day,)).fetchone()
        if old:return
        self.run(str(uuid.uuid4()),grant['owner'],authority,trigger='scheduled',due_day=day)


def handle(handler,method,uri,service):
    if uri.path!=ENDPOINT:return False
    from conversation_http import read_json,respond
    try:
        if service is None:respond(handler,503,{'error':'campaign_weekly_unavailable'});return True
        owner=handler.headers.get('X-FS-Actor');cookie=handler.headers.get('Cookie','')
        if method=='GET':
            query=parse_qs(uri.query,keep_blank_values=True,max_num_fields=1)
            if not query:result=service.status(owner,cookie)
            elif set(query)=={'operation_id'} and len(query['operation_id'])==1:result=service.reconcile(query['operation_id'][0],owner,cookie)
            else:raise ValueError('campaign_weekly_query')
        elif method=='POST':
            if uri.query or handler.headers.get('X-FS-Advisor-Action')!='submit' or handler.headers.get('Sec-Fetch-Site')!='same-origin':raise PermissionError('campaign_weekly_origin')
            body=read_json(handler,maximum=6500)
            if body.get('action')=='supplement_sources' and set(body)=={'action','operation_id','sources'}:
                result=service.supplement_sources(body['operation_id'],owner,cookie,body['sources'])
            elif body.get('action')=='configure':result=service.configure(body,owner,cookie)
            elif body.get('action')=='run' and set(body) in ({'action','operation_id'},{'action','operation_id','trio_review'}):
                if 'trio_review' in body and body['trio_review'] is None:raise ValueError('campaign_trio_review')
                result=service.run(body['operation_id'],owner,cookie,trio_review=body.get('trio_review'))
            elif set(body)=={'action','operation_id'} and body['action']=='reconcile':result=service.reconcile(body['operation_id'],owner,cookie)
            elif set(body)=={'action','operation_id'} and body['action']=='resume':result=service.resume(body['operation_id'],owner,cookie)
            else:raise ValueError('campaign_weekly_fields')
        else:raise ValueError('campaign_weekly_method')
        respond(handler,202 if result.get('status')=='pending' else 200,result)
    except PermissionError:respond(handler,403,{'error':'campaign_session_required'})
    except LookupError:respond(handler,404,{'error':'campaign_weekly_not_found'})
    except (ValueError,TypeError,KeyError):respond(handler,422,{'error':'campaign_weekly_invalid_request'})
    except Exception:respond(handler,503,{'error':'campaign_weekly_unavailable'})
    return True
