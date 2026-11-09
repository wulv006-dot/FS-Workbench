"""FC model identity selection. Native prices/stock and purchase permissions never projected."""
import re
from urllib.parse import urlsplit
from .catalog import positive_id
from .core import ContractError

KINDS={'player':'9627','sbc':'10203','bundle':'10255'}
PLATFORMS={'ps':'21587','xbox':'21585','pc':'21589'}
# Explicit user-approved name alias; no automatic translation or fallback to all models.
ALIASES={'哈兰德':'Haaland'}
PRIVATE=re.compile(r'price|cost|profit|money|amount|token|password|secret|cookie|authorization|email|customer|member|order',re.I)


def label(value,maximum=240):
    if (not isinstance(value,str) or not value.strip() or len(value)>maximum
            or re.search(r'[\x00-\x1f@]|https?://|phx_',value) or PRIVATE.search(value)):
        return None
    return value


def request_scope(request,resolve=False):
    allowed={'action','site_id','game_id','kind','model_id'} | (set() if resolve else {'keyword','page','page_size'})
    if set(request)-allowed:raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
    if positive_id(request.get('site_id'))!='266' or positive_id(request.get('game_id'))!='1327':
        raise ContractError('MODEL_PROJECT_SCOPE_REQUIRED')
    kind=request.get('kind')
    if not isinstance(kind,str) or kind not in KINDS:raise ContractError('MODEL_KIND_REQUIRED')
    if resolve:
        return dict(kind=kind,category_id=KINDS[kind],model_id=positive_id(request.get('model_id')))
    query=[key for key in ('keyword','model_id') if key in request]
    if len(query)!=1:raise ContractError('MODEL_QUERY_REQUIRED')
    page,size=request.get('page',1),request.get('page_size',10)
    if type(page) is not int or not 1<=page<=500 or type(size) is not int or not 1<=size<=20:
        raise ContractError('INVALID_CATALOG_PAGE')
    result=dict(kind=kind,category_id=KINDS[kind],page=page,page_size=size)
    if query[0]=='model_id':
        if page!=1:raise ContractError('EXACT_MODEL_PAGE_REQUIRED')
        result['model_id']=positive_id(request['model_id'])
    else:
        original=request['keyword']
        if not isinstance(original,str) or not 2<=len(original.strip())<=80 or any(ord(c)<32 for c in original):
            raise ContractError('INVALID_CATALOG_KEYWORD')
        original=original.strip();keyword=ALIASES.get(original,original)
        if re.search(r'[\u3400-\u9fff]',keyword):raise ContractError('MODEL_ALIAS_REQUIRED')
        result.update(keyword=keyword,name_query=dict(input=original,resolved=keyword,alias_applied=keyword!=original,
            source='explicit_alias' if keyword!=original else 'native_title'))
    return result


def version_label(row,kind):
    if kind!='player':return None
    more=row.get('more');base=more.get('baseprop') if isinstance(more,dict) else None
    if not isinstance(base,list):return None
    props=[p for p in base if isinstance(p,dict) and str(p.get('id'))=='347' and p.get('name')=='Version']
    if len(props)!=1:return None
    prop=props[0];default=prop.get('default');choices=prop.get('pvs')
    if not isinstance(default,dict) or not isinstance(choices,list):return None
    try:chosen=positive_id(default.get('checked_item'))
    except ContractError:return None
    matches=[p for p in choices if isinstance(p,dict) and str(p.get('id'))==chosen and str(p.get('prop_id'))=='347']
    if len(matches)!=1 or type(matches[0].get('status')) not in (int,str) or matches[0]['status'] not in (1,'1'):return None
    return label(matches[0].get('name'))


def player_type(row):
    """Observed Admin PlayersType selection; missing facts never mean normal."""
    more=row.get('more');base=more.get('baseprop') if isinstance(more,dict) else None
    # Index uses the compact persisted property identity; edit expands choices.
    if isinstance(base,dict):
        selection=base.get('393')
        return {'8067':'normal','8115':'Signature'}.get(str(selection.get('a'))) if isinstance(selection,dict) else None
    if not isinstance(base,list):return None
    props=[p for p in base if isinstance(p,dict) and str(p.get('id'))=='393' and p.get('name')=='PlayersType']
    if len(props)!=1:return None
    prop=props[0];default=prop.get('default');choices=prop.get('pvs')
    if not isinstance(default,dict) or not isinstance(choices,list):return None
    chosen=str(default.get('checked_item'))
    names={'8067':'normal','8115':'Signature'}
    matches=[p for p in choices if isinstance(p,dict) and str(p.get('id'))==chosen]
    if chosen not in names or len(matches)!=1:return None
    value=matches[0]
    if str(value.get('prop_id'))!='393' or value.get('name')!=names[chosen] or value.get('status') not in (1,'1') or value.get('checked') is not True:return None
    if any(p.get('checked') is True and str(p.get('id'))!=chosen for p in choices if isinstance(p,dict)):return None
    return names[chosen]


