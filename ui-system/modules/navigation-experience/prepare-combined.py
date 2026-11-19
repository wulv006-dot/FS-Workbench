"""Prepare one UI publisher stage from captured active bytes and reviewed payloads.

This builds local files only. The existing release_ui.py performs production CAS,
backup, activation, and rollback after the owner supplies the stage and approval.
"""
import base64
import hashlib
import json
import re
import shutil
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(capture_file, reviewed_dir, navigation_dir, publisher_file, output):
    capture = json.loads(Path(capture_file).read_text(encoding='ascii'))
    reviewed_dir, navigation_dir, output = map(Path, (reviewed_dir, navigation_dir, output))
    if output.exists():
        raise ValueError('new stage required')
    raw = {}
    for name, row in capture.items():
        value = base64.b64decode(row['base64'], validate=True)
        if sha(value) != row['sha256']:
            raise ValueError('captured hash mismatch: ' + name)
        raw[name] = value
    expected = {
        'nav.js': '40480fcbf0c0a084f8ca9b568a991c6f7e8d7ea09ccb1c5930ac28c48aa6e1f6',
        'hubnav.js': 'f84604eb0835f01461b94635ab1e4f45c9cfb2e626c0fdd0cf61fb7f530b5e61',
        'production-server.mjs': 'de5e68a95150fca28bc156bceb41fb0f88b3cd56e9a820dc5f0247cc5e442bed',
        'old-shell.js': 'ea2f0650aba175b5a725b4f409e869dbfa332807e1776432a470310e0d4ac100',
        'old-home-shell.js': '6027ccc49bef842611770bcea05d0e2594767fb2adf91fab00116a0e7186be36',
        'old-legacy-shell.js': '900255839ace975c2a7333bf0ae4b906d87aa0b14994ddc32f4166265549b47d',
        'old-homepage-shell.js': 'f985e1d802bafb01b376a4c344d5997d155660d92fc3ff501103309d97b58c6b',
        'old-analytics-index.html': 'dd989f51468c0d9fa72f7e1a2c3485db59c8f95ad7e3d3af72745d80092b1104',
    }
    for name, value in expected.items():
        if capture[name]['sha256'] != value:
            raise ValueError('unreviewed live baseline: ' + name)
    reviewed_hash = {
        'shell.js': 'd57e982f939f58a3888c3f1e862429833cea863e563d064c1cdad07fe3587f04',
        'home-shell.js': '6285998c936804f064bea72afee832418f7e7baf5fe2e35658f8e9a972d2fbd4',
        'legacy-shell.js': 'f6379f72de373ac12cd614085757d28d516b3e1ec0122c801a4d86190c41b29f',
        'homepage-shell.js': '0c97b6398692cfce509e75e7776d33bc9a305b4cfc2578834932bae74311a501',
        'production-server.mjs': 'e0d11517a31c3c644fe1e588ead4dd0cb048986c04800fe6eb55ac9d05cecb57',
        'analytics-index.html': 'dd2f70cc3c48cfd6101f7b3adf2f31a8d05ce50b5420816104b3eee658f477f9',
    }
    reviewed = {name: (reviewed_dir / name).read_bytes() for name in reviewed_hash}
    for name, value in reviewed.items():
        if sha(value) != reviewed_hash[name]:
            raise ValueError('reviewed module hash mismatch: ' + name)
    nav = {name: (navigation_dir / name).read_bytes() for name in ('nav.js', 'hubnav.js')}
    version = 'nav-unified-20261120-' + sha(nav['nav.js'] + b'\0' + nav['hubnav.js'])[:12]
    old_loader = b"const sharedNav=document.createElement('script');sharedNav.src='/__hub/hubnav.js?v=3dda7cae';sharedNav.defer=true;document.head.append(sharedNav);"
    loader = ("{const href=new URL('/__hub/hubnav.js?v=" + version + "',document.baseURI).href;"
              "if(!document.getElementById('hubNav')&&![...document.scripts].some(s=>s.src===href)){"
              "const sharedNav=document.createElement('script');sharedNav.src=href;sharedNav.defer=true;document.head.append(sharedNav);}}") .encode()
    def replace_loader(data):
        if data.count(old_loader) != 1:
            raise ValueError('navigation loader drift')
        return data.replace(old_loader, loader, 1)
    shell_names = ('shell.js', 'home-shell.js', 'legacy-shell.js', 'homepage-shell.js')
    assets = {name: replace_loader(reviewed[name]) for name in shell_names}
    assets['analytics-index.html'] = reviewed['analytics-index.html']
    asset_names = shell_names + ('analytics-index.html',)
    package = 'nav-unified-20261120-' + sha(b''.join(name.encode()+b'\0'+assets[name] for name in asset_names))[:12]
    routes = {
        'shell.js': '/dashboard/workspace-assets/workspace-native-20261006-8b7908ecad30/shell.js',
        'home-shell.js': '/dashboard/workspace-assets/workspace-native-20261006-72d7ba0dbca8/shell.js',
        'legacy-shell.js': '/dashboard/workspace-assets/workspace-native-20261006-fd4cfd0a70aa/shell.js',
        'homepage-shell.js': '/dashboard/workspace-assets/workspace-native-20261006-37fe775358df/shell.js',
        'analytics-index.html': '/dashboard/analytics/index.html',
    }
    formal = raw['zz-formal.conf']
    for name, location in routes.items():
        pattern = re.compile(rb'(?m)^location = ' + re.escape(location.encode()) + rb' \{\r?\n.*?^\}', re.S)
        matches = list(pattern.finditer(formal))
        old = ('alias ' + capture['old-'+name]['target'] + ';').encode()
        new = ('alias /var/lib/fs-navigation-formal-static/' + package + '/' + name + ';').encode()
        if len(matches) != 1 or matches[0].group().count(old) != 1:
            raise ValueError('active shell alias drift: ' + name)
        formal = pattern.sub(lambda match: match[0].replace(old, new, 1), formal, count=1)
    token = re.compile(rb'(/__hub/(?:nav|hubnav)\.js\?v=)[A-Za-z0-9_-]+')
    def replace_versions(data, name):
        result, count = token.subn(lambda m: m[1] + version.encode(), data)
        if not count:
            raise ValueError('navigation reference missing: ' + name)
        return result
    formal = replace_versions(formal, 'zz-formal.conf')
    payloads = {}
    for name in asset_names:
        payloads['a-assets/'+name] = ('/var/lib/fs-navigation-formal-static/'+package+'/'+name, None, assets[name])
    for name in ('nav.js','hubnav.js'):
        payloads['b-shared/'+name] = (capture[name]['target'], capture[name]['sha256'], nav[name])
    payloads['c-navigation.js'] = (capture['navigation.js']['target'], capture['navigation.js']['sha256'], replace_loader(raw['navigation.js']))
    payloads['c-production-server.mjs'] = (capture['production-server.mjs']['target'], capture['production-server.mjs']['sha256'], reviewed['production-server.mjs'])
    pages = ('home.html','analytics.html','hermes.html','sports.html','arpg.html','collaboration.html',
             'about.html','report.html','conversation.html','tasks.html','fc-coins.html','design-index.html','design-doc.html')
    for name in pages:
        payloads['d-pages/'+name] = (capture[name]['target'],capture[name]['sha256'],replace_versions(raw[name],name))
    payloads['zz-main.conf'] = (capture['z-main.conf']['target'],capture['z-main.conf']['sha256'],replace_versions(raw['z-main.conf'],'z-main.conf'))
    payloads['zz-formal.conf'] = (capture['zz-formal.conf']['target'],capture['zz-formal.conf']['sha256'],formal)
    output.mkdir(parents=True)
    files=[];targets={}
    for name,(target,before,data) in payloads.items():
        if before is not None and sha(data) == before:
            raise ValueError('unchanged target: '+name)
        path=output/'candidate'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        files.append(dict(candidate=name,target=target,beforeSha256=before,sha256=sha(data)))
        targets[name]=target
    protected = [dict(path=capture[name]['target'],sha256=capture[name]['sha256']) for name in
                 ('old-shell.js','old-home-shell.js','old-legacy-shell.js','old-homepage-shell.js','old-analytics-index.html','protected-index.html')]
    protected += [dict(path='/var/www/dashboard/fs-home/navigation.json',sha256='898ec4949c47fc7e19c1e350ae14a65287f103baa7d849cf1eb9378d4e475151'),
                  dict(path='/var/www/dashboard/fs-home/module-registry.json',sha256='ce4c0e9186bd39f264de36a9e7b4fc6a96f32fe3b3b64f794294037c1f4012d0')]
    manifest=dict(schemaVersion=1,scope='traffic-source-tabs-ui-finish-20261019',releaseReady=True,
                  businessWrites=False,timersChanged=False,
                  runtimeRequired={'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}},
                  unchangedRequired=protected,files=files)
    encode=lambda x:(json.dumps(x,ensure_ascii=False,indent=2)+'\n').encode()
    (output/'manifest.json').write_bytes(encode(manifest));(output/'targets.json').write_bytes(encode(targets))
    shutil.copyfile(publisher_file,output/'release_ui.py')
    return dict(version=version,package=package,files=len(files),manifestSha256=sha((output/'manifest.json').read_bytes()))

if __name__ == '__main__':
    import sys
    print(json.dumps(prepare(*sys.argv[1:]),ensure_ascii=False,indent=2))
