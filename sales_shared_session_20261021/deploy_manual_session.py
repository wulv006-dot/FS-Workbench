"""Install the human-CAPTCHA session image and temporarily selected account, without logging in."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

UNIT = Path('/etc/systemd/system/fc27-p2pah-session.service')
CONFIG = Path('/etc/fc27-cloud/fc27.env')
RELEASE = Path('/var/backups/fs-admin-wulv-manual-20261021-v1')
UNIT_SHA = '4c6879e71e98972d4d7b0ca27f9ff51cbcf75bdc583c11d431678551a9aab997'
IMAGE = 'fc27-cloud-session:manual-wulv-20261021-v1'
IMAGE_ID = 'sha256:08c82bdf70d914a0f3b85863ef52ceda3a74ed921fdbd97dc3c7f16a46ddcea9'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def atomic(path, raw, mode, uid=0, gid=0):
    temp = path.with_name(path.name + '.wulv-manual.tmp')
    with temp.open('xb') as stream:
        os.chmod(temp, mode)
        os.chown(temp, uid, gid)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def main():
    assert not RELEASE.exists(), 'existing_operation_inspect_receipt'
    credential = json.load(sys.stdin)
    assert set(credential) == {'P2PAH_USERNAME', 'P2PAH_PASSWORD', 'P2PAH_API_BASE'}
    assert credential['P2PAH_USERNAME'] == 'wulv' and credential['P2PAH_PASSWORD']
    assert credential['P2PAH_API_BASE'] == 'https://admin-api.p2pah.cn'
    unit = UNIT.read_bytes()
    assert digest(unit) == UNIT_SHA, 'unit_changed'
    config = CONFIG.read_bytes()
    config_info = CONFIG.stat()
    assert config_info.st_uid == 0 and not (config_info.st_mode & 0o007)
    assert subprocess.check_output(['docker','image','inspect',IMAGE,'--format','{{.Id}}'],text=True).strip()==IMAGE_ID
    lines = config.decode().splitlines()
    changed = set()
    for index, line in enumerate(lines):
        key, sep, _ = line.partition('=')
        if sep and key in {'P2PAH_USERNAME', 'P2PAH_PASSWORD'}:
            lines[index] = key + '=' + json.dumps(credential[key])
            changed.add(key)
    assert changed == {'P2PAH_USERNAME', 'P2PAH_PASSWORD'}, 'configuration_contract_changed'
    candidate_config = ('\n'.join(lines) + '\n').encode()
    old_image = 'fc27-cloud-session:2fa-file-20261021-v1'
    text = unit.decode()
    assert text.count(old_image)==1
    assert text.count('src=/run/fs-google-code,dst=/run/secrets/gcode')==1
    assert text.count('-p 127.0.0.1:8767:8767')==1
    text = text.replace(old_image, IMAGE).replace('src=/run/fs-google-code,dst=/run/secrets/gcode',
            'src=/run/fs-google-code-wulv-20261021,dst=/run/secrets/gcode')
    text = text.replace('-p 127.0.0.1:8767:8767',
            '--mount type=bind,src=/run/fs-admin-manual,dst=/run/secrets/fs-manual-captcha -p 127.0.0.1:8767:8767')
    RELEASE.mkdir(mode=0o700)
    atomic(RELEASE/'unit.before', unit, 0o600)
    atomic(RELEASE/'config.before', config, 0o600)
    units = ['fc27-cloud-worker', 'fc27-ops-worker', 'fc27-cloud-api', 'fc27-ops-api']
    before = {name:subprocess.run(['systemctl','is-active',name],capture_output=True,text=True).stdout.strip() for name in units}
    receipt = {'operation':RELEASE.name,'state':'PREPARED','account':'wulv','temporary_account':True,
               'unit_before':UNIT_SHA,'unit_after':digest(text.encode()),'image':IMAGE,'image_id':IMAGE_ID,
               'before_states':before,'login_requests':0,
               'created_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()}
    atomic(RELEASE/'receipt.json',json.dumps(receipt).encode(),0o600)
    assert UNIT.read_bytes()==unit and CONFIG.read_bytes()==config,'changed_before_apply'
    for path in ['/run/fs-admin-manual','/run/fs-google-code-wulv-20261021']:
        Path(path).mkdir(mode=0o700,exist_ok=False)
    subprocess.run(['systemctl','stop','fc27-p2pah-session'],check=True,capture_output=True)
    assert UNIT.read_bytes()==unit and CONFIG.read_bytes()==config,'changed_before_replace'
    atomic(CONFIG,candidate_config,stat.S_IMODE(config_info.st_mode),config_info.st_uid,config_info.st_gid)
    atomic(UNIT,text.encode(),0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
    subprocess.run(['systemctl','start','fc27-p2pah-session'],check=True,capture_output=True)
    assert CONFIG.read_bytes()==candidate_config and UNIT.read_bytes()==text.encode()
    receipt['state']='DEPLOYED_AWAITING_HUMAN_CAPTCHA'
    atomic(RELEASE/'receipt.json',json.dumps(receipt).encode(),0o600)
    print(json.dumps(receipt))


if __name__=='__main__':main()
