"""Retire the legacy login daemon and reconcile SBC with the active shared owner."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import urllib.request

from deploy_sales import atomic
from unify_admin import transform

RELEASE = Path('/var/backups/fs-admin-retire-20261021-v1')
SBC = Path('/opt/fc27-sbc-tool/admin_client.py')
SBC_SHA = 'ceb98846749432f25e8b11bf7350d47e0bea53d19b257e45d7c96f632bff9ca9'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def main():
    assert not RELEASE.exists(), 'existing_operation_inspect_receipt'
    raw = SBC.read_bytes()
    assert digest(raw) == SBC_SHA, 'sbc_changed'
    candidate = transform(raw.decode(), 'sbc').encode()
    before_tree, after_tree = ast.parse(raw), ast.parse(candidate)
    def other_methods(tree):
        cls, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AdminClient']
        return {n.name:ast.dump(n) for n in cls.body if isinstance(n, ast.FunctionDef)
                and n.name not in {'login', 'authenticated', '_bytes'}}
    assert other_methods(before_tree) == other_methods(after_tree), 'unrelated_sbc_changed'
    with urllib.request.urlopen('http://127.0.0.1:8793/health', timeout=10) as response:
        health = json.load(response)
    assert health.get('busy') is False and not health.get('running'), 'sbc_busy'
    with urllib.request.urlopen('http://127.0.0.1:8767/health', timeout=10) as response:
        assert json.load(response).get('ready') is True, 'global_not_ready'
    legacy = Path('/etc/systemd/system/dashboard-collect.service')
    assert legacy.is_file() and not legacy.is_symlink(), 'legacy_unit_changed'
    old_unit = legacy.read_bytes()
    dropin = Path('/etc/systemd/system/fc27-p2pah-session.service.d/manual-inbox.conf')
    assert not dropin.exists(), 'dropin_exists'
    assert Path('/usr/bin/install').is_file()
    RELEASE.mkdir(mode=0o700)
    atomic(RELEASE/'sbc.before.py',raw,0o600)
    atomic(RELEASE/'dashboard-collect.service.before',old_unit,0o600)
    receipt={'operation':RELEASE.name,'state':'PREPARED','sbc_before':SBC_SHA,
             'sbc_after':digest(candidate),'legacy_unit_before':digest(old_unit),
             'retired_units':['dashboard-collect.service'],'sales_timer':'held_for_order',
             'login_requests':0}
    atomic(RELEASE/'receipt.json',json.dumps(receipt).encode(),0o600)
    assert SBC.read_bytes()==raw and legacy.read_bytes()==old_unit,'changed_before_apply'
    subprocess.run(['systemctl','stop','fc27-sbc-tool.service'],check=True,capture_output=True)
    assert SBC.read_bytes()==raw,'sbc_changed_before_replace'
    atomic(SBC,candidate,stat.S_IMODE(SBC.stat().st_mode))
    subprocess.run(['systemctl','disable','--now','dashboard-collect.service'],check=True,capture_output=True)
    assert legacy.read_bytes()==old_unit,'legacy_changed_before_retire'
    temp=legacy.with_name(legacy.name+'.retired.tmp')
    os.symlink('/dev/null',temp)
    os.replace(temp,legacy)
    dropin.parent.mkdir(mode=0o755,exist_ok=True)
    atomic(dropin,b'[Service]\nExecStartPre=/usr/bin/install -d -m 0700 /run/fs-admin-manual /run/fs-google-code-wulv-20261021\n',0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
    subprocess.run(['systemctl','enable','fc27-p2pah-session.service'],check=True,capture_output=True)
    subprocess.run(['systemctl','start','fc27-sbc-tool.service'],check=True,capture_output=True)
    assert digest(SBC.read_bytes())==receipt['sbc_after'] and legacy.is_symlink() and os.readlink(legacy)=='/dev/null'
    receipt['state']='RETIRED_AND_SBC_RECONCILED'
    atomic(RELEASE/'receipt.json',json.dumps(receipt).encode(),0o600)
    print(json.dumps(receipt))


if __name__=='__main__':main()
