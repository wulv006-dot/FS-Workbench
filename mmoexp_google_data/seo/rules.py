"""Daily evidence rules over frozen facts, independently of AI."""
import datetime as dt
from decimal import Decimal
from .metrics import number


def evaluate(history):
    usable = [r for r in history if r['metrics'].get('gsc') is not None][-14:]
    if len(usable) < 14 or any((dt.date.fromisoformat(b['source_date'])-dt.date.fromisoformat(a['source_date'])).days != 1 for a,b in zip(usable,usable[1:])):
        return [dict(kind='insufficient_comparable_history', message='暂缺连续14个完整GSC源日，不判断搜索下跌。')]
    previous = sum((number(r['metrics']['gsc']['clicks']) for r in usable[:7]), Decimal(0))
    current = sum((number(r['metrics']['gsc']['clicks']) for r in usable[7:]), Decimal(0))
    if previous >= 100 and previous-current >= 30 and (current-previous)/previous <= Decimal('-.2'):
        return [dict(kind='click_decline', message='最近7个可比源日的搜索点击下降，建议优先检查主要页面。',
                     previous_clicks=str(previous), current_clicks=str(current), change=str((current-previous)/previous),
                     evidence_start=usable[0]['source_date'], evidence_end=usable[-1]['source_date'])]
    return []
