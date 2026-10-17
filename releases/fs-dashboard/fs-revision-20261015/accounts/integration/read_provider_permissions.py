"""Read only service identity and file metadata, never credential contents."""
from datetime import datetime, timezone
import json
from pathlib import Path
import pwd
import re
import stat
import subprocess

KEY = Path('/var/lib/fs-hermes-fc/fs/secrets/deepseek.key')
out = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'credential_contents_read': False,
       'provider_called': False, 'key_file_metadata': [], 'units': {}}
for path in (KEY, *KEY.parents):
    info = path.lstat()
    out['key_file_metadata'].append({'path': str(path), 'uid': info.st_uid, 'gid': info.st_gid,
        'mode': oct(stat.S_IMODE(info.st_mode)), 'symlink': path.is_symlink(),
        'regular': stat.S_ISREG(info.st_mode), 'bytes': info.st_size if path == KEY else None})
for unit in ('fs-boss-game-monitor.service', 'fs-boss-management.service', 'fs-business-range.service'):
    fields = ('User', 'Group', 'SupplementaryGroups', 'DynamicUser', 'RootDirectory', 'RootImage',
              'InaccessiblePaths', 'ReadOnlyPaths', 'BindPaths', 'BindReadOnlyPaths', 'MainPID',
              'FragmentPath', 'DropInPaths', 'ProtectSystem', 'ProtectHome', 'NoNewPrivileges')
    result = subprocess.run(['systemctl', 'show', unit, '--no-pager'] +
                            [v for field in fields for v in ('-p', field)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    user = props.get('User') or 'root'
    props['resolved_uid'] = pwd.getpwnam(user).pw_uid if not user.isdigit() else int(user)
    props['selected_key_file_directives'] = []
    for source in [props.get('FragmentPath')] + props.get('DropInPaths', '').split():
        if not source:
            continue
        path = Path(source)
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if line.startswith('Environment=FS_HERMES_DEEPSEEK_KEY_FILE='):
                name = line.partition('FS_HERMES_DEEPSEEK_KEY_FILE=')[2].strip()
                props['selected_key_file_directives'].append({'source': source,
                    'default_path': name == str(KEY), 'unexpected_override': name != str(KEY)})
    pid = props.get('MainPID', '0')
    if pid != '0':
        props['running_process_identity'] = [line for line in Path('/proc/' + pid + '/status').read_text().splitlines()
                                              if line.startswith(('Uid:', 'Gid:'))]
    out['units'][unit] = props
print(json.dumps(out, indent=2))
