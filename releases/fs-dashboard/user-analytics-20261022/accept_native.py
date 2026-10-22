"""One native model acceptance; inspect the original saved intent before any retry."""
import asyncio
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import aiohttp

SNAPSHOT=sys.argv[1]
EXPECTED=int(sys.argv[2])
assert re.fullmatch('us_[0-9a-f]{32}',SNAPSHOT),'frozen_snapshot_required'
ROOT=Path('/profile/user-analytics-acceptance-20261023')
ROOT.mkdir(mode=0o700,exist_ok=True)
STATE=ROOT/'native-v2.json'
assert not STATE.exists(),'inspect_original_native_intent_before_retry'
state=dict(snapshot_id=SNAPSHOT,phase='create_intent',started_at=time.time())


def save():
    fd,temp=tempfile.mkstemp(dir=ROOT)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as output:
            output.write(json.dumps(state,ensure_ascii=False,indent=2));output.flush();os.fsync(output.fileno())
        os.replace(temp,STATE)
    finally:
        if os.path.exists(temp):os.unlink(temp)


async def rpc(ws,method,params,rid):
    await ws.send_json(dict(jsonrpc='2.0',id=rid,method=method,params=params))
    while True:
        frame=await ws.receive(timeout=60)
        if frame.type!=aiohttp.WSMsgType.TEXT:raise RuntimeError('native_connection_closed')
        event=json.loads(frame.data)
        if event.get('id')==rid:
            if 'error' in event:raise RuntimeError('native_rpc_error_'+str(event['error'].get('code')))
            return event['result']


async def main():
    save();token=Path('/profile/.desktop-management/token').read_text().strip()
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect('http://127.0.0.1:8942/api/ws?token='+token,heartbeat=20) as ws:
            created=await rpc(ws,'session.create',dict(source='desktop',cwd='/profile',idempotency_key='fs-user-analytics-native-compact-v2-20261023'),1)
            state.update(runtime_session_id=created['session_id'],stored_session_id=created['stored_session_id'],phase='submit_intent');save()
            prompt=('这是用户分析上线的普通聊天原生工具验收。请实际使用fs_query_user_analytics，参数只有snapshot_id='+SNAPSHOT+
                    '，读取当前正式页面同一冻结快照。若工具延迟发现，使用tool_search和tool_call。不要terminal、execute_code、直接HTTP或读文件代替注册工具。'
                    '请只用一次必要聚合调用，以6句中文解释：已接入范围和日期、区间购买/已确认老客/首购待确认人数、期末阶段、支持证据与替代解释、历史/退款/卫星站缺口、负责人行动和具体复查日期。'
                    '保留snapshot_id，缺历史不称真实首购为0；不联系客户、不发券、不改价、不新建自动化，不做其他数据采集。')
            accepted=await rpc(ws,'prompt.submit',dict(session_id=state['runtime_session_id'],text=prompt),2)
            state.update(phase='running',accepted_status=accepted.get('status'));save()
            print('NATIVE_ACCEPTED '+str(accepted.get('status')),flush=True)
            deadline=time.monotonic()+420
            while time.monotonic()<deadline:
                try:frame=await ws.receive(timeout=45)
                except asyncio.TimeoutError:continue
                if frame.type!=aiohttp.WSMsgType.TEXT:raise RuntimeError('native_connection_closed')
                event=json.loads(frame.data).get('params',{});kind=event.get('type','')
                if kind in ('tool.start','tool.complete'):print('NATIVE_TOOL '+kind,flush=True)
                if kind in ('message.error','agent.error'):raise RuntimeError('native_turn_error')
                if kind=='message.complete':state.update(phase='completed',completion=event.get('payload',{}));save();break
            else:raise TimeoutError('native_acceptance_timeout_reconcile_original_session')
    with sqlite3.connect('file:/profile/state.db?mode=ro',uri=True) as db:
        rows=db.execute('SELECT role,tool_name,tool_calls,content FROM messages WHERE session_id=?',(state['stored_session_id'],)).fetchall()
    results=[]
    for role,name,calls,content in rows:
        if name=='fs_query_user_analytics':
            value=json.loads(content)
            if value.get('snapshot_id')==SNAPSHOT and value.get('metrics',{}).get('purchasers',{}).get('value')==EXPECTED:
                results.append(value)
    assert len(results)==1,'one_actual_native_result_with_matching_snapshot_and_count_required'
    assert len(json.dumps(results[0]))<20000,'native_summary_too_large'
    assert not any(r[1] in ('execute_code','terminal','read_file') for r in rows),'native_fallback_not_accepted'
    state.update(native_tool_acceptance='passed',purchasers=EXPECTED,completed_at=time.time());save()
    print(json.dumps(dict(native_tool_acceptance='passed',snapshot_id=SNAPSHOT,purchasers=EXPECTED,stored_session_id=state['stored_session_id'])),flush=True)


try:asyncio.run(main())
except Exception as error:
    state.update(error_type=type(error).__name__);save()
    print('NATIVE_RECONCILE '+type(error).__name__,flush=True)
    raise
