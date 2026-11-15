"""One-time, baseline-checked restoration; dry-run unless --apply is supplied.

Order sources are still owned by the uncommitted DSH task. Patch the verified
live module without importing or committing that task's other changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

EXPECTED = {
    'order_panel.py': '2e54fd6ba6cafe03d5b8a22b66f947f6a337c45e595f6c755ae94eaa2777d518',
    'chat_service.py': 'ceb5e925b21507fed05c7c28de6299bff8a1b00b9caf11c1183195fb0e8ef2c0',
    'content.chat.config.json': '8ab28f11c50e854a46e837e990e73bcd0e7bd9453d64213facf66a8de78dcffe',
}
SERVICES = ('mmoexp-fc-community.service', 'mmoexp-fc-chat.service')
TEXT = ('FCVIP6: 6% off eligible FC27 purchases at MMOEXP. '
        'Valid 2026-10-27 to 2027-11-01; no usage-count limit. '
        'Eligibility and final price confirmed at checkout.')


def replace_once(data, old, new):
    old, new = old.encode('utf-8'), new.encode('utf-8')
    if data.count(old) != 1:
        raise ValueError('Expected exactly one matching source fragment')
    return data.replace(old, new)


def candidates(original):
    result = dict(original)
    order = replace_once(original['order_panel.py'], 'REWARDS_PAUSED = True',
                         'REWARDS_PAUSED = False')
    order = replace_once(order, "'Discount rewards are temporarily paused.'))",
        "'Your first reaction unlocks a private MMOEXP FC27 6% discount code sent by DM.\\n'\n"
        "        'DMs closed? Use Get my code after reacting.'))")
    order = replace_once(order, "'Thank you! Your code: **FCVIP6** · **6% off**. '",
        "'Thank you! Your code: **FCVIP6** · **6% off** eligible FC27 purchases at MMOEXP. '")
    order = replace_once(order, "'Final eligibility and price are confirmed at checkout.')",
        "'Valid 2026-10-27 to 2027-11-01; no usage-count limit. '\n"
        "          'Final eligibility and price are confirmed at checkout.')")
    result['order_panel.py'] = order
    chat = replace_once(original['chat_service.py'], "description=text or 'Limited discount code'",
                        "description=text or 'Community discount code'")
    result['chat_service.py'] = replace_once(chat,
        "text='Limited quantity, final price at checkout'",
        "text='Eligibility and final price confirmed at checkout'")
    config = json.loads(original['content.chat.config.json'])
    surprise = config['chat_bot']['surprise']
    if surprise['enabled'] is not False or surprise['codes'] != ['FCVIP6']:
        raise ValueError('Unexpected surprise baseline')
    # Preserve every other runtime setting, including staff and rate limits.
    surprise['enabled'] = True
    surprise['texts'] = [TEXT]
    result['content.chat.config.json'] = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    for name in ('order_panel.py', 'chat_service.py'):
        compile(result[name], name, 'exec')
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(path, data):
    temp = path.with_name(path.name + '.fcvip6-restore.tmp')
    shutil.copy2(path, temp)
    stat = path.stat()
    os.chown(str(temp), stat.st_uid, stat.st_gid)
    temp.write_bytes(data)
    os.replace(str(temp), str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/mmoexp-fc-community'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.root
    original = {name: (root / name).read_bytes() for name in EXPECTED}
    if {name: digest(data) for name, data in original.items()} != EXPECTED:
        raise SystemExit('STOP: production baseline changed; no files written')
    changed = candidates(original)
    print(json.dumps({'candidate_sha256': {n: digest(d) for n, d in changed.items()},
                      'surprise': json.loads(changed['content.chat.config.json'])['chat_bot']['surprise']}), flush=True)
    if not args.apply:
        return
    backup = root / 'var/releases' / ('fcvip6-restore-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    backup.mkdir(parents=True, exist_ok=False)
    for name in original:
        shutil.copy2(root / name, backup / name)
    print('BACKUP ' + str(backup), flush=True)
    # Recheck immediately before writes; caller holds the existing release locks.
    if any((root / n).read_bytes() != data for n, data in original.items()):
        raise SystemExit('STOP: baseline changed during preparation')
    written = []
    try:
        for name, data in changed.items():
            install(root / name, data)
            written.append(name)
        subprocess.run(['systemctl', 'restart'] + list(SERVICES), check=True)
        subprocess.run(['systemctl', 'is-active'] + list(SERVICES), check=True)
        assert all((root / n).read_bytes() == data for n, data in changed.items())
        print('APPLIED; Discord readiness and card readback still required', flush=True)
    except Exception:
        for name in written:
            if (root / name).read_bytes() != changed[name]:
                raise RuntimeError('Concurrent change; inspect backup before rollback')
            install(root / name, original[name])
        subprocess.run(['systemctl', 'restart'] + list(SERVICES), check=False)
        raise


if __name__ == '__main__':
    main()
