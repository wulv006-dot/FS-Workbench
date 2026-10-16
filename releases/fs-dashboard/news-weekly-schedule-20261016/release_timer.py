"""Change only the existing shared game-monitor timer; never start its service."""
from pathlib import Path
import argparse,hashlib,json,subprocess
import release_backend as release

TARGET=Path('/etc/systemd/system/fs-boss-game-monitor.timer')
BEFORE='9599f01b5ff2d0c1a7221d3fb21245467d0423b669fe8f2b77c85afa5d9d061a'
OLD=b'OnCalendar=*-*-* 00:05:00'
NEW=b'OnCalendar=Sat *-*-* 00:05:00'

def candidate(raw):
    if hashlib.sha256(raw).hexdigest()!=BEFORE or raw.count(OLD)!=1:
        raise ValueError('original timer CAS required')
    return raw.replace(OLD,NEW).replace(b'FS game monitor daily at 00:05 Shanghai',b'FS game monitor weekly Saturday at 00:05 Shanghai')

def timer_state():
    raw=subprocess.check_output(['systemctl','show','fs-boss-game-monitor.timer','-p','ActiveState','-p','UnitFileState','-p','NextElapseUSecRealtime'],universal_newlines=True)
    return dict(line.split('=',1) for line in raw.splitlines() if '=' in line)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);args=parser.parse_args()
    manifest=json.loads(args.manifest.read_bytes());release.validate(manifest)
    backup=Path('/var/backups/news-weekly-schedule-20261016/timer-saturday-20261016')
    with release.locks(manifest,Path('/')):
        release.guards(manifest,Path('/'));release.safe(TARGET)
        if any(release.digest(Path(row['target']))!=row['sha256'] for row in manifest['files']):
            raise ValueError('approved backend must be deployed first')
        if Path('/etc/localtime').resolve()!=Path('/usr/share/zoneinfo/Asia/Shanghai'):
            raise ValueError('Shanghai server timezone required')
        state=timer_state()
        if state['ActiveState']!='active' or state['UnitFileState']!='enabled':raise ValueError('original active/enabled timer required')
        raw=TARGET.read_bytes();changed=candidate(raw);after=hashlib.sha256(changed).hexdigest()
        backup.mkdir(mode=0o700);release.atomic(backup/'original.timer',raw)
        try:
            if release.digest(TARGET)!=BEFORE:raise ValueError('timer changed before replace')
            release.atomic(TARGET,changed,0o644)
            subprocess.run(['systemctl','daemon-reload'],check=True)
            subprocess.run(['systemctl','restart','fs-boss-game-monitor.timer'],check=True)
            release.idle();state=timer_state()
            if release.digest(TARGET)!=after or state['ActiveState']!='active' or state['UnitFileState']!='enabled':raise ValueError('timer readback failed')
        except Exception:
            if release.digest(TARGET)==after:
                release.atomic(TARGET,raw,0o644)
                subprocess.run(['systemctl','daemon-reload'],check=True)
                subprocess.run(['systemctl','restart','fs-boss-game-monitor.timer'],check=True)
            raise
        receipt=dict(status='applied',before_sha256=BEFORE,sha256=after,schedule='Saturday 00:05 Asia/Shanghai',state=state,service_started=False,backup=str(backup))
        release.atomic(backup/'receipt.json',json.dumps(receipt,indent=2).encode());print(json.dumps(receipt))

if __name__=='__main__':main()
