"""Bounded server explanation adapter. No credentials are provisioned by this module."""
import json
import os
from pathlib import Path
import re
import stat
import urllib.request
import urllib.error

MODEL = 'deepseek-v4.1-flash'
ENDPOINT = 'https://ws-yn3l5r2y0e989yrc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions'
FOCUS = {'review_source': ('facts.orders', '核对来源覆盖及缺项。'),
         'review_issues': ('facts.issues', '在原订单后台核对问题状态，记录负责人及复核时间。'),
         'review_change': ('comparison.revenue_pct', '核对同口径的主站平台与产品结构变化。')}


def projection(report):
    """Explicit whitelist; never forward a collector response or arbitrary labels."""
    facts = report['main']
    allowed = ['review_source']
    if facts['issues']: allowed.append('review_issues')
    if report['comparison']: allowed.append('review_change')
    labels = {'platform': {'PS', 'PC', 'XBOX', 'unknown'},
              'product': {'Coins', 'Items', 'Boosting', 'Accounts', 'Top Up', '多品类', '待分类'}}
    return {'report_kind': 'day', 'period': report['period'],
            'allowed_focus_and_ref': {k: FOCUS[k][0] for k in allowed},
            'facts': {k: facts[k] for k in ('orders', 'revenue_usd', 'issues')},
            'comparison': report['comparison'],
            'structure': {key: [{k: row[k] for k in ('key', 'orders', 'revenue_usd')}
                                for row in report['dimensions'][key][:5] if row['key'] in names]
                          for key, names in labels.items()}}


def validate(raw, projected):
    if raw.get('model') != MODEL or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', raw.get('id', '')):
        raise ValueError('invalid_model_response')
    choice = raw['choices'][0]
    if choice.get('finish_reason') != 'stop': raise ValueError('incomplete_model_response')
    item = json.loads(choice['message']['content'])
    if set(item) != {'focus', 'evidence_ref', 'explanation'}: raise ValueError('invalid_model_output')
    refs = projected['allowed_focus_and_ref']
    if item['focus'] not in refs or item['evidence_ref'] != refs[item['focus']]: raise ValueError('invalid_evidence')
    explanation = item['explanation']
    if not isinstance(explanation, str) or not 8 <= len(explanation) <= 120 or re.search(r'\d|[$¥%<>]|售价|调价|降价|涨价|采购价|卖价|自动执行|无需|无须|已完成|可直接|立即', explanation):
        raise ValueError('invalid_model_output')
    usage = raw.get('usage', {})
    if any(type(usage.get(k)) is not int or not 0 <= usage[k] <= 10000 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
        raise ValueError('invalid_model_usage')
    return {'status': 'succeeded', 'model': MODEL, 'response_id': raw['id'],
            **item, 'next_step': FOCUS[item['focus']][1], 'tokens': usage['total_tokens']}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def configured():
    # Existing server configuration only; no local DPAPI transfer/fallback.
    return False


def explain(projected):
    return {'status': 'retired', 'replacement': '/dashboard/fs-home/hermes/index.html', 'reason': 'legacy_bailian_analysis_retired'}
