"""Preserve untouched mixed line endings while adapting only four reader anchors."""
import argparse
import hashlib
from pathlib import Path

BASELINE_SHA256='08b4ca6029c5f81eedc390f918936e1c1295f9669fd523822e952f7c392a9e31'
REVIEW_SHA256='8ed4baad4d3a1ce90d46bc120b089ea59e529875000d4eae4dc67bc079b6ed27'
OLD=b"    r=subprocess.run(['docker','exec','-i',container,'python3','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)"


def transform(raw):
    if raw.count(OLD)!=1:
        raise ValueError('one_reader_call_adapter_required')
    index=raw.index(OLD)+len(OLD)
    newline=b'\r\n' if raw[index:index+2]==b'\r\n' else b'\n'
    replacement=newline.join((
        b"    if script in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):",
        b"        if container != 'fs-order-browser':raise ValueError('order_reader_isolation_required')",
        b'        from order_reader_runner import run',
        b'        r=run(program,requests,timeout)',
        b'    else:',b'    '+OLD))
    candidate=raw.replace(OLD,replacement)
    for reader in (b'primary_reader.py',b'fc_category_reader.py',b'profit_daily_reader.py'):
        before=b"call('fc27-cloud-browser','"+reader+b"'"
        if candidate.count(before)!=1:
            raise ValueError('one_original_order_consumer_required')
        candidate=candidate.replace(before,b"call('fs-order-browser','"+reader+b"'")
    if hashlib.sha256(candidate.replace(b'\r\n',b'\n')).hexdigest()!=REVIEW_SHA256:
        raise ValueError('unreviewed_candidate_difference')
    compile(candidate,'collector.py','exec')
    return candidate


def prepare(baseline,output):
    raw=baseline.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASELINE_SHA256:
        raise ValueError('active_collector_baseline_drift')
    result=transform(raw);output.write_bytes(result)
    return hashlib.sha256(result).hexdigest()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(prepare(args.baseline,args.output))
