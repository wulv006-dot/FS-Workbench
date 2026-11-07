import json
import os
import stat
from pathlib import Path
path = '/dev/null'
info = os.lstat(path)
assert stat.S_ISCHR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
assert (os.major(info.st_rdev), os.minor(info.st_rdev)) == (1, 3)
before = {'uid': info.st_uid, 'gid': info.st_gid, 'mode': oct(stat.S_IMODE(info.st_mode)),
          'type': 'character', 'major': 1, 'minor': 3}
backup = Path('/tmp/fc27-news-route-20261108/dev-null-before.json')
with backup.open('x') as handle:
    json.dump(before, handle)
os.chown(path, 0, 0)
os.chmod(path, 0o666)
print(json.dumps({'before': before, 'after': {'uid':0, 'gid':0, 'mode':'0o666'}}))
