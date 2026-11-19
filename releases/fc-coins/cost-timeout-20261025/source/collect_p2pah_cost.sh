#!/bin/sh
set -eu
umask 077
evidence=/var/lib/fc27-cloud/evidence
state=/var/lib/fc27-cloud/state
mkdir -p -m 0700 "$evidence" "$state"
exec 9>"$state/p2pah-cost.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
trace=$(mktemp "$evidence/p2pah-cost-XXXXXXXX.tmp")
collector_exit=0
if timeout 180s docker run --rm --init --memory 2g --memory-swap 2g --env PYTHONPATH=/opt:/opt/fs-order-session --mount type=bind,src=/opt/fc27-cloud-browser/isolated_backend.py,dst=/opt/isolated_backend.py,readonly --network host --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --mount type=bind,src=/opt/fs-order-session,dst=/opt/fs-order-session,readonly \
  --mount type=bind,src=/run/fs-order-session,dst=/run/fs-order-session,readonly \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  -e FC_V6_COST_REFERENCES \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  --mount type=bind,src=/opt/fc27-cloud-browser/collect_p2pah_cost.py,dst=/usr/local/bin/collect_p2pah_cost.py,readonly \
  fc27-cloud-cost:1 > "$trace"; then
  if python3 - "$trace" <<'PY'
import json,os,sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
assert x.get('status')=='valid'
assert [r.get('platform') for r in x.get('costs',[])]==['PS','XBOX','PC']
if os.environ.get('FC_V6_COST_REFERENCES') is not None:
    assert x.get('cost_protocol')=='fc27_curve_v6'
    assert all(r.get('status') in ('valid','missing') for r in x['costs'])
else:
    assert all(r.get('status')=='valid' and r.get('genre')=='1' and r.get('delivery_type')=='\u8ba2\u5355\u53d1\u8d27' for r in x['costs'])
PY
  then
    mv "$trace" "${trace%.tmp}.json"
    printf '%s\n' '{"source":"P2PAH","status":"valid","platforms":["PS","XBOX","PC"]}'
    exit 0
  fi
else
  collector_exit=$?
fi
python3 - "$trace" "$collector_exit" <<'PY'
import json,re,sys
from pathlib import Path
trace = Path(sys.argv[1])
failed = trace.with_suffix('.failed.json')
exit_code = int(sys.argv[2])
diagnostic = {'exit_code': exit_code}
result = {'source': 'P2PAH', 'status': 'missing', 'reason': 'collector_payload_invalid',
          'diagnostic': diagnostic, 'evidence_file': failed.name}
if exit_code == 124:
    result['reason'] = 'collector_process_timeout'
    diagnostic['timeout_seconds'] = 180
else:
    try:
        raw = trace.read_text(encoding='utf-8')
        if not raw.strip():
            result['reason'] = 'collector_output_empty'
        else:
            payload = json.loads(raw)
            reason = payload.get('reason') or ('cost_records_incomplete' if payload.get('status') == 'incomplete' else '')
            if isinstance(reason, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:,.-]{0,119}', reason):
                result['reason'] = reason
            detail = payload.get('diagnostic')
            if isinstance(detail, dict):
                for key in ('requested_page', 'http_status'):
                    if type(detail.get(key)) is int:
                        diagnostic[key] = detail[key]
                checked = detail.get('checked_at')
                if isinstance(checked, str) and re.fullmatch(r'[0-9T:.+Z-]{19,40}', checked):
                    diagnostic['checked_at'] = checked
                observed = detail.get('observed')
                if isinstance(observed, dict):
                    checks = {k: observed[k] for k in ('login', 'table', 'hasDataRows', 'empty')
                              if type(observed.get(k)) is bool}
                    for key in ('page', 'game', 'product', 'genre'):
                        value = observed.get(key)
                        if isinstance(value, str) and re.fullmatch(r'[0-9]{1,8}', value):
                            checks[key] = value
                    checks['delivery_type_header_matches'] = observed.get('typeHeader') == '\u4ea4\u8d27\u7c7b\u578b'
                    diagnostic['observed'] = checks
    except (OSError, ValueError, TypeError, AttributeError):
        pass
receipt = json.dumps(result)
trace.write_text(receipt + '\n', encoding='utf-8')
trace.replace(failed)
print(receipt)
PY
exit 1
