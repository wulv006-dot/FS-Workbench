"""Bounded public FC 27 lookups. Only aggregate usage counters persist."""
import asyncio
import hashlib
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

DOMAINS = ('fut.gg', 'futbin.com', 'ea.com')
PROMO = re.compile(r'thunderstruck|雷霆卡?|\b(?:totw|rttk|toty|tots)\b', re.I)
FRESH = re.compile(r'new|latest|today|upgrade|leak|tracker|rating|最新|今天|升级|爆料|属性', re.I)
FUT = re.compile(r'\b(?:cards?|fut|fc\s?27|sbc|evo|promo)\b|球员|阵容|进化|球卡', re.I)
SENSITIVE = re.compile(r'@|https?://|\b\d{7,}\b|\b(?:order|email|password|coupon|refund)\b|订单|邮箱', re.I)
NO_FACT = "I couldn't verify that FC 27 update yet. Check the current cards on FUT.GG: <https://www.fut.gg/>"


def relevant(text):
    return not SENSITIVE.search(text) and bool(PROMO.search(text) or (FRESH.search(text) and FUT.search(text)))


def reserve(kind):
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    limit = {'lookup': 200, 'chat': 4500}[kind]
    path = Path(__file__).parent / 'var' / 'luna-usage.sqlite3'
    path.parent.mkdir(exist_ok=True)
    with closing(sqlite3.connect(str(path))) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS usage (month TEXT,kind TEXT,n INTEGER,PRIMARY KEY(month,kind))')
        db.execute('INSERT OR IGNORE INTO usage VALUES(?,?,0)', (month, kind))
        return db.execute('UPDATE usage SET n=n+1 WHERE month=? AND kind=? AND n<?',
                          (month, kind, limit)).rowcount == 1


class Lookup:
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()

    async def answer(self, key, text):
        query = ' '.join(text.split())[:220]
        digest = hashlib.sha256(query.casefold().strip('?! .').encode()).digest()
        async with self.lock:
            now = time.monotonic()
            self.cache = {k:v for k,v in self.cache.items() if v[0] > now}
            if digest in self.cache:
                return self.cache[digest][1]
            if not reserve('lookup'):
                return NO_FACT
            answer = NO_FACT
            payload = dict(model='gpt-6-luna', store=False, reasoning={'effort':'low'},
                tools=[{'type':'web_search', 'search_context_size':'low', 'filters':{'allowed_domains':DOMAINS}}],
                tool_choice='required', max_tool_calls=1, max_output_tokens=480,
                instructions="Answer a Discord FUT player in English in two short sentences. Verify the EA FC 27 season and date. Use only facts supported by EA, FUTBIN or FUT.GG. Distinguish confirmed updates from rumours. If no reliable match, say so. Give one useful squad implication if supported. No commerce claims, mentions or raw URLs. Cite the source.",
                input='As of {} UTC, question: {}'.format(datetime.now(timezone.utc).date(), query))
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=24)) as http:
                    async with http.post('https://api.openai.com/v1/responses',json=payload,
                            headers={'Authorization':'Bearer '+key}) as response:
                        response.raise_for_status()
                        data = await response.json()
                for item in data.get('output', []):
                    for part in item.get('content', []):
                        links = []
                        for ref in part.get('annotations', []):
                            url = ref.get('url','')
                            host = urlsplit(url).hostname or ''
                            if url.startswith('https://') and any(host == d or host.endswith('.'+d) for d in DOMAINS):
                                links.append(url.split('?utm_source=')[0])
                        if links and part.get('type') == 'output_text':
                            clean = re.sub(r'\[([^\]]*)\]\(https?://[^)]+\)', r'\1', part['text'])
                            clean = re.sub(r'https?://\S+|<[^>]+>|@', '', clean).strip()
                            if clean:
                                answer = clean[:550] + '\n' + ' '.join('<'+u+'>' for u in dict.fromkeys(links[:2]))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                pass
            self.cache[digest] = (now + (300 if answer == NO_FACT else 3600), answer)
            return answer
