"""Prepare the user-supplied FC calendar without touching the blocked live inbox."""
import copy
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
module = ROOT.parent / 'game-monitor-autopublish-20261022/source'
if not module.is_dir():
    module = ROOT.parent / 'game_monitor_static_fill_20261022/compat/source'
sys.path.insert(0, str(module))
from contract import slots, snapshot, safe_changes, sop

before = (ROOT / 'before.html').read_bytes()
assert hashlib.sha256(before).hexdigest() == 'bbc5e18dbee322364155e3e4718bd2ba85f7a9de5f08066399d5a6affa0ee7a0'
calendar = json.loads((ROOT / 'calendar.json').read_text(encoding='utf8'))
rows = calendar['events']
assert len(rows) == 18 and len({r[1] for r in rows}) == 18
assert sum(r[5] == '官方确认' for r in rows) == 5
assert all(len(r) == 8 and date.fromisoformat(r[2]) <= date.fromisoformat(r[3]) and 1 <= r[7] <= 5 for r in rows)
data = snapshot(before)
game = copy.deepcopy(data['ea-sports-fc']['game'])
original_count = len(game['events'])
game['activity_calendar'] = calendar
pb = game['phaseboard']
pb['generated_at'] = '2026-11-03'
pb['current_stage_banner'].update(latest_promo='Ultimate Scream', promo_status='表列活动期：10-23 至 11-06',
    season='FC27 Ultimate Team', week='赛季周次未核', demand='未核', risk='未核',
    action='下一节点：11-06 UEFA Primetime（社区追踪）；黑五11-27、TOTY 01-21、TOTS 04-23重点关注，评级沿原表。')
for node in pb['timeline']:
    # Remove stale cached statuses so the existing renderer derives them by date.
    node.pop('status', None)
for index, (cn, en, start, end, kind, source, detail, stars) in enumerate(rows, 1):
    pb['timeline'].append(dict(id=f'fc27-calendar-{index:02d}', primary_category='活动·卡池',
        secondary_category=kind, title_human=cn, title_raw=en, start=start, end=end,
        granularity='promo', credibility=f'{source}（原表标注）', impact_products=['FC Coins'],
        impact_direction='', action='原表市场等级：' + '★'*stars + '☆'*(5-stars),
        source=calendar['source'], note=detail + ' ' + calendar['source_note'], nested=[]))
safe_changes(data['ea-sports-fc']['game'], game)
updated = copy.deepcopy(data['ea-sports-fc'])
updated['game'] = game
sop(updated)
text = before.decode('utf8')
a, b, _ = slots(text)['ea-sports-fc']['game']
text = text[:a] + json.dumps(game, ensure_ascii=False, separators=(',', ':')) + text[b:]
needle = '  const timelineHtml=dailyIntelHtml(g)+(phaseHtml||nodesHtml);'
assert text.count(needle) == 1
replacement = '''  const calendar=g.activity_calendar;
  const calendarHtml=calendar?`<section aria-label="FC27活动日历"><div class="gv-lv1-title">📅 FC27 活动日历</div><p>${esc(calendar.source)}。${esc(calendar.source_note)}</p><div class="gvg-stack">${gvGuideBlk(calendar.events.map(r=>[r[0]+" · "+r[1],r[2]+" 至 "+r[3]+"｜"+r[4]+"｜"+r[5]+"（原表标注）｜市场等级："+"★".repeat(r[7])+"☆".repeat(5-r[7])+"。"+r[6]]))}</div></section>`:"";
  const timelineHtml=dailyIntelHtml(g)+calendarHtml+(phaseHtml||nodesHtml);'''
after = text.replace(needle, replacement, 1).encode('utf8')
actual = snapshot(after)
assert actual['ea-sports-fc'] == updated
assert all(actual[k] == v for k, v in data.items() if k != 'ea-sports-fc')
assert len(actual['ea-sports-fc']['game']['events']) == original_count
assert game['events'][:original_count] == data['ea-sports-fc']['game']['events']
proof = dict(status='candidate_only_not_published', game='ea-sports-fc', calendar_events=18,
    official_as_labeled=5, community_tracking=13, other_games_unchanged=True,
    original_events_preserved=True, original_automation_unchanged=True,
    before_sha256=hashlib.sha256(before).hexdigest(), after_sha256=hashlib.sha256(after).hexdigest(),
    checks=['date ranges', 'source labels', 'market ratings', 'existing SOP', 'non-target data equality'])
if sys.argv[1:] == ['--check']:
    assert (ROOT / 'index.html').read_bytes() == after, 'candidate differs from rebuilt payload'
    assert json.loads((ROOT / 'proof.json').read_text(encoding='utf8')) == proof
else:
    (ROOT / 'index.html').write_bytes(after)
    (ROOT / 'fc-game.json').write_text(json.dumps(game, ensure_ascii=False, indent=2), encoding='utf8')
    (ROOT / 'proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(proof, ensure_ascii=False))
