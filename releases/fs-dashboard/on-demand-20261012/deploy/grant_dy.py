"""Prepare the single DY registry change; the existing publisher owns CAS/write."""
import copy
import re
import time


def grant_all(registry, now=None):
    result = copy.deepcopy(registry)
    clients = result['clients']
    matches = [c for c in clients if c.get('id') == 'dy-all-projects']
    if len(matches) != 1:
        raise ValueError('DY identity must be unique')
    dy = matches[0]
    if (dy.get('owner') != 'DY' or dy.get('enabled') is not True
            or dy.get('includeProfit') is not True
            or dy.get('expiresAtEpoch', 0) <= (time.time() if now is None else now)
            or not re.fullmatch(r'[a-f0-9]{64}', dy.get('tokenSha256', ''))):
        raise ValueError('DY identity/validity changed; do not restore old credentials')
    dy['projects'] = ['*']
    return result
