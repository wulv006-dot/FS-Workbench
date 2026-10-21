"""Keep all active Nginx bytes except three scoped aliases and one authenticated asset route."""
import hashlib,re

BEFORE='5d59f2254e02878f4755ad29fce29f688102181d0fc01c07b29997d4384a56be'

def candidate(raw,assets):
    if hashlib.sha256(raw).hexdigest()!=BEFORE or not re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',assets):
        raise ValueError('navigation_baseline_drift')
    edits={
      '/dashboard/data-tools/index.html':('workspace-native-20261006-afff372192a3/tools-index.html',assets+'/tools-index.html'),
      '/dashboard/data-tools/page.js':('workspace-native-20261006-afff372192a3/page.js',assets+'/page.js'),
      '/dashboard/fs-home/hermes/customer-tracking/page.js':('workspace-native-20261006-346f59eea565/page.js',assets+'/tracking-page.js')}
    for uri,(old,new) in edits.items():
        blocks=list(re.finditer(rb'^location = '+re.escape(uri.encode())+rb' \{.*?^\}',raw,re.S|re.M))
        if len(blocks)!=1:raise ValueError('navigation_route_drift')
        match=blocks[0];block=match.group()
        old=('alias /var/lib/fs-navigation-formal-static/'+old+';').encode()
        if block.count(old)!=1:raise ValueError('navigation_alias_drift')
        block=block.replace(old,('alias /var/lib/fs-navigation-formal-static/'+new+';').encode())
        raw=raw[:match.start()]+block+raw[match.end():]
    pattern=rb'location = /dashboard/workspace-assets/workspace-native-20261006-916087de9ef6/data-workspace\.js \{.*?^\}'
    matches=re.findall(pattern,raw,re.S|re.M)
    if len(matches)!=1:raise ValueError('navigation_asset_contract_drift')
    block=matches[0].replace(b'workspace-native-20261006-916087de9ef6',assets.encode())
    return raw+b'\n# Business baseline: same existing auth and read-only static contract.\n'+block+b'\n'
