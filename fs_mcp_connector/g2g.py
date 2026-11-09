"""Project the existing G2G business reads without exporting credential/error bodies."""
from copy import deepcopy
import math
import re

from .redaction import redact

from .backend import BackendError


SAFE_EVENT = re.compile(
    r'\[\d{2}:\d{2}:\d{2}\] (?:开始采集（只出建议单，不改任何价）|'
    r'token 可用，剩余 -?\d+(?:\.\d+)?s|'
    r'成本完成：\d+ 区有报价 / 共 \d+ 区|'
    r'抓本店 G2G 货架 …|货架 \d+ 条，其中 Aion2 金币 \d+ 条|'
    r'执行完成：\d+ 条，回读校验通过 \d+ 条（回读等待 \d+s）)')
WITHHELD = '[原错误正文未转发：上游内容可能含凭据]'


def _redact(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact(child) for child in value]
    return value


def project(value):
    if not isinstance(value, dict):
        raise BackendError('unexpected_g2g_shape', 502)
    value = deepcopy(value)
    if 'token' in value:
        status = value.pop('token')
        if (not isinstance(status, dict) or type(status.get('ok')) is not bool
                or set(status) - {'ok', 'remaining', 'error'}):
            raise BackendError('unexpected_g2g_credential_status', 502)
        if status['ok']:
            remaining = status.get('remaining')
            if type(remaining) not in (int, float) or not math.isfinite(remaining):
                raise BackendError('unexpected_g2g_credential_status', 502)
            value['credential_status'] = dict(ok=True, remaining=remaining)
        else:
            error = status.get('error', '')
            value['credential_status'] = dict(ok=False, reason='expired' if isinstance(error, str)
                and re.fullmatch(r'token 已过期（\d+(?:\.\d+)? 秒前）', error) else 'unavailable')
    if 'logs' in value:
        if not isinstance(value['logs'], list) or not all(isinstance(line, str) for line in value['logs']):
            raise BackendError('unexpected_g2g_logs', 502)
        lines = [redact(line) for line in value['logs']]
        # G2G logs contain arbitrary upstream repr/tracebacks; redact alone cannot prove those safe.
        safe = [line if SAFE_EVENT.fullmatch(line) else WITHHELD for line in lines]
        withheld = safe.count(WITHHELD)
        value.update(logs=safe, log_coverage=dict(entries=len(lines), withheld=withheld,
                                                complete=withheld == 0))
    if 'writes' in value:
        if not isinstance(value['writes'], list) or not all(isinstance(row, dict) for row in value['writes']):
            raise BackendError('unexpected_g2g_writes', 502)
        for row in value['writes']:
            if row.get('detail'):
                row.update(detail=WITHHELD, detail_withheld=True)
    return _redact(value)
