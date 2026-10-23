"""One explicitly authorized, isolated real-model test; never replay an existing intent."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types


def verify(payloads, request_id, evidence_root):
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    intent = root / 'intent.json'
    if intent.exists():
        raise RuntimeError('original_request_exists_reconcile_without_resubmit')
    with tempfile.TemporaryDirectory(prefix='hermes-history-readonly-') as folder:
        home = Path(folder)
        os.environ['HERMES_HOME'] = str(home)
        os.environ['HOME'] = str(home)
        sys.path[:0] = ['/opt/hermes', '/fs-source']
        from hermes_cli import plugins
        from hermes_constants import get_hermes_home, profile_name_for_home
        from hermes_state import SessionDB
        from run_agent import AIAgent
        import knowledge_catalog
        module = types.ModuleType('isolated_candidate_knowledge')
        exec(compile(payloads['knowledge.py'], '<candidate_knowledge>', 'exec'), module.__dict__)
        fs = home / 'fs'; fs.mkdir(); (fs / 'admission.lock').touch()
        pointer = 'knowledge-releases/knowledge-layering-20261023-1/index.json'
        raw = (Path('/fs') / pointer).read_bytes()
        index = knowledge_catalog.validate(json.loads(raw))
        expected = 'ba2a0ad4b38028cf08a0b73e6d1529a2ba255a29bd5cbc483b5f8f8c9ee095ba'
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('published_history_test_source_changed')
        dest = fs / pointer; dest.parent.mkdir(parents=True); dest.write_bytes(raw)
        # Only formal rule/decision sources enter this test; no business report or customer data.
        for row in index['entries']:
            if row['id'] not in {'fc.marketing.attribution', 'fs.decision.pmax-authority-20261023'}:
                continue
            relative = Path(index['source_root']) / row['source']['path']
            data = (Path('/fs') / relative).read_bytes()
            if hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest() != row['source']['sha256']:
                raise ValueError('history_rule_source_changed')
            destination = fs / relative; destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        sid = 'history-readonly-20261023-01'
        profile = profile_name_for_home(get_hermes_home())
        info = dict(session_id=sid, platform='desktop', profile_name=profile)
        policy = dict(contract='fs-knowledge-load-policy-v1', requests={}, native=dict(enabled=True,
                      routes=[dict(platform='desktop', profile_name=profile, session_ids=[sid], catalog=pointer,
                                   sha256=expected, modules=['FC27'])], readonly_sessions={sid: {'task_ids': [request_id]}}))
        (fs / 'knowledge-load-policy.json').write_text(json.dumps(policy))
        adapter = module.NativeKnowledge(fs)
        adapter.pin(info)
        module.NativeKnowledge = lambda: adapter
        module.register(plugins.PluginContext(plugins.PluginManifest(name='isolated-history-readonly'), plugins.get_plugin_manager()))
        entry = types.ModuleType('isolated_candidate_entry')
        exec(compile(payloads['fs_native_entry.py'], '<candidate_entry>', 'exec'), entry.__dict__)
        entry.adapter = lambda: adapter
        events = []
        def emit(kind, payload):
            event = dict(jsonrpc='2.0', method='event', params=dict(type=kind, session_id=sid, payload=payload, seq=len(events)))
            events.append(event)
            with (root / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        database = SessionDB(db_path=home / 'state.db')
        database.create_session(sid, 'desktop', profile_name=profile)
        agent = entry.construct_fs_agent(AIAgent, model='deepseek-flash', provider='custom',
                    base_url='https://api.deepseek.com/v1', api_key=Path('/fs/secrets/deepseek.key').read_text().strip(),
                    session_id=sid, platform='desktop', session_db=database, enabled_toolsets=['fs_knowledge'],
                    quiet_mode=True, max_iterations=8, max_tokens=3500, run_budget_seconds=240,
                    tool_start_callback=lambda call, name, args: emit('tool.start', dict(tool_id=call, name=name, args=args)),
                    tool_complete_callback=lambda call, name, args, result: emit('tool.complete', dict(tool_id=call, name=name, args=args, result=result)))
        adapter.verify_test_agent(agent, sid, request_id)
        prompt = ('这是一次明确的历史知识检索验收，不是业务操作。请实际读取已发布知识，回答：'
                  'PMax-Coins-US在本知识版本保留的较早口径里如何定位？2026-10-22更正后的现行归属是什么？'
                  '2026-10-23的来源选择决策记录了谁确认、替代哪个原文、为什么选这份来源？'
                  '分别引用历史原文、当前原文、已确认决策的稳定ID和revision，区分文件版本日期、决定日期与未知的精确生效时刻。'
                  '不要拿当前内容冒充历史，不猜未记载的经营动机，不把历史口径恢复为当前规则。'
                  '仅查上述PMax正式规则和来源选择决策，不读取经营日报、订单、客户、记忆或技能；不执行写入。'
                  '不需要自报调用次数，实际调用由框架事件另行核验。最后给出实际release和读取选择哈希；总回答约800中文字。')
        with intent.open('x', encoding='utf-8') as stream:
            json.dump(dict(request_id=request_id, state='dispatch_intent', session_id=sid,
                           source_release=index['release'], prompt=prompt,
                           code_sha256={k: hashlib.sha256(v.encode()).hexdigest() for k, v in payloads.items()}), stream, ensure_ascii=False, indent=2)
        result = agent.run_conversation(prompt, task_id=request_id)
        final = result.get('final_response') or ''
        emit('message.complete', dict(status='complete' if result.get('completed', bool(final)) and final else 'unknown', text=final))
        (root / 'answer.md').write_text(final, encoding='utf-8')
        receipts = [json.loads(p.read_bytes()) for p in (fs / 'knowledge/native').glob('use-*.json')]
        (root / 'knowledge-uses.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2))
        provider_receipt = dict(request_id=request_id, state='completed_model_return',
                                final_text_sha256=hashlib.sha256(final.encode()).hexdigest(),
                                result_keys=sorted(result), api_calls=result.get('api_calls'))
        (root / 'provider-receipt.json').write_text(json.dumps(provider_receipt, ensure_ascii=False, indent=2))
        audit_module = types.ModuleType('isolated_knowledge_audit')
        exec(compile(payloads['knowledge_audit.py'], '<candidate_audit>', 'exec'), audit_module.__dict__)
        summary = audit_module.audit(events, sid)
        report = dict(request_id=request_id, state='completed' if summary['turn_complete'] else 'unknown-needs-reconcile',
                      isolation='actual Hermes image, separate process/profile/SessionDB, two real knowledge tools, real DeepSeek; candidate not deployed',
                      audit=summary, final_text_sha256=hashlib.sha256(final.encode()).hexdigest(),
                      result_keys=sorted(result), api_calls=result.get('api_calls'), source_commit=index['source_commit'],
                      release=index['release'], code_sha256={k: hashlib.sha256(v.encode()).hexdigest() for k, v in payloads.items()})
        (root / 'receipt.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        database.close()
        print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paid-model', action='store_true', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--evidence-root', required=True)
    args = parser.parse_args()
    verify(json.load(sys.stdin), args.request_id, args.evidence_root)