def model_image(row,kind):
    formatted=row.get('_format')
    image=formatted.get('icon_format') if isinstance(formatted,dict) else None
    if isinstance(image,str) and image:
        parsed=urlsplit(image)
        if (parsed.scheme=='https' and parsed.netloc in ('b2c-static.p2pah.cn','assets.mmoexp.com')
                and not parsed.query and not parsed.fragment and '..' not in parsed.path.split('/')
                and re.fullmatch(r'/[A-Za-z0-9_./-]+\.(?:png|jpe?g|webp)',parsed.path,re.I)):
            return image,'admin_model_uploaded_asset'
    if kind=='player':
        more=row.get('more');extend=more.get('extend') if isinstance(more,dict) else None
        ids=[str(x.get('value')) for x in extend if isinstance(x,dict) and x.get('key')=='player_id'] if isinstance(extend,list) else []
        if len(ids)==1 and re.fullmatch(r'[1-9]\d{0,19}',ids[0]):
            return 'https://assets.mmoexp.com/player/fc27/'+ids[0]+'.png','storefront_player_id_asset'
    return None,None


def project_model(row,kind):
    if not isinstance(kind,str) or kind not in KINDS:raise ContractError('MODEL_KIND_REQUIRED')
    if (not isinstance(row,dict) or positive_id(row.get('gid'))!='1327' or positive_id(row.get('cid'))!=KINDS[kind]):
        raise ContractError('MODEL_SCOPE_MISMATCH')
    model_id=positive_id(row.get('id'))
    image,provenance=model_image(row,kind)
    return dict(key='model-266-1327-'+model_id,site_id='266',game_id='1327',model_id=model_id,kind=kind,
        title=label(row.get('title')),version_label=version_label(row,kind),image_url=image,image_provenance=provenance,
        platforms={p:dict(state='unknown',product_ref=None,observed_quantity=None) for p in PLATFORMS},
        verification_scope='catalog_identity_only',site_association='not_yet_verified',available=False,
        authoritative=False,checkout_enabled=False)


def historical_image(model_id,mapping,catalog):
    """Exact accepted model-ID/artifact association, never name/version matching."""
    rows=mapping.get('mappings',{}).values();images=set()
    for row in rows:
        ref=row.get('product_ref',{})
        if row.get('family')!='fc' or ref.get('site_id')!='266' or ref.get('game_id')!='1327' or ref.get('model_id')!=model_id:continue
        for product in catalog.get('products',{}).values():
            if any(str(offer.get('id'))==ref.get('goods_id') and str(offer.get('aid'))==row.get('platform',{}).get('attribute_id') for offer in product.get('platforms',{}).values()):
                image=product.get('imageSource')
                if not isinstance(image,str):continue
                parsed=urlsplit(image)
                if (parsed.scheme=='https' and parsed.netloc=='assets.mmoexp.com' and not parsed.query and not parsed.fragment
                        and re.fullmatch(r'/player/fc27/[A-Za-z0-9_./-]+\.(?:png|jpe?g|webp)',parsed.path)
                        and '..' not in parsed.path.split('/')):images.add(image)
    return next(iter(images)) if len(images)==1 else None


def observed_quantity(row):
    def number(key):
        try:return positive_id(row.get(key))
        except ContractError:return None
    unit=row.get('unit')
    if not isinstance(unit,str) or len(unit)>64 or re.search(r'[\x00-\x1f@]|https?://',unit) or PRIVATE.search(unit):unit=None
    result=dict(minimum=number('min_qty'),unit=unit,group=number('num'))
    return None if all(value is None for value in result.values()) else result


def resolve_model(row,kind,page):
    model=project_model(row,kind);rows=page['rows']
    complete=page['total']==len(rows)
    if complete and not rows:raise ContractError('MODEL_SITE_ASSOCIATION_MISSING')
    for goods in rows:
        if (positive_id(goods.get('site_id'))!='266' or positive_id(goods.get('gid'))!='1327'
                or positive_id(goods.get('cid'))!=KINDS[kind] or positive_id(goods.get('mid'))!=model['model_id']):
            raise ContractError('MODEL_GOODS_SCOPE_MISMATCH')
    for platform,aid in PLATFORMS.items():
        matches=[goods for goods in rows if str(goods.get('aid'))==aid]
        slot=model['platforms'][platform]
        if not complete:continue
        if not matches:slot['state']='missing';continue
        if len(matches)>1:slot['state']='ambiguous';continue
        goods=matches[0];status,off=goods.get('status'),goods.get('auto_off')
        if any(type(v) not in (int,str) or v not in (0,1,'0','1') for v in (status,off)):continue
        slot['observed_quantity']=observed_quantity(goods)
        model_status,model_off=row.get('status'),row.get('auto_off')
        if (str(status)=='0' or str(off)=='1' or type(model_status) in (int,str) and model_status in (0,'0')
                or type(model_off) in (int,str) and model_off in (1,'1')):
            slot['state']='offline';continue
        if (type(model_status) not in (int,str) or model_status not in (1,'1')
                or type(model_off) not in (int,str) or model_off not in (0,'0')):
            continue
        slot.update(state='verified',product_ref=dict(site_id='266',game_id='1327',model_id=model['model_id'],goods_id=positive_id(goods.get('id'))))
    model['site_association']='observed' if rows else 'not_observed'
    return model
