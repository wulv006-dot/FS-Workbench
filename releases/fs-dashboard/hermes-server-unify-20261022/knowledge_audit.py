"""Derive native knowledge usage from turn events, never from assistant prose."""
import argparse
import json
from pathlib import Path

READ_TOOLS = {'fs_get_knowledge_index', 'fs_read_knowledge'}


def audit(events, session_id):
    starts, ends, sequences = {}, {}, {}
    complete = None
    for event in events:
        data = event.get('params', {})
        if data.get('session_id') != session_id:
            continue
        seq = data.get('seq')
        if seq is not None:
            if seq in sequences:
                if sequences[seq] != data:
                    raise ValueError('native_event_sequence_conflict')
                continue
            sequences[seq] = data
        kind, payload = data.get('type'), data.get('payload', {})
        if kind == 'message.complete':
            if complete is not None and complete != payload:
                raise ValueError('native_turn_completion_conflict')
            complete = payload
        if kind not in ('tool.start', 'tool.complete') or payload.get('name') not in READ_TOOLS:
            continue
        key = payload.get('tool_id')
        if not key:
            raise ValueError('native_tool_identity_missing')
        target = starts if kind == 'tool.start' else ends
        if key in target and target[key] != payload:
            raise ValueError('native_tool_event_conflict')
        target[key] = payload
    if set(ends) - set(starts):
        raise ValueError('native_tool_start_missing')
    calls = []
    for key, start in starts.items():
        end = ends.get(key)
        if end and end['name'] != start['name']:
            raise ValueError('native_tool_name_conflict')
        result = end.get('result') if end else None
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = None
        calls.append(dict(tool_id=key, tool=start['name'],
                          status=result.get('status', 'unknown') if isinstance(result, dict) else 'unknown',
                          args=end.get('args', {}) if end else start.get('args', {}),
                          selection_sha256=result.get('selection_sha256') if isinstance(result, dict) else None))
    return dict(contract='fs-native-knowledge-audit-v1', session_id=session_id,
                turn_complete=bool(complete and complete.get('status') == 'complete'),
                attempts=len(calls), index_attempts=sum(c['tool'] == 'fs_get_knowledge_index' for c in calls),
                content_attempts=sum(c['tool'] == 'fs_read_knowledge' for c in calls),
                content_successes=sum(c['tool'] == 'fs_read_knowledge' and c['status'] == 'available' for c in calls),
                failed_attempts=sum(c['status'] not in ('available', 'index_only', 'unknown') for c in calls),
                unknown_attempts=sum(c['status'] == 'unknown' for c in calls), calls=calls)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events', type=Path)
    parser.add_argument('--session-id', required=True)
    args = parser.parse_args()
    print(json.dumps(audit([json.loads(line) for line in args.events.read_text(encoding='utf-8').splitlines()],
                           args.session_id), ensure_ascii=False, indent=2))
