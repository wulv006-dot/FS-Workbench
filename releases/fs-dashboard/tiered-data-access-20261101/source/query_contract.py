"""Strict query normalization shared by planning and future cache identities."""
import hashlib
import json
from date_policy import PolicyError, validate

REQUIRED = {'dataset_id','start','end_exclusive','timezone','site_id','game_id','grain','fields','mode','budget_profile','reason','policy_version'}
OPTIONAL = {'filters','source_preference','cursor','snapshot_id','snapshot_revision'}


def normalize(request, capability, dataset):
    if not isinstance(request, dict) or not REQUIRED <= set(request) or set(request)-REQUIRED-OPTIONAL:
        raise PolicyError('query_schema')
    for key in REQUIRED-{'fields'}:
        if not isinstance(request[key],str) or not request[key] or len(request[key])>1000:
            raise PolicyError('query_schema')
    if request['dataset_id']!=dataset['dataset_id'] or request['grain'] not in dataset['grains']:
        raise PolicyError('dataset_or_grain_not_supported')
    fields=request['fields']
    if not isinstance(fields,list) or not fields or any(not isinstance(x,str) or x not in dataset['fields'] for x in fields) or len(fields)!=len(set(fields)):
        raise PolicyError('fields_not_supported')
    if request.get('source_preference','auto') not in ('auto',dataset['source']):
        raise PolicyError('source_not_supported')
    for key in ('cursor','snapshot_id','snapshot_revision'):
        if request.get(key) is not None and (type(request[key]) is not str or not request[key] or len(request[key])>4096):
            raise PolicyError('query_schema')
    if request['budget_profile'] not in capability['budget_profiles']:
        raise PolicyError('budget_not_allowed')
    filters=request.get('filters',{})
    if not isinstance(filters,dict) or set(filters)-set(dataset.get('filters',{})):
        raise PolicyError('filters_not_supported')
    for key,value in filters.items():
        if type(value) is not str or value not in dataset['filters'][key]:
            raise PolicyError('filter_value_not_supported')
    mode=request['mode']
    if mode!='frozen' and any(request.get(key) is not None for key in ('snapshot_id','snapshot_revision')):
        raise PolicyError('snapshot_mode_mismatch')
    scope=dict(site_id=request['site_id'],game_id=request['game_id'])
    validate(capability,dict(request,scope=scope))
    normalized=dict(request,scope=scope,fields=sorted(fields),filters=dict(sorted(filters.items())),source_preference=request.get('source_preference','auto'))
    # Reasons explain use but do not change result identity. Permission and source
    # watermark are added by the host; this digest alone is never a cache key.
    canonical={key:value for key,value in normalized.items() if key not in ('reason','cursor')}
    encoded=json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    normalized['filter_hash']=hashlib.sha256(encoded.encode()).hexdigest()
    return normalized
