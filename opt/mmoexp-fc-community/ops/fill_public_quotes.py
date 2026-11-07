"""Fill missing authorized category entries without reposting existing cards."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, '/opt/mmoexp-fc-news-stage-20261108-core')
from discord_ops import request, identity, APP
sys.path.insert(0, '/opt/mmoexp-fc-community')
from quote_panel import CategoryHomeView, category_embed

CHANNELS={'sbc':'1301379787696377926','packs':'1568610700463710278',
 'gallery':'1568610467587563591','evolutions':'1372781247847465000',
 'boosting':'1568610224502345758','coins':'1568663210901504041'}
MARKER=Path('/opt/mmoexp-fc-community/var/quote-fill-20261108.json')

def save(data):
    temp=MARKER.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2))
    temp.replace(MARKER)

async def main():
    identity()
    config=json.loads(Path('/opt/mmoexp-fc-community/content.config.json').read_text())
    marker=json.loads(MARKER.read_text()) if MARKER.exists() else {}
    result=[]
    for kind,channel in CHANNELS.items():
        meta=request('GET','channels/'+channel)
        if meta['guild_id']!='1041923524601851914': raise RuntimeError('Wrong guild')
        messages=request('GET','channels/'+channel+'/messages?limit=100')
        found=[m for m in messages if m['author']['id']==APP and
               any(c.get('custom_id')=='fc:quote:'+kind for row in m.get('components',[]) for c in row.get('components',[]))]
        if found:
            result.append({'kind':kind,'channel':channel,'status':'existing','message':found[0]['id']})
            continue
        if kind in marker:
            raise RuntimeError('Existing or ambiguous send marker; reconcile before another send')
        if '--apply' not in sys.argv:
            result.append({'kind':kind,'channel':channel,'status':'missing'})
            continue
        marker[kind]={'status':'sending','channel':channel}; save(marker)
        presentation=config.get('quote_presentation')
        view=CategoryHomeView(None,kind,presentation=presentation)
        sent=request('POST','channels/'+channel+'/messages',
                     {'embeds':[category_embed(kind,presentation).to_dict()],
                      'components':view.to_components(),'allowed_mentions':{'parse':[]}})
        marker[kind]={'status':'published','channel':channel,'message':sent['id']}; save(marker)
        check=request('GET','channels/'+channel+'/messages/'+sent['id'])
        if check['author']['id']!=APP or not check.get('components'): raise RuntimeError('Readback failed')
        result.append(dict(marker[kind],kind=kind))
    print(json.dumps(result))

asyncio.run(main())
