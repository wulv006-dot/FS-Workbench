"""Fixture-only browser regression for the user analysis dashboard."""
from datetime import date, timedelta
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[4]
UI = Path(__file__).resolve().parents[1] / 'ui'
URL = 'https://fs.invalid/dashboard/users/'
SHARED = {
    'fs-tokens.css': 'ui-system/tokens/fs-tokens.css',
    'fs-ui.css': 'ui-system/components/fs-ui.css',
    'fs-theme.js': 'ui-system/adapters/fs-theme.js',
}


def summary(query):
    windows = list(map(int, query.get('windows', ['30,90,180'])[0].split(',')))
    after, within = int(query['return_after'][0]), int(query['return_within'][0])
    batches = []
    for month, population, observing in [('2026-01', 101, 0), ('2026-02', 127, 0),
                                         ('2026-03', 98, 0), ('2026-04', 120, 0),
                                         ('2026-05', 111, 3), ('2026-06', 0, 0)]:
        if not query['cohort_start'][0] <= month <= query['cohort_end'][0]:
            continue
        cells = []
        for days in windows:
            watching = observing if days >= 180 else 0
            gap = 2 if month == '2026-04' else 0
            if month == '2026-03' and days >= 180:
                gap = population  # every customer excluded: not the same as an empty cohort
            denominator = population - watching - gap
            numerator = min({30: 32, 90: 48}.get(days, 52), denominator)
            cells.append(dict(days=days, group=f'cohort:{month}:{days}', observing=watching, coverage_gap=gap,
                              denominator=denominator, numerator=numerator,
                              rate=numerator/denominator if denominator else None,
                              repeat_amount=dict(known_usd='250.00' if denominator else None, unknown_orders=0),
                              repeat_per_customer_usd='5.00' if denominator else None))
        mature = cells[-1]
        cumulative = [min(cell['numerator'], mature['numerator']) for cell in cells]
        buckets = [value - previous for value, previous in zip(cumulative, [0] + cumulative)]
        buckets.append(mature['denominator'] - cumulative[-1])
        returning = {'2026-01': 3, '2026-02': 5, '2026-03': 6, '2026-04': 7, '2026-05': 4}.get(month, 0)
        batches.append(dict(month=month, windows=cells, pending_classification=1,
                            first_repeat=dict(boundaries=windows, counts=buckets),
                            silent_return=dict(after_days=after, within_days=within, numerator=returning,
                                               denominator=68 if population else 0, rate=returning/68 if population else None,
                                               return_amount=dict(known_usd=None if month == '2026-01' else str(returning * 47) if population else '0',
                                                                  unknown_orders=3 if month == '2026-01' else int(month == '2026-04')))))
    cohort_type = query.get('cohort_type', ['new'])[0]
    cohorts = dict(batches=batches)
    if cohort_type == 'compare':
        import copy
        old = copy.deepcopy(batches)
        for batch in old:
            for cell in batch['windows']:
                cell['group'] = 'cohort:old:' + batch['month'] + ':' + str(cell['days'])
                cell['numerator'] = cell['numerator'] // 2
                cell['rate'] = cell['numerator'] / cell['denominator'] if cell['denominator'] else None
                if batch['month'] == '2026-06':
                    # A month with old customers but no eligible new customers.
                    cell.update(denominator=10, numerator=4, rate=.4)
            if batch['month'] == '2026-06':
                batch['first_repeat']['counts'] = [2, 1, 1, 6]
        cohorts['compare'] = dict(segment='old', batches=old)
    return dict(contract_version='fs-users-v4', snapshot_id='browser-fixture', config_version=2,
                observation_date='2026-11-23', query=dict(game=query['game'][0], windows=windows, cohort_type=cohort_type,
                return_after=after, return_within=within, start=query['start'][0], end_exclusive=query['end_exclusive'][0]),
                coverage=dict(order_missing_days=1, new_customer_flags=dict(status='complete')),
                cohorts=cohorts, stages=dict(
                    stages=[dict(kind=kind, group=f'stage:{kind}', count=count) for kind, count in
                            [('recent', 20), ('silent', 12), ('lost', 5), ('long_lost', 2), ('unverified', 1)]],
                    inflow=[dict(kind='silent', group='entered:silent', count=12)],
                    returns=[dict(kind='any', group='return:any', count=6)],
                    daily_returns=[dict(date=(date(2026, 11, 1) + timedelta(days=day)).isoformat(),
                                        silent_wakeup=None if day == 12 else 3 + (day * 7 % 6),
                                        lost_return=None if day == 12 else 1 + (day * 5 % 4))
                                   for day in range(23)],
                    cross_game_flow=[]))


