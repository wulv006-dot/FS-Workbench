"""Suggest up to two matches for a human Smart Score check. Never posts to Discord."""

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo


LONDON = ZoneInfo('Europe/London')


def shortlist(now, search, model):
    if now.tzinfo is None:
        raise ValueError('A timezone-aware clock is required')
    local = now.astimezone(LONDON)
    first = local.date()
    second = first + dt.timedelta(days=1)
    search_prompt = (
        'Today is {} in London. Find football fixtures on {} or {} in the '
        'five major European leagues, major cups, international or world '
        'competitions. Choose up to three web searches yourself. '
        'Return only JSON: {{"queries":["..."]}}.'
    ).format(local.date().isoformat(), first.isoformat(), second.isoformat())
    plan = json.loads(model(search_prompt, '', 160))
    if not isinstance(plan, dict) or not isinstance(plan.get('queries'), list):
        raise ValueError('Invalid Hermes search plan')
    queries = [query.strip() for query in plan['queries'][:3]
               if isinstance(query, str) and 0 < len(query.strip()) <= 128]
    evidence = []
    for query in queries:
        for row in search(query).get('results', [])[:4]:
            if isinstance(row, dict):
                evidence.append((str(row.get('title') or '') + ' | ' +
                                 str(row.get('snippet') or row.get('summary') or ''))[:230])
    if not evidence:
        return []
    prompt = (
        'Today is {} in London. From these web results, pick up to two football '
        'matches worth discussing in our FC27 community on {} or {}. Scope: '
        'five major European leagues, major cups, international and world '
        'competitions. A quiet day may have no picks. Do not invent fixtures. '
        'Add a short English discussion question for each pick. Return only '
        'JSON: {{"matches":[{{"home":"","away":"","competition":"",'
        '"date":"YYYY-MM-DD","question":""}}]}}. No search recap.'
    ).format(local.date().isoformat(), first.isoformat(), second.isoformat())
    raw = model(prompt, '\n'.join(evidence), 320)
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('matches'), list):
        raise ValueError('Invalid Hermes shortlist')
    selected = []
    for item in data['matches'][:2]:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str)
                                              for key in ('home', 'away', 'competition', 'date')):
            continue
        if item['date'] not in (first.isoformat(), second.isoformat()):
            continue
        if not all(1 < len(item[key].strip()) <= 60
                   for key in ('home', 'away', 'competition')):
            continue
        match = {key: item[key].strip() for key in
                 ('home', 'away', 'competition', 'date')}
        question = item.get('question')
        if (isinstance(question, str) and 8 <= len(question.strip()) <= 160 and
                '\n' not in question and '\r' not in question):
            match['question'] = question.strip()
        selected.append(match)
    return selected


def main():
    from discovery import DeepSeek
    from direct_provider import MODEL, request_model
    from proxy_gateway import schemas

    def model(system, evidence, limit):
        result = request_model({
            'model': MODEL,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': evidence}],
            'max_tokens': limit, 'tools': [], 'stream': False,
            'enable_thinking': False, 'reasoning_effort': 'low',
        }, schemas(), native_chat=True)
        if result.get('status') or result.get('choices', [{}])[0].get('finish_reason') != 'stop':
            raise RuntimeError('Hermes shortlist unavailable')
        return result['choices'][0]['message']['content']

    now = dt.datetime.now(dt.timezone.utc)
    matches = shortlist(now, DeepSeek().search, model)
    result = json.dumps({
        'generated_at_utc': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'matches': matches,
        'next_step': 'check_each_in_smart_score',
    }, ensure_ascii=False)
    output = os.environ.get('FC27_SCOUT_OUTPUT')
    if output:
        target = Path(output)
        temporary = target.with_name(target.name + '.tmp')
        temporary.write_text(result + '\n', encoding='utf-8')
        temporary.replace(target)
    print(result)


if __name__ == '__main__':
    main()
