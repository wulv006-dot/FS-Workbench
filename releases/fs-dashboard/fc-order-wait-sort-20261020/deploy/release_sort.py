"""Exact FC detail sort scope over the existing frozen publisher; retain original guards."""
from pathlib import Path
import hashlib,types,json,sys
P=Path(__file__).parent
raw=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_navigation_base.py').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'
s=raw.decode();old="DETAIL_SCOPE='fc-detail-analytics-20261012'";assert s.count(old)==1
s=s.replace(old,"DETAIL_SCOPE='fc-order-wait-sort-20261020'")
b=types.ModuleType('existing_fc_publisher');b.__file__='/opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_navigation_base.py'
exec(compile(s,b.__file__,'exec'),b.__dict__)
m=json.loads((P/'approved-manifest.json').read_bytes());original=b.validate
b.expected_files=lambda manifest:set(b.DETAIL_TARGETS) if manifest.get('scope')=='fc-order-wait-sort-20261020' else (_ for _ in ()).throw(ValueError('sort_scope_only'))

def validate(manifest,stage):
 if manifest!=m:raise ValueError('exact_sort_manifest_required')
 for r in manifest['files']:
  if r['candidate']!='fc/fc_detail_model.py' and r['beforeSha256']!=r['sha256']:raise ValueError('unrelated_FC_source_change')
 return original(manifest,stage)
b.validate=validate
if __name__=='__main__':b.main()
