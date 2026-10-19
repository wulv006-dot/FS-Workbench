"""Bounded views of evidence already owned by this task; no new source access."""
from copy import deepcopy
import json
import re

LIMIT = 12000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def pointer_part(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def bounded(value, path='/data', offset=0):
    if type(offset) is not int or not 0 <= offset <= 200000:
        raise ValueError('evidence_offset')
    if isinstance(value, list):
        items = []
        for row in value[offset:offset + 20]:
            if len(encoded(items + [row]).encode()) > LIMIT:
                break
            items.append(deepcopy(row))
        if not items and offset < len(value):
            return dict(bounded(value[offset], path + '/' + str(offset)), parent_items=len(value))
        stop = offset + len(items)
        return {'path':path, 'items':items, 'offset':offset, 'total':len(value),
                'next_offset':stop if stop < len(value) else None}
    if offset and not isinstance(value, dict):
        raise ValueError('evidence_offset_requires_list')
    if len(encoded(value).encode()) <= LIMIT:
        return {'path':path, 'value':deepcopy(value), 'complete':True}
    if isinstance(value, dict):
        small = {}; index = []
        entries = list(value.items())
        for key, child in entries[offset:offset + 30]:
            entry = {'path':path + '/' + pointer_part(key), 'type':type(child).__name__}
            if isinstance(child, (dict, list, str)):
                entry['items'] = len(child)
            index.append(entry)
            if len(encoded(child).encode()) < 1200 and len(encoded(small).encode()) < 3500:
                small[key] = deepcopy(child)
        stop = offset + len(index)
        return {'path':path, 'overview':small, 'content_index':index,
                'next_offset':stop if stop < len(entries) else None,
                'complete':False, 'instruction':'Use fc.read_evidence with a listed path; full evidence remains archived. An omitted field is not missing source data.'}
    if isinstance(value, str):
        return {'path':path, 'characters':len(value), 'complete':False,
                'reason':'large_text_use_existing_report_history_sections'}
    raise ValueError('evidence_view')


def read_evidence(book, args):
    if set(args) - {'evidence_id','path','offset'} or 'evidence_id' not in args:
        raise ValueError('evidence_fields')
    ident = args['evidence_id']; path = args.get('path', '/data')
    if not isinstance(ident, str) or not re.fullmatch(r'ev_[a-f0-9]{24}', ident):
        raise ValueError('evidence_id')
    if ident not in book.evidence:
        raise PermissionError('evidence_not_in_this_task')
    if not isinstance(path, str) or len(path) > 800 or path != '/data' and not path.startswith('/data/'):
        raise ValueError('evidence_path')
    value = book.evidence[ident]['data']
    try:
        for part in path.split('/')[2:]:
            key = part.replace('~1','/').replace('~0','~')
            value = value[int(key)] if isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*',key) else value[key]
    except (KeyError,IndexError,TypeError,ValueError):
        raise ValueError('evidence_path') from None
    return {'evidence_id':ident, **bounded(value,path,args.get('offset',0)),
            'source_query':deepcopy(book.evidence[ident].get('query')), 'new_source_query':False}


def model_view(record):
    if len(encoded(record).encode()) <= 16000:
        return record
    view = bounded(record['data'])
    overview = view.get('overview', {})
    return {k:deepcopy(v) for k,v in record.items() if k != 'data'} | {
        'data':overview,
        'model_projection':view,
        'full_evidence_retained':True,
        'read_more':{'tool':'fc.read_evidence','evidence_id':record['evidence_id'],'path':'/data'}}
