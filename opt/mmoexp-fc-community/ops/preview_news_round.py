"""Publish exactly three authorized TEST PREVIEW messages to the test guild only."""
import asyncio
import json
import sys
import time
from pathlib import Path

stage=Path('/opt/mmoexp-fc-news-stage-20261108-core')
sys.path[:0]=[str(stage/'mmoexp-fc-pilot'),str(stage)]
from discord_ops import identity, request
from collector_router import fetch_remote_html
from news_feed import NewsStore, parse_ea_listing, news_embed, publish_pending

CHANNEL='1568260661010497627'
GUILD='1565922092518613064'
identity()
channel=request('GET','channels/'+CHANNEL)
if channel.get('guild_id')!=GUILD:
    raise SystemExit('Not the authorized test guild')
path=stage/'news-preview.sqlite3'
if path.exists():
    raise SystemExit('Preview already initialized; inspect receipts before retrying')
# Public 183 response fixture was independently fetched and verified this session.
rows=parse_ea_listing(json.loads((stage/'ea-183-fixture.json').read_text())['html'])
rows[0]['title']='TEST PREVIEW — '+rows[0]['title']
store=NewsStore(path)
batch=store.begin_cycle(21600)
store.ingest(rows,batch_id=batch)
store.finish_cycle(batch,{'ea':{'ok':True,'collector':'183'}})
receipts=[]
async def sender(item,channel_id):
    if str(channel_id)!=CHANNEL:
        raise RuntimeError('Unexpected channel')
    result=request('POST','channels/'+CHANNEL+'/messages',{
        'content':'TEST PREVIEW — news center '+item['delivery_mode']+' delivery',
        'embeds':[news_embed(item).to_dict()], 'allowed_mentions':{'parse':[]}})
    receipts.append(dict(id=result['id'],url=item['url'],mode=item['delivery_mode']))
    return result['id']
async def main():
    if await publish_pending(store,CHANNEL,sender,limit=1)!=1:
        raise RuntimeError('Automatic preview was not acknowledged')
    for n in (1,2):
        store.enqueue_article(rows[0]['url'],title='TEST PREVIEW — Manual repeat '+str(n),
                              summary='Same EA article link, submitted manually again; manual publication has no duplicate limit.',actor='isolated-verification')
    if await publish_pending(store,CHANNEL,sender,limit=2)!=2:
        raise RuntimeError('Manual previews were not acknowledged')
asyncio.run(main())
for record in receipts:
    message=request('GET','channels/'+CHANNEL+'/messages/'+record['id'])
    if message['author']['id']!='1568239618111832094' or message['embeds'][0]['url']!=record['url']:
        raise RuntimeError('Preview readback mismatch')
result={'channel_id':CHANNEL,'guild_id':GUILD,'messages':receipts,'verified_at':int(time.time())}
(stage/'news-preview-receipts.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