def install(page):
    def route(request):
        url = urlsplit(request.request.url)
        name = url.path.rsplit('/', 1)[-1]
        query = parse_qs(url.query)
        if name in SHARED:
            return request.fulfill(path=ROOT / SHARED[name])
        if name in ('', 'users.js', 'users.css'):
            return request.fulfill(path=UI / (name or 'index.html'))
        if name == 'data.json':
            if query.get('action') == ['catalog']:
                return request.fulfill(json=dict(contract_version='fs-users-v4', history_backfill_start='2026-01-01',
                                                weekly_update=dict(cutoff='2026-11-24T00:00:00+08:00'),
                                                projects={'1327': dict(label='FC27', series='FC'), '833': dict(label='FC26', series='FC')}))
            return request.fulfill(json=summary(query))
        if name == 'private.json' and query['action'] == ['members']:
            assert query['group'] in (['cohort:2026-04:180'], ['cohort:old:2026-04:180'])
            return request.fulfill(json=dict(total=1, next_cursor=None, rows=[
                dict(email='cohort@example.invalid', customer_id='client', stage='recent',
                     window_status='denominator', in_numerator=True)]))
        return request.fulfill(status=404, body='')

    page.route('**/*', route)


def check_page(browser, output=None):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, color_scheme='light')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    install(page)
    page.goto(URL)
    expect(page.locator('#cohort-kpis')).to_contain_text('2026-04')
    expect(page.locator('#cohort-kpis')).to_contain_text('120')
    expect(page.locator('#repeat-finding')).to_contain_text('48')
    expect(page.locator('#return-finding')).to_contain_text('7')
    expect(page.locator('#return-finding')).to_contain_text('金额未知')
    expect(page.locator('input[name=start]')).to_have_value('2026-08-26')
    expect(page.locator('#cross-flow')).not_to_have_attribute('open', '')
    expect(page.get_by_role('img', name='各批次回头率曲线')).to_be_visible()
    # Demo layout: four cards, a conclusion line and charts; no dot-joined meta strings in cells.
    expect(page.locator('#cohort-kpis .card')).to_have_count(4)
    # FC26 and FC27 share customers: the merged series is offered as one choice.
    expect(page.locator('select[name=game] option[value="series:FC"]')).to_have_text('FC 系列（FC26 + FC27）')
    expect(page.locator('#repeat-finding')).to_contain_text('结论')
    page.get_by_role('button', name='2026-04 180 天，查看详情').click()
    drill = page.locator('#cohort-drill')
    expect(drill).to_contain_text('数据缺口 2 人')
    drill.get_by_role('button', name='查看名单').click()
    expect(page.locator('#members')).to_contain_text('cohort@example.invalid')
    expect(page.get_by_role('button', name='导出 CSV')).to_be_enabled()

    # All return amounts unknown for 2026-01: no bar is drawn and the amount is not shown as $0.
    expect(page.locator('#return-amounts svg rect')).to_have_count(4)
    expect(page.locator('#return-amounts')).to_contain_text('含 3 笔金额未知')

    # A window whose customers are all in a coverage gap stays inspectable.
    all_gap = page.get_by_role('button', name='2026-03 180 天，查看详情')
    expect(all_gap).to_contain_text('数据缺口 98')
    all_gap.click()
    expect(page.locator('#cohort-drill')).to_contain_text('数据缺口 98 人')

    # The 2026-04 coverage gap is reported next to the first-repeat distribution.
    expect(page.locator('#first-repeat-basis')).to_contain_text('有 2 人因订单数据缺口未计入')
    expect(page.locator('#first-repeat')).to_contain_text('数据缺口未计入')

    # Coverage gaps (2026-03, 2026-04) and customers still under observation (2026-05) mark both return charts.
    expect(page.locator('#return-rates svg text', has_text='部分')).to_have_count(3)
    expect(page.locator('#return-amounts svg text', has_text='部分')).to_have_count(4)

    # New-versus-old comparison: cells show the old-customer rate, the drill offers both lists.
    page.get_by_role('radio', name='新老对比').check()
    expect(page.locator('#repeat-title')).to_contain_text('新老客')
    expect(page.locator('#segment-note')).to_be_visible()
    expect(page.locator('#cohort-heat')).to_contain_text('老客')
    expect(page.locator('#cohort-kpis')).to_contain_text('老客')
    old_only = page.get_by_role('button', name='2026-06 30 天，查看详情')
    expect(old_only).to_be_enabled()
    expect(old_only).to_contain_text('老客 40.0%')
    # A mature old-customer month is shown even when that month has no mature new customers.
    expect(page.locator('#first-repeat')).to_contain_text('2026-06 老')
    expect(page.locator('#first-repeat')).not_to_contain_text('2026-06 新')
    if output:
        page.screenshot(path=output / 'users-compare.png', full_page=True, animations='disabled')
    # Each population reports its own excluded customers in comparison mode.
    expect(page.locator('#first-repeat-basis')).to_contain_text('有 4 人')
    page.get_by_role('button', name='2026-04 180 天，查看详情').click()
    page.locator('#cohort-drill').get_by_role('button', name='查看老客名单').click()
    expect(page.locator('#members')).to_contain_text('cohort@example.invalid')
    # Only an old-customer month selected: the curve still draws the old-customer line.
    page.locator('input[name=cohort_start]').fill('2026-06')
    page.locator('input[name=cohort_end]').fill('2026-06')
    page.locator('#run-query').click()
    expect(page.locator('#repeat-curve')).to_contain_text('2026-06 老客')
    expect(page.locator('#repeat-curve')).not_to_contain_text('2026-06 新客')
    page.locator('input[name=cohort_start]').fill('2026-01')
    page.locator('input[name=cohort_end]').fill('2026-06')
    page.get_by_role('radio', name='新客').check()
    expect(page.locator('#segment-note')).to_be_hidden()

    page.locator('input[name=w2]').fill('60')
    page.locator('input[name=w3]').fill('')
    page.locator('#run-query').click()
    expect(page.locator('#cohort-kpis')).to_contain_text('2026-04')
    expect(page.locator('#cohort-heat')).to_contain_text('60 天')
    expect(page.locator('#cohort-heat')).not_to_contain_text('180 天')
    # The 180-day return window now comes from the reference query; partial markers survive.
    expect(page.locator('#return-rates svg text', has_text='部分')).to_have_count(3)
    page.locator('input[name=cohort_end]').fill('2026-03')
    page.locator('#run-query').click()
    expect(page.locator('#cohort-kpis')).to_contain_text('2026-03')
    page.reload()
    expect(page.locator('#cohort-kpis')).to_contain_text('2026-04')
    for mode, width, tag in [('light', 1440, 'light'), ('dark', 1440, 'dark'), ('light', 390, '390')]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.locator('#theme').select_option(mode)
        expect(page.locator('html')).to_have_attribute('data-fs-theme', mode)
        assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
        if width == 390:
            scroll = page.locator('#cohort-heat')
            scroll.focus()
            page.keyboard.press('ArrowRight')
            page.wait_for_function('document.querySelector("#cohort-heat").scrollLeft > 0')
            scroll.evaluate('(node) => node.scrollLeft = 0')
            page.locator('#theme').evaluate('(node) => node.blur()')
            page.evaluate('scrollTo(0, 0)')
        if output:
            page.screenshot(path=output / f'users-{tag}.png', full_page=True, animations='disabled')
    assert not errors, errors
    page.close()


if __name__ == '__main__':
    captures = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('FS_BROWSER_EXECUTABLE'))
        check_page(browser, captures)
        browser.close()
    print('User analysis browser checks passed')
