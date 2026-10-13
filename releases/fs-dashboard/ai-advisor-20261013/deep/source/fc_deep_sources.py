"""Reuse FCDetails' queue/cache once, then derive every window from that same snapshot."""
from datetime import datetime, timezone
import hashlib
import json
import time
from fc_deep_analysis import build_evidence, plan, attach_diagnostics, fallback


class EvidenceReader:
    def __init__(self, detail, diagnostics=None, wait=time.sleep, monotonic=time.monotonic):
        self.detail,self.diagnostics,self.wait,self.monotonic=detail,diagnostics,wait,monotonic

    def capture(self, query_plan, timeout=920):
        params={k:[v] for k,v in {'mode':'fc-detail','profile':'FC27','grain':'day',
                                'start':query_plan['read_start'],'end':query_plan['read_end'],'site_group':'main'}.items()}
        deadline=self.monotonic()+timeout
        config=dict(self.detail.config)
        key=hashlib.sha256(json.dumps({'start':query_plan['read_start'],'end':query_plan['read_end'],'config':config},sort_keys=True).encode()).hexdigest()
        while self.monotonic()<deadline:
            code,result=self.detail.get(params)
            if code==403:raise PermissionError('source_permission_denied')
            if code==200 and not result.get('stale') and not result.get('refreshing'):
                # Exact cache used by the existing authenticated FCDetails instance.
                # Revalidate against its returned snapshot; never glob "latest" or pick by mtime.
                raw=json.loads((self.detail.cache/(key+'.json')).read_text('utf-8'))
                if raw['snapshot_id']!=result['snapshot_id'] or self.detail.config!=config:
                    raise ValueError('source_snapshot_changed')
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(raw['as_of'])).total_seconds()
                if not 0<=age<config['today_cache_seconds']:
                    raise ValueError('source_stale')
                return raw,config
            if code not in (200,202,429,503):raise ValueError('source_unavailable')
            if code==503 and result.get('data_status')=='unavailable':raise ValueError('source_unavailable')
            self.wait(3)
        raise ValueError('source_timeout')

    def collect_bundle(self, start, end, at, progress=None):
        query_plan=plan(start,end,at)
        if progress:progress('historical_comparison')
        raw,config=self.capture(query_plan)
        result=build_evidence(query_plan,raw,config,at)
        needs_order=any(j['kind']=='order_problem_sample' for j in result['investigations'])
        if needs_order:
            if progress:progress('problem_order_evidence')
            if self.diagnostics:
                try:diagnostics=self.diagnostics()
                except Exception:diagnostics={'status':'unavailable','reason':'diagnostic_read_failed'}
            else:diagnostics={'status':'not_configured','reason':'diagnostic_reader_missing'}
            attach_diagnostics(result,diagnostics)
        result['decision']=fallback(result)
        return result,raw,config

    def collect(self, start, end, at, progress=None):
        return self.collect_bundle(start,end,at,progress)[0]
