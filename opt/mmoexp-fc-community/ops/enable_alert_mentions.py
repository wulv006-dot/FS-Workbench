"""Make only the five approved zero-permission alert roles mentionable."""
import importlib.util
import json
import os
from pathlib import Path

STAGE = Path('/opt/mmoexp-fc-news-stage-20261108-core/community-ux')
spec = importlib.util.spec_from_file_location('alert_ops', STAGE.parent/'discord_ops.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
ROLES = {'1568690687694606446': 'FC27 Alerts · SBC',
         '1568690688789319746': 'FC27 Alerts · Evolutions',
         '1568690690160988353': 'FC27 Alerts · Objectives & Rush',
         '1568690690903244832': 'FC27 Alerts · News',
         '1568690692769714397': 'FC27 Alerts · Giveaways'}


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def selected_roles():
    selected = {r['id']: r for r in ops.request('GET', 'guilds/'+ops.GUILD+'/roles') if r['id'] in ROLES}
    if set(selected) != set(ROLES) or any(r['name'] != ROLES[key] or int(r['permissions'])
            or r['managed'] or r['hoist'] for key, r in selected.items()):
        raise RuntimeError('Alert role identity or permissions changed')
    return selected


if __name__ == '__main__':
    ops.identity()
    before = selected_roles()
    backup = STAGE/'alert-mentions-before.json'
    if not backup.exists():
        save(backup, before)
    for key, role in before.items():
        if not role['mentionable']:
            result = ops.request('PATCH', 'guilds/'+ops.GUILD+'/roles/'+key, {'mentionable': True})
            if result['id'] != key or result['mentionable'] is not True or int(result['permissions']):
                raise RuntimeError('Role update not confirmed')
    after = selected_roles()
    if any(r['mentionable'] is not True for r in after.values()):
        raise RuntimeError('Mentionability readback failed')
    receipt = {'status': 'verified', 'role_ids': list(ROLES), 'mentionable': True, 'permissions': '0',
               'backup': str(backup), 'scope': 'server-wide role setting; writable channels can mention these roles'}
    save(STAGE/'alert-mentions-result.json', receipt)
    print(json.dumps(receipt))
