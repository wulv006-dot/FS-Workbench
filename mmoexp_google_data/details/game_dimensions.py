"""Read-only game projections. Preserve source totals and unresolved mappings."""
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, unquote

VERSION = 'traffic-game-projections-20261019-v1'
ALIASES = {'FC27':'FC27','RS':'RS','D4':'D4','A2':'AION2','Madden':'MADDEN',
           'POE2':'POE2','ARC':'ARC','WOW Forever':'WOW_FOREVER',
           'Maplestory Classic World':'MSCW','Monopoly Go':'MONOPOLY_GO'}
LABELS = {'FC27':'FC27','FC26':'FC26','D4':'Diablo IV','AION2':'Aion2','RS':'RuneScape',
          'MADDEN':'Madden','POE2':'POE2','ARC':'ARC Raiders','WOW_FOREVER':'WoW Forever',
          'MSCW':'MapleStory Classic World','MONOPOLY_GO':'Monopoly Go','NBA2K':'NBA2K','MLB':'MLB',
          'GLOBAL':'全局品牌 / 通用','UNKNOWN':'未映射 / 待核'}
PATHS = {'fc-27':'FC27','fc-26':'FC26','diablo-4':'D4','aion-2':'AION2','aion2':'AION2',
         'path-of-exile-2':'POE2','poe-2':'POE2','poe2':'POE2','arc-raiders':'ARC',
         'madden-nfl-27':'MADDEN','madden-27':'MADDEN','nba-2k27':'NBA2K','nba2k27':'NBA2K',
         'mlb-the-show-26':'MLB','mlb-26':'MLB','monopoly-go':'MONOPOLY_GO',
         'maplestory-classic-world':'MSCW','wow-forever':'WOW_FOREVER'}

def campaign_mapping():
    data=json.loads(Path(__file__).with_name('game_mapping_20261019.json').read_text())
    result=defaultdict(set)
    for row in data['rows']:
        result[row['campaign_name'].strip().casefold()].add(ALIASES.get(row['game_label'], 'UNKNOWN'))
    return result

CAMPAIGNS=campaign_mapping()

def classify_campaign(name):
    key=re.sub(r'^(?:google|bing)-','',str(name or '').strip(),flags=re.I).casefold()
    if key=='fc27-pmax-coins-us': return {'game':'GLOBAL','basis':'user_confirmed_cross_game'}
    games=CAMPAIGNS.get(key,set())
    if len(games)==1 and 'UNKNOWN' not in games:
        return {'game':next(iter(games)),'basis':'user_supplied_campaign_name_mapping'}
    return {'game':'UNKNOWN','basis':'conflicting_mapping' if games else 'unmapped_campaign'}

def classify_page(value):
    path=unquote(urlsplit(str(value or '')).path).strip('/').casefold()
    parts=path.split('/')
    if parts and parts[0] in ('es','de','fr','it','pt','nl','ja','ko','ru','zh'):
        parts=parts[1:]
    if not parts or not parts[0]:return {'game':'GLOBAL','basis':'site_home'}
    if parts[0] in PATHS:return {'game':PATHS[parts[0]],'basis':'explicit_game_path'}
    # News names are hints only; preserve this distinction in every consumer.
    if parts[0]=='news' and len(parts)>1:
        matches={game for prefix,game in PATHS.items() if parts[1].startswith(prefix+'-')}
        if len(matches)==1:return {'game':next(iter(matches)),'basis':'news_slug_hint'}
    return {'game':'UNKNOWN','basis':'unmapped_page'}

def aggregate(rows, source):
    if not rows:return None
    keys=('sessions',) if source=='ga4' else ('clicks','impressions')
    result={k:str(sum(Decimal(str(r['metrics'][k])) for r in rows)) for k in keys}
    if source=='gsc':
        impressions=Decimal(result['impressions'])
        result['ctr']=str(Decimal(result['clicks'])/impressions) if impressions else None
        result['position']=str(sum(Decimal(str(r['metrics']['position']))*Decimal(str(r['metrics']['impressions'])) for r in rows)/impressions) if impressions else None
    # Do not sum activeUsers or average bounce rates across landing pages.
    return result

def project(report, source, page_dimension, extra_dimension=None):
    groups=defaultdict(list);bases=defaultdict(set)
    for row in (report or {}).get('rows',[]):
        match=classify_page(row.get('dimensions',{}).get(page_dimension))
        key=(match['game'],row.get('dimensions',{}).get(extra_dimension)) if extra_dimension else (match['game'],None)
        groups[key].append(row);bases[key].add(match['basis'])
    metric='sessions' if source=='ga4' else 'clicks'
    rows=[{'game':game,'label':LABELS.get(game,game),'dimension':dimension,
           'metrics':aggregate(items,source),'basis':sorted(bases[(game,dimension)]),'row_count':len(items)}
          for (game,dimension),items in groups.items()]
    rows.sort(key=lambda r:Decimal(r['metrics'][metric]),reverse=True)
    quality=(report or {}).get('quality',{})
    attempt=(report or {}).get('last_attempt',{})
    return {'version':VERSION,'rows':rows,'status':'unavailable' if report is None else 'stale' if attempt.get('status') in ('failed','empty') else 'partial' if not quality.get('pagination_complete') or any(quality.get(k) for k in ('sampling_present','subject_to_thresholding','data_loss_from_other_row','top_rows_not_all_queries')) else 'available',
            'basis':'landing_page_sessions' if source=='ga4' else 'search_page_rows',
            'source_quality':quality,'returned_rows':len((report or {}).get('rows',[])),
            'not_site_total':True,'active_users_not_additive':True,'collected_at':(report or {}).get('collected_at')}
