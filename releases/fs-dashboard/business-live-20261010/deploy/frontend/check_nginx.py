"""Parse the full current Nginx master with only this staged fragment substituted."""
import hashlib,json,subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
fragment='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
main=Path('/etc/nginx/nginx.conf').read_text()
old='include /etc/nginx/conf.d/*.conf;'
assert main.count(old)==1,'Expected one conf.d include'
includes=[]
for p in sorted(Path('/etc/nginx/conf.d').glob('*.conf')):
    raw=p.read_text()
    if fragment in raw:
        assert raw.count(fragment)==1,'Expected one formal fragment include'
        q=HERE/('nginx-'+p.name)
        q.write_text(raw.replace(fragment,str(HERE/'candidate/formal.conf')))
        includes.append('include '+str(q)+';')
    else:includes.append('include '+str(p)+';')
candidate=HERE/'nginx-candidate.conf'
candidate.write_text(main.replace(old,'\n'.join(includes)))
r=subprocess.run(['nginx','-t','-c',str(candidate)],capture_output=True,universal_newlines=True)
print(json.dumps({'candidateFullMasterSyntaxPassed':r.returncode==0,'returncode':r.returncode,'diagnostic':r.stderr[-1800:],'nginxReload':False}))
if r.returncode:raise SystemExit(r.returncode)
