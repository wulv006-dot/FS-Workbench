"""One bounded explanation over projected facts; uses the existing model and key path."""
import json
import os
from pathlib import Path
import re
import stat
import time
import urllib.error
import urllib.request
from fc_daily_model import MODEL, ENDPOINT, NoRedirect


def clean_question(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 600:
        raise ValueError('question_length')
    value = value.strip()
    # Free-form conversation never becomes a credential/order upload route.
    if re.search(r'sk-[A-Za-z0-9]|Bearer\s|password\s*[:=]|密码\s*[:：=]|Cookie\s*[:=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|\b\d{10,}\b', value, re.I):
        raise ValueError('sensitive_question')
    return value


def projection(report, question=None, context=()):
    facts = []
    for item in report['projects']:
        for key in ('orders', 'revenueUsd', 'newCustomers', 'repeatRatePct', 'fulfillmentRatePct'):
            metric = item.get('metrics', {}).get(key, {})
            if metric.get('value') is not None:
                facts.append({'ref': item['key']+'.'+key, 'value': metric['value'],
                              'source': metric['source'], 'scope': metric['scope']})
    return {'contract': 'fs-advisor-model-v1', 'period': report['period'],
            'facts': facts, 'coverage': report['coverage'],
            'question': clean_question(question) if question else None,
            'previous_questions': [clean_question(x) for x in list(context)[-3:]]}


def validate(raw, projected):
    if raw.get('model') != MODEL or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', raw.get('id', '')):
        raise ValueError('response_identity')
    choice = raw['choices'][0]
    if choice.get('finish_reason') != 'stop': raise ValueError('incomplete_response')
    item = json.loads(choice['message']['content'])
    if set(item) != {'analysis', 'suggestion', 'references'}: raise ValueError('response_shape')
    refs = {f['ref'] for f in projected['facts']}
    if not isinstance(item['references'], list) or not 1 <= len(item['references']) <= 4 or any(x not in refs for x in item['references']):
        raise ValueError('unsupported_reference')
    for key in ('analysis', 'suggestion'):
        text = item[key]
        if not isinstance(text, str) or not 4 <= len(text) <= 180 or re.search(r'\d|[$¥%<>]|已执行|已调整|已派单|已退款|保证|联网|搜索到|自动改价|立即调价', text):
            raise ValueError('unsupported_statement')
    usage = raw.get('usage', {})
    if any(type(usage.get(k)) is not int or not 0 <= usage[k] <= 12000 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
        raise ValueError('invalid_usage')
    if usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
        raise ValueError('invalid_usage')
    return dict(status='succeeded', model=MODEL, response_id=raw['id'], tokens=usage['total_tokens'], **item)


def request_model(messages, projected, validator, *, max_tokens=220, timeout=40, tools=None, reasoning_effort=None):
    return {'status': 'retired', 'replacement': '/dashboard/fs-home/hermes/index.html', 'reason': 'legacy_bailian_analysis_retired'}


def explain(projected):
    return {'status': 'retired', 'replacement': '/dashboard/fs-home/hermes/index.html', 'reason': 'legacy_bailian_analysis_retired'}


def explain_boss(projected):
    from boss_insights import build_messages, validate_response
    return request_model(build_messages(dict(projected,request_id='bounded_model_request')),projected,validate_response)
