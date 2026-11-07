"""Clarify a geographic club group; retain every role and component."""
import hashlib
from pathlib import Path
import shutil
import sys
sys.path.insert(0,'/opt/mmoexp-fc-news-stage-20261108-core')
from discord_ops import request, identity, APP
from deploy_news_center import atomic
identity()
path=Path('/opt/mmoexp-fc-community/club_panel.py')
raw=path.read_bytes()
if hashlib.sha256(raw).hexdigest()!='431b250f8115c9c7b399e8279f6b08f91c1dd747857143bed0123bf7c528fb4a':
    raise RuntimeError('Club source drift')
changed=raw.replace(b"title = 'English clubs'",b"title = 'English football clubs'")
if changed==raw: raise RuntimeError('Title not found')
backup=Path('/opt/mmoexp-fc-community/backups/club-title-20261108.py')
if backup.exists(): raise RuntimeError('Backup exists')
shutil.copy2(path,backup)
atomic(path,changed)
route='channels/1568663362567413820/messages/1568666885321400411'
message=request('GET',route)
if message['author']['id']!=APP or len(message['embeds'])!=1: raise RuntimeError('Wrong welcome message')
embed=message['embeds'][0]
embed['title']='English football clubs'
request('PATCH',route,{'embeds':[embed],'allowed_mentions':{'parse':[]}})
verified=request('GET',route)
assert verified['embeds'][0]['title']=='English football clubs'
assert verified['components']==message['components']
print('Welcome title clarified; 25 club buttons unchanged. No restart.')
