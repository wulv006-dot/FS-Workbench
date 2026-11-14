"""Print channel metadata only; token is consumed from the service environment."""

import json
import os
import sys
import urllib.request


GUILDS = {'1565922092518613064', '1041923524601851914'}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in GUILDS:
        raise SystemExit('Choose a known guild')
    token = os.environ['DISCORD_BOT_TOKEN']
    request = urllib.request.Request(
        'https://discord.com/api/v10/guilds/%s/channels' % sys.argv[1],
        headers={'Authorization': 'Bot ' + token, 'Accept': 'application/json',
                 'User-Agent': 'DiscordBot (https://www.mmoexp.com, 0.1)'},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        channels = json.load(response)
    for row in sorted(channels, key=lambda item: (item.get('position', 0), item.get('id', ''))):
        print(json.dumps({'guild_id': sys.argv[1], 'id': row['id'], 'name': row['name'], 'type': row['type'],
                          'parent_id': row.get('parent_id'), 'position': row.get('position'),
                          'overwrites': [{'id': x['id'], 'type': x['type'],
                                          'allow': x.get('allow'), 'deny': x.get('deny')}
                                         for x in row.get('permission_overwrites', [])]},
                         separators=(',', ':')))


if __name__ == '__main__':
    main()
