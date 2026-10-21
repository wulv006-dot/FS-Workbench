"""FC consumer-only fix; leaves the shared Admin service and credentials untouched."""
from pathlib import Path
import ast
from deploy_fc import once, publish


def changes():
    result = {}
    for name in ('coin_all_sync_job.py', 'player_sync_job.py', 'clear_cache_after_write.py'):
        path = Path('/opt/fc27-cloud-browser') / name
        text = path.read_text()
        old = 'from p2pah_session_service import '
        if name == 'coin_all_sync_job.py':
            text = text.replace("!='chenchao'", ' not in allowed_admin_usernames()')
            text = text.replace("!= 'chenchao'", 'not in allowed_admin_usernames()')
            tree = ast.parse(text)
            position = max((n.end_lineno for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == '__future__'), default=0)
            lines = text.splitlines(keepends=True)
            lines.insert(position, '''
def allowed_admin_usernames():
    import sys
    sys.path.insert(0, '/usr/local/bin')
    from p2pah_session_service import allowed_admin_usernames as allowed
    return allowed()
''')
            text = ''.join(lines)
        else:
            text = once(text, old, 'from p2pah_session_service import allowed_admin_usernames, ')
            text = text.replace('!= "chenchao"', 'not in allowed_admin_usernames()')
            text = text.replace('username == "chenchao"', 'username in allowed_admin_usernames()')
        result[path] = text
    for name in ('execute_price.sh', 'clear_cache_after_write.sh', 'sync_players.sh'):
        path = Path('/opt/fc27-cloud-browser') / name
        text = path.read_text()
        marker = '  --mount type=bind,src=/etc/fc27-cloud/fc27.env,dst=/run/secrets/fc27.env,readonly \\\n'
        mounts = ('  --mount type=bind,src=/opt/fs-order-session/fc_shared_admin.py,dst=/usr/local/bin/p2pah_session_service.py,readonly \\\n'
                  '  --mount type=bind,src=/etc/fc27-cloud/global-admin-principal.json,dst=/run/secrets/fs-global-admin.json,readonly \\\n')
        if name != 'execute_price.sh':
            mounts += '  -e FS_ADMIN_SESSION_URL=http://fc27-p2pah-session:8767 \\\n'
        text = once(text, marker, mounts)
        result[path] = text
    return result


if __name__ == '__main__':
    publish(changes(), 'order-global-fc-admin-consumer-20261021-v1')
