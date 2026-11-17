#!/bin/sh
set -eu
umask 077
evidence=/var/lib/fc27-cloud/evidence
state=/var/lib/fc27-cloud/state
mkdir -p -m 0700 "$evidence" "$state"
exec 9>"$state/p2pah-cost.lock"
flock -n 9 || { printf '%s\n' '{"status":"busy"}'; exit 75; }
trace=$(mktemp "$evidence/p2pah-cost-XXXXXXXX.tmp")
if timeout 180s docker run --rm --network host --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --group-add 11028 \
  -e FC_V6_COST_REFERENCES \
  -e FC27_CDP_ENDPOINT=http://127.0.0.1:9225 \
  --mount type=bind,src=/etc/fc27-cloud/fc27.env,dst=/run/secrets/fc27.env,readonly \
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
fi
mv "$trace" "${trace%.tmp}.failed.json"
python3 - "${trace%.tmp}.failed.json" <<'PY'
import json,re,sys
from pathlib import Path
result={'source':'P2PAH','status':'missing','reason':'collector_failed'}
try:
    payload=json.load(open(sys.argv[1],encoding='utf-8'))
    reason=payload.get('reason') or ('cost_records_incomplete' if payload.get('status')=='incomplete' else '')
    if isinstance(reason,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:,.-]{0,119}',reason):
        result['reason']=reason
    diagnostic=payload.get('diagnostic')
    if isinstance(diagnostic,dict):
        result['diagnostic']={k:diagnostic.get(k) for k in ('requested_page','http_status','checked_at')}
        observed=diagnostic.get('observed')
        if isinstance(observed,dict):
            result['diagnostic']['observed']={k:observed.get(k) for k in ('login','page','game','product','genre','typeHeader','table','hasDataRows','empty')}
except (OSError,ValueError,TypeError,AttributeError):
    pass
result['evidence_file']=Path(sys.argv[1]).name
print(json.dumps(result))
PY
exit 1
