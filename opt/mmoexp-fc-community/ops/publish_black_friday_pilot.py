"""Publish only the fixture pilot into D4 VIP. On uncertain POST, reconcile before retrying."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/opt/mmoexp-fc-community/ops')
from discord_ops import APP, identity, request

GUILD = '1565922092518613064'
CHANNEL = '1568260661010497627'
STATE = Path('/var/lib/fc27-black-friday-pilot')
ROUTE = 'channels/' + CHANNEL + '/messages'
TITLE = '🎰  FC27 Black Friday Mystery Drop'
IDS = ['bf26:pilot:start','bf26:pilot:examples']


def verify(row):
    if (row['author']['id'] != APP or row['channel_id'] != CHANNEL
        or row['embeds'][0]['title'] != TITLE
        or [b['custom_id'] for b in row['components'][0]['components']] != IDS):
        raise RuntimeError('Unexpected test message')
    return row['id']


def main():
    identity()
    ch = request('GET','channels/'+CHANNEL)
    if ch['guild_id'] != GUILD or ch['name'] != 'fc27-bot-test':
        raise RuntimeError('Wrong channel')
    marker = STATE/'message.id'
    if not marker.exists():
        pending = STATE/'publish.pending'
        if pending.exists():
            matches = [m for m in request('GET',ROUTE+'?limit=100') if m.get('author',{}).get('id')==APP
                       and m.get('embeds') and m['embeds'][0].get('title')==TITLE]
            if len(matches) != 1:
                raise RuntimeError('Uncertain prior publish. Reconcile manually.')
            ident = verify(matches[0])
        else:
            with pending.open('x') as f:
                f.write('D4 VIP pilot')
            card = {'title':TITLE, 'color':0xE4AF45,
                    'description':('Support a club. Verify your test email. Reveal your reward.\n\n'
                    '**$1 OFF  ·  $2 OFF  ·  $2 + 20% OFF**\n'
                    'Your MMOEXP orders across all games since Oct 1 determine your drop. '
                    'Five completed orders unlock the extra 20% coupon.'),
                    'footer':{'text':'D4 VIP PLAYTEST · Demo accounts only · No real coupons issued'}}
            buttons = [{'type':2,'style':style,'custom_id':ident,'label':label,'emoji':{'name':emoji}}
                       for ident,style,label,emoji in zip(IDS,[1,2],['Play the test drop','See all test cases'],['🎰','📋'])]
            sent = request('POST',ROUTE,{'embeds':[card],'components':[{'type':1,'components':buttons}],
                                         'allowed_mentions':{'parse':[]}})
            ident = verify(sent)
        temp = STATE/'message.next'
        temp.write_text(ident)
        temp.replace(marker)
    ident = verify(request('GET',ROUTE+'/'+marker.read_text().strip()))
    print(json.dumps({'guild':GUILD,'channel':CHANNEL,'message':ident,'mode':'fixture'}))


if __name__ == '__main__':
    main()
