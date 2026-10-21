"""One native Desktop conversation proves that a model can use FS tools."""
import asyncio
import json
from pathlib import Path
import sqlite3
import time

import aiohttp

ROOT=Path('/profile/server-migration-20261022/tool-acceptance')
STATE=ROOT/'native-conversation.json'
assert not STATE.exists(), 'Inspect the original conversation before any retry'
state={'phase':'created_intent','started_at':time.time()}


def save():
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2))


async def rpc(ws,method,params,rid):
    await ws.send_json({'jsonrpc':'2.0','id':rid,'method':method,'params':params})
    while True:
        frame=await ws.receive(timeout=60)
        if frame.type!=aiohttp.WSMsgType.TEXT:raise RuntimeError('native_connection_closed')
        event=json.loads(frame.data)
        if event.get('id')==rid:
            if 'error' in event:raise RuntimeError('native_rpc_error_'+str(event['error'].get('code')))
            return event['result']


async def main():
    save()
    token=Path('/profile/.desktop-management/token').read_text().strip()
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect('http://127.0.0.1:8942/api/ws?token='+token,heartbeat=20) as ws:
            created=await rpc(ws,'session.create',{'source':'desktop','cwd':'/profile','idempotency_key':'fs-native-tool-acceptance-20261022'},1)
            state.update(runtime_session_id=created['session_id'],stored_session_id=created['stored_session_id'],phase='submit_intent')
            save()
            prompt=('这是一次服务器客户端原生工具验收。请用当前已注册的fs_get_data_catalog及fs_query_native_statistics查询FC27的2026-10-21至2026-10-21经营统计。'
                    '工具延迟发现时先tool_search搜索这两个工具，再tool_call；pending按原repeat_arguments和retryAfter继续。'
                    '不要execute_code、终端、读文件或直接HTTP代替注册工具；不要生成FS研究报告、改价、新建巡检或发消息。'
                    '结束只回复是否成功、来源日期及数据范围，不列销售金额。')
            accepted=await rpc(ws,'prompt.submit',{'session_id':state['runtime_session_id'],'text':prompt},2)
            state.update(phase='running',accepted_status=accepted.get('status'));save()
            print('NATIVE_PROMPT_ACCEPTED',accepted.get('status'),flush=True)
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                frame=await ws.receive(timeout=60)
                if frame.type!=aiohttp.WSMsgType.TEXT:raise RuntimeError('native_connection_closed')
                event=json.loads(frame.data).get('params',{})
                kind=event.get('type','')
                if kind in ('tool.start','tool.complete'):
                    print('NATIVE_TOOL_EVENT',kind,flush=True)
                if kind in ('message.error','agent.error'):raise RuntimeError('native_turn_error')
                if kind=='message.complete':
                    state.update(phase='completed',completion=event.get('payload',{}));save()
                    print('NATIVE_TURN_COMPLETE',flush=True)
                    break
            else:raise TimeoutError('native_tool_acceptance_timeout')
    c=sqlite3.connect('file:/profile/state.db?mode=ro',uri=True)
    rows=c.execute('SELECT role,tool_name,tool_calls FROM messages WHERE session_id=?',(state['stored_session_id'],)).fetchall()
    text=json.dumps(rows)
    used={name:name in text for name in ['fs_get_data_catalog','fs_query_native_statistics']}
    print('MODEL_USED_FS_TOOLS',json.dumps(used),flush=True)
    assert all(used.values()), 'Model did not use both registered FS tools'
    assert not any(row[1] in ('execute_code','terminal','read_file') for row in rows), 'Fallback is not native tool acceptance'
    state.update(native_tool_acceptance='passed',completed_at=time.time());save()


try:
    asyncio.run(main())
except Exception as error:
    state.update(error_type=type(error).__name__);save()
    print('ACCEPTANCE_STOPPED',type(error).__name__,flush=True)
    raise
