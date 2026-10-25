"""Explicit model/goods field mapping and public-safe catalog projection."""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from urllib.parse import urlsplit

from .core import ContractError, Money, identity, source_identity, timestamp


_PRIVATE = re.compile(r'price|cost|profit|amount|money|token|password|secret|cookie|authorization|email|order|customer|member', re.I)
_SPEC_FIELDS = {'id','name','title','label','key','value','values','children','options','sku_id','skuid','skuId',
    'prop_id','property_id','attribute_id','value_id','pid','vid','ids','propids','attr','saleprop','skuTableSet',
    'skuData','spec','props','propvalues','status','stock','min_qty','max_qty','step','num','group','quantity',
    'unit','required','selected','disabled','checked','gold','items','sku','skus','specs','attributes','attrs',
    'sale_props','baseprop','extend','min','max','qty','quantity_group','type'}


def specification_projection(value, depth=0):
    """Bounded observed purchase fields, never raw Admin objects or financial leaves."""
    if depth > 7:
        return {'schema_status': 'depth_limit'}
    if isinstance(value, list):
        if len(value) > 200:
            return {'schema_status': 'entry_limit', 'entry_count': len(value)}
        return [specification_projection(v, depth + 1) for v in value]
    if isinstance(value, dict):
        out, unknown = {}, []
        for key, item in value.items():
            key = str(key)
            if _PRIVATE.search(key):
                continue
            if key in _SPEC_FIELDS or re.fullmatch(r'[0-9]+', key):
                out[key] = specification_projection(item, depth + 1)
            elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,48}', key):
                unknown.append(key)
        if unknown:
            out['_unmapped_fields'] = sorted(unknown)
        return out
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str) and len(value) <= 160 and not _PRIVATE.search(value) and not re.search(r'[\x00-\x1f$€£¥]|https?://|@|phx_', value):
        return value
    return None


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _decimal(value):
    if type(value) not in (str, int) or not re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,6})?', str(value)):
        raise ContractError('QUANTITY_FIELD_UNKNOWN')
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ContractError('QUANTITY_FIELD_UNKNOWN') from None


def quantity_tiers(goods_values, model_values):
    """Observed more.gold is an ordered quantity table, not a source of fabricated SKU IDs."""
    if not isinstance(goods_values, list) or not goods_values or len(goods_values) > 200:
        raise ContractError('QUANTITY_TIER_SCHEMA_UNKNOWN')
    values = [_decimal(v) for v in goods_values]
    if (any(v <= 0 for v in values) or len(set(values)) != len(values)
            or not isinstance(model_values, list) or values != [_decimal(v) for v in model_values]):
        raise ContractError('QUANTITY_TIER_MODEL_CONFLICT')
    return [dict(source_index=i, value=format(v, 'f')) for i, v in enumerate(values)]


def positive_id(value):
    if (type(value) not in (int, str) or not str(value).isascii()
            or not str(value).isdecimal() or len(str(value)) > 19 or int(value) < 1):
        raise ContractError('POSITIVE_ID_REQUIRED')
    return str(int(value))


def _switch(value):
    if type(value) not in (str, int) or value not in (0, 1, '0', '1'):
        raise ContractError('PRODUCT_SWITCH_UNKNOWN')
    return int(value)


def _reference_id(value):
    if type(value) in (int, str) and str(value) == '0':
        return '0'
    return positive_id(value)


def discover_product(row, site_id, game_id, allow_unknown=False):
    """Observed Admin metadata only: no currency, availability or checkout inference."""
    if not isinstance(row, dict):
        raise ContractError('INVALID_PRODUCT_ROW')
    site_id, game_id = positive_id(site_id), positive_id(game_id)
    if allow_unknown:
        if positive_id(row.get('site_id')) != site_id or positive_id(row.get('gid')) != game_id:
            raise ContractError('PRODUCT_SCOPE_MISMATCH')
        reasons = []
        def optional_id(key):
            try:return _reference_id(row.get(key))
            except ContractError:
                reasons.append(key.upper()+'_UNKNOWN');return None
        def optional_switch(key):
            try:return _switch(row.get(key))
            except ContractError:
                reasons.append(key.upper()+'_UNKNOWN');return None
        try:
            minimum = int(positive_id(row.get('min_qty')))
            if minimum > 9007199254740991:raise ContractError('QUANTITY_FIELD_UNKNOWN')
        except ContractError:
            minimum = None;reasons.append('MINIMUM_QUANTITY_UNKNOWN')
        try:positive_id(row.get('num'))
        except ContractError:reasons.append('QUANTITY_GROUP_UNKNOWN')
        def label(value, maximum, empty=False):
            if (not isinstance(value,str) or len(value)>maximum or (not empty and not value.strip())
                    or re.search(r'[\x00-\x1f]|https?://|@|phx_',value) or _PRIVATE.search(value)):
                return None
            return value
        title, unit = label(row.get('title'),240), label(row.get('unit'),64,True)
        if title is None:reasons.append('PRODUCT_TITLE_UNKNOWN')
        if unit is None:reasons.append('PRODUCT_UNIT_UNKNOWN')
        result = dict(product_ref=dict(site_id=site_id,game_id=game_id,goods_id=positive_id(row.get('id')),
            model_id=positive_id(row.get('mid'))),title=title,platform_attribute_id=optional_id('aid'),
            server_id=optional_id('sid'),category_id=optional_id('cid'),minimum_quantity=minimum,unit=unit,
            sku_switch=optional_switch('sku_switch'),attr_switch=optional_switch('attr_switch'),
            raw_status=row.get('status') if type(row.get('status')) in (int,str) and re.fullmatch(r'[0-9]{1,10}',str(row['status'])) else None,
            raw_buy_status=row.get('buy_status') if type(row.get('buy_status')) in (int,str) and re.fullmatch(r'[0-9]{1,10}',str(row['buy_status'])) else None,
            status_semantics='unknown',purchase_mapping_required=True,purchase_mapping_reasons=['PRODUCT_DETAIL_REQUIRED'],
            metadata_missing_reasons=reasons,available=False,authoritative=False,checkout_enabled=False)
        if result['raw_status'] is None:reasons.append('PRODUCT_STATUS_UNKNOWN')
        if result['raw_buy_status'] is None:reasons.append('PRODUCT_BUY_STATUS_UNKNOWN')
        return result
    try:
        if (positive_id(row['site_id']) != site_id or positive_id(row['gid']) != game_id):
            raise ContractError('PRODUCT_SCOPE_MISMATCH')
        ref = dict(site_id=site_id, game_id=game_id, model_id=positive_id(row['mid']),
                   goods_id=positive_id(row['id']))
        title = identity(row['title'])
        minimum = positive_id(row['min_qty'])
        unit = row['unit']
        if not isinstance(unit, str) or len(unit) > 64 or any(ord(c) < 32 for c in unit):
            raise ContractError('PRODUCT_UNIT_UNKNOWN')
        status, buy_status = row['status'], row['buy_status']
        if any(type(value) not in (str, int) for value in (status, buy_status)):
            raise ContractError('PRODUCT_STATUS_UNKNOWN')
        return dict(product_ref=ref, title=title, platform_attribute_id=_reference_id(row['aid']),
            server_id=_reference_id(row['sid']), category_id=_reference_id(row['cid']),
            minimum_quantity=int(minimum), unit=unit, sku_switch=_switch(row['sku_switch']),
            attr_switch=_switch(row['attr_switch']), raw_status=status, raw_buy_status=buy_status,
            status_semantics='unknown', purchase_mapping_required=True,
            purchase_mapping_reasons=['PRODUCT_DETAIL_REQUIRED'], authoritative=False, checkout_enabled=False)
    except KeyError:
        raise ContractError('PRODUCT_METADATA_MISSING') from None


def read_product_metadata(model, goods, site_id, game_id, allow_unknown=False):
    product = discover_product(goods, site_id, game_id, allow_unknown=allow_unknown)
    if (not isinstance(model, dict)
            or positive_id(model.get('id')) != product['product_ref']['model_id']):
        raise ContractError('MODEL_SCOPE_MISMATCH')
    if 'gid' in model and positive_id(model['gid']) != product['product_ref']['game_id']:
        raise ContractError('MODEL_SCOPE_MISMATCH')
    reasons = list(product.get('metadata_missing_reasons',[]))
    title = model.get('title')
    if allow_unknown and (not isinstance(title,str) or not title.strip() or len(title)>240
            or re.search(r'[\x00-\x1f]|https?://|@|phx_',title) or _PRIVATE.search(title)):
        product['model_title'] = None;reasons.append('MODEL_TITLE_UNKNOWN')
    else:product['model_title'] = identity(title)
    sale_properties_observed = False
    specifications = {}
    for source, row in (('goods', goods), ('model', model)):
        more = row.get('more')
        if not isinstance(more, dict):
            reasons.append(source.upper() + '_SPEC_SCHEMA_UNKNOWN')
            continue
        specifications[source] = {}
        for key in ('saleprop', 'skuTableSet'):
            if key not in more:
                specifications[source][key] = dict(present=False)
                continue
            value = more[key]
            if not isinstance(value, (list, dict)):
                specifications[source][key] = dict(present=True, schema_status='unknown')
                reasons.append(source.upper() + '_SPEC_SCHEMA_UNKNOWN')
                continue
            if key == 'saleprop':
                sale_properties_observed = True
            # Empty observed containers have no IDs to invent. Nonempty shapes await exact mapping.
            specifications[source][key] = dict(present=True, schema_status='empty' if not value else 'mapping_required',
                                                entry_count=len(value))
            if value:
                specifications[source][key]['observed'] = specification_projection(value)
                reasons.append(source.upper() + '_SPEC_MAPPING_REQUIRED')
    if product['sku_switch']:
        reasons.append('SKU_SELECTION_MAPPING_REQUIRED')
    if not sale_properties_observed:
        reasons.append('SALE_PROPERTY_PRESENCE_UNKNOWN')
    if product['platform_attribute_id'] in ('0', None):
        reasons.append('PLATFORM_ATTRIBUTE_MAPPING_REQUIRED')
    # attr_switch=1 alone does not imply selectable attributes; actual saleprop decides.
    if not product['sku_switch'] and not reasons:
        product['purchase_mapping_required'] = False
    product['purchase_mapping_reasons'] = sorted(set(reasons))
    product['specification_sources'] = specifications
    product['quantity_observation'] = dict(minimum=str(product['minimum_quantity']) if product['minimum_quantity'] is not None else None, raw_unit=product['unit'],
        raw_num=str(goods['num']) if type(goods.get('num')) in (str, int) and str(goods['num']).isdigit() else None,
        step=None, maximum=None, semantics='observed_fields_not_cart_serialization')
    product['nested_purchase_fields'] = {source: specification_projection(row.get('more'))
                                         for source, row in (('goods', goods), ('model', model))}
    product['selection_schema'] = 'unresolved'
    if product['sku_switch'] and isinstance(goods.get('more'), dict) and 'gold' in goods['more']:
        try:
            model_more = model.get('more') if isinstance(model.get('more'),dict) else {}
            product['quantity_tiers'] = quantity_tiers(goods['more']['gold'], goods['more']['gold'])
            product['model_quantity_tiers'] = quantity_tiers(model_more.get('gold'), model_more.get('gold'))
            if product['quantity_tiers'] != product['model_quantity_tiers']:
                product['purchase_mapping_reasons'].append('QUANTITY_TIER_PRECEDENCE_UNVERIFIED')
            product['selection_schema'] = 'admin_gold_quantity_tiers_v1'
        except ContractError as error:
            product['purchase_mapping_reasons'].append(str(error))
    else:
        product['selection_schema'] = 'empty_selectable_properties' if not product['purchase_mapping_required'] else 'unresolved'
    product['verification_scope'] = 'observed_admin_metadata_not_checkout_mapping'
    return product


def _evidence_index(evidence):
    if evidence.get('schema_version') != 1 or evidence.get('method') != 'GET':
        raise ContractError('CATALOG_EVIDENCE_INVALID')
    result = {}
    for product in evidence.get('products', []):
        ref = product.get('product_ref', {})
        key = tuple(positive_id(ref[k]) for k in ('site_id','game_id','goods_id'))
        if key in result:
            raise ContractError('CATALOG_EVIDENCE_DUPLICATE')
        result[key] = product
    return result


def _mapping_summary(mappings):
    return dict(reference_count=len(mappings),unique_goods_count=len({tuple(m['product_ref'][k] for k in ('site_id','game_id','goods_id')) for m in mappings.values()}),
        game_count=len({m['game_key'] for m in mappings.values()}),metadata_observed=sum(m['metadata_state']=='observed' for m in mappings.values()),
        empty_selectable_properties=sum(m['selection_schema']=='empty_selectable_properties' for m in mappings.values()),
        quantity_tier_references=sum(m['selection_schema']=='admin_gold_quantity_tiers_v1' for m in mappings.values()),
        original_status_guard_failed=sum(m.get('original_status_guard_passed') is False for m in mappings.values()),
        available=0,checkout_enabled=0)


def _fc_fixed_serialization(reference, value):
    """Original activity-core.payload fields only; no current main-site acceptance claim."""
    if reference['family'] != 'fc':
        return None
    quantity, group = positive_id(value), positive_id(reference['expected_quantity'].get('group'))
    if (reference['game_key'] != 'fc' or reference['source_artifact'] != 'app/catalog.json'
            or reference['product_ref']['site_id'] != '266' or reference['product_ref']['game_id'] != '1327'
            or quantity != value or str(reference['expected_quantity']['group']) != group
            or reference['expected_quantity'].get('source_unit') is not None
            or max(int(quantity),int(group)) > 9007199254740991):
        raise ContractError('FC_FIXED_SELECTION_CONTRACT_INVALID')
    return dict(contract='fc-activity-core-payload-v1',source_artifact='app/activity-core.js',
        verification_scope='original_source_only',current_main_site_verified=False,
        fields=dict(category='new_items',id=positive_id(reference['product_ref']['goods_id']),
            group=group,num=quantity,attr='',aid=positive_id(reference['expected_platform']['attribute_id'])))


def build_reference_mappings(seed, evidence, supplement=None):
    """Consume sanitized GET evidence, preserving reference quantities and honest unresolved parts."""
    if seed.get('schema_version') != 1 or not isinstance(seed.get('references'), list):
        raise ContractError('CATALOG_SEED_INVALID')
    index = _evidence_index(evidence)
    extra = _evidence_index(supplement) if supplement else {}
    evidence_hashes = {'catalog_get': _json_hash(evidence)}
    if supplement:
        evidence_hashes['currency_schema_get'] = _json_hash(supplement)
    mappings = {}
    for reference in seed['references']:
        key = identity(reference['reference_key'])
        if key in mappings:
            raise ContractError('CATALOG_REFERENCE_DUPLICATE')
        ref = {k:positive_id(reference['product_ref'][k]) for k in ('site_id','game_id','goods_id')}
        scope = tuple(ref[k] for k in ('site_id','game_id','goods_id'))
        observed = index.get(scope)
        if scope in extra:
            if (not observed or extra[scope].get('goods',{}).get('identity') != observed.get('goods',{}).get('identity')
                    or extra[scope].get('model',{}).get('identity') != observed.get('model',{}).get('identity')
                    or extra[scope].get('goods',{}).get('purchase_fields') != observed.get('goods',{}).get('purchase_fields')):
                raise ContractError('CATALOG_EVIDENCE_CHANGED')
            observed = extra[scope]
        expected = reference['expected_quantity']
        original_value = str(expected['value']); _decimal(original_value)
        entry = dict(reference_key=key, family=identity(reference['family']), game_key=identity(reference['game_key']),
            product_ref=ref, platform=dict(code=identity(reference['expected_platform']['code']),
                attribute_id=positive_id(reference['expected_platform']['attribute_id'])),
            quantity=dict(reference_value=original_value, reference_unit=expected.get('source_unit'),
                reference_group=expected.get('group'), step=None, maximum=None),
            verified_parts=[], missing_reasons=['PUBLIC_PURCHASE_SERIALIZATION_UNVERIFIED',
                'SALE_STATE_SEMANTICS_UNVERIFIED','QUANTITY_STEP_AND_UPPER_BOUND_UNVERIFIED'],
            selection_schema='unresolved', selectable_attributes=[], sku_options=[],
            metadata_state='unresolved', available=False, authoritative=False, checkout_enabled=False,
            source_evidence=dict(evidence_hashes, original_artifact=reference['source_artifact'],
                original_artifact_sha256=seed['source_artifacts'][reference['source_artifact']]))
        fixed = _fc_fixed_serialization(reference, original_value)
        if fixed:
            entry['original_cart_serialization'] = fixed
            entry['quantity'].update(selection_mode='fixed_original_choice',step_required=False,maximum_required=False)
            entry['missing_reasons'].remove('QUANTITY_STEP_AND_UPPER_BOUND_UNVERIFIED')
            entry['verified_parts'] += ['original_fc_fixed_selection','original_fc_cart_field_serialization']
        if not observed or observed.get('status') != 'observed':
            entry['missing_reasons'].append('CURRENT_PRODUCT_METADATA_UNRESOLVED')
            mappings[key] = entry; continue
        goods, model = observed.get('goods',{}), observed.get('model',{})
        ids, mid = goods.get('identity',{}), model.get('identity',{})
        if (positive_id(ids.get('id')) != ref['goods_id'] or positive_id(ids.get('site_id')) != ref['site_id']
                or positive_id(ids.get('gid')) != ref['game_id'] or positive_id(ids.get('mid')) != positive_id(mid.get('id'))
                or 'gid' in mid and positive_id(mid['gid']) != ref['game_id']):
            raise ContractError('CATALOG_SCOPE_MISMATCH')
        entry['product_ref']['model_id'] = positive_id(ids['mid'])
        entry['metadata_state'] = 'observed'
        entry['verified_parts'] += ['site_game_goods_identity','model_identity','minimum_quantity_observed','raw_unit_observed']
        actual_platform = _reference_id(ids.get('aid'))
        entry['observed_platform_attribute_id'] = actual_platform
        if actual_platform == entry['platform']['attribute_id']:
            entry['verified_parts'].append('platform_attribute_identity')
        else:
            entry['missing_reasons'].append('ORIGINAL_PLATFORM_IDENTITY_CONFLICT')
        for field_name, source_name in (('server_id','sid'),('category_id','cid')):
            actual = _reference_id(ids.get(source_name)); entry[field_name] = actual
            if field_name in reference:
                if actual != str(reference[field_name]):
                    entry['missing_reasons'].append('ORIGINAL_'+field_name.upper()+'_CONFLICT')
                else:
                    entry['verified_parts'].append(field_name+'_identity')
        fields = goods.get('purchase_fields',{})
        minimum = _decimal(fields.get('min_qty')); value = _decimal(original_value)
        if minimum<=0 or value<=0:raise ContractError('QUANTITY_FIELD_UNKNOWN')
        unit = fields.get('unit')
        if not isinstance(unit,str) or len(unit)>64 or any(ord(c)<32 for c in unit):
            raise ContractError('PRODUCT_UNIT_UNKNOWN')
        entry['quantity'].update(observed_minimum=format(minimum,'f'), observed_unit=unit,
            observed_num=str(fields['num']) if type(fields.get('num')) in (str,int) else None,
            meets_observed_minimum=value>=minimum,
            unit_matches=None if expected.get('source_unit') is None else expected['source_unit']==unit)
        if fixed:
            try:
                group_matches = positive_id(fields.get('num')) == fixed['fields']['group']
                entry['quantity']['original_group_matches_observed_num'] = group_matches
                if not group_matches:
                    entry['missing_reasons'].append('ORIGINAL_QUANTITY_GROUP_CONFLICT')
            except ContractError:
                entry['quantity']['original_group_matches_observed_num'] = None
                entry['missing_reasons'].append('ORIGINAL_QUANTITY_GROUP_UNVERIFIED')
        if value<minimum: entry['missing_reasons'].append('ORIGINAL_QUANTITY_BELOW_CURRENT_MINIMUM')
        if expected.get('source_unit') is not None and expected['source_unit']!=unit:
            entry['missing_reasons'].append('ORIGINAL_QUANTITY_UNIT_CONFLICT')
        entry['raw_status'] = {k:fields[k] for k in ('status','buy_status','auto_off','sku_switch','attr_switch') if type(fields.get(k)) in (str,int)}
        entry['original_status_guard_passed'] = type(fields.get('status')) is int and fields['status']==1 and fields.get('auto_off')==0
        if not entry['original_status_guard_passed']:
            entry['missing_reasons'].append('ORIGINAL_PAGE_STATUS_GUARD_FAILED')
        specs = {}
        for source, row in (('goods',goods),('model',model)):
            more = row.get('specifications',{}).get('more',{})
            specs[source] = {name:{'present':more.get(name,{}).get('present') is True,
                **({'observed':specification_projection(more[name].get('value'))} if more.get(name,{}).get('present') else {})}
                for name in ('saleprop','skuTableSet')}
        entry['specification_evidence'] = specs
        sku_switch = _switch(fields.get('sku_switch'))
        if sku_switch == 0 and all(specs[s]['saleprop'].get('observed') in ([],{}) and specs[s]['saleprop']['present']
                                   and specs[s]['skuTableSet'].get('observed') in ([],{}) and specs[s]['skuTableSet']['present'] for s in specs):
            entry['selection_schema'] = 'empty_selectable_properties'
            entry['verified_parts'].append('empty_selectable_properties_observed')
        elif sku_switch == 1:
            try:
                goods_values,model_values=goods.get('nested_purchase_fields',{}).get('gold'),model.get('nested_purchase_fields',{}).get('gold')
                tiers = quantity_tiers(goods_values,goods_values)
                model_tiers = quantity_tiers(model_values,model_values)
                entry['selection_schema'] = 'admin_gold_quantity_tiers_v1'
                entry['quantity_tiers'] = tiers
                entry['model_quantity_tiers'] = model_tiers
                if tiers != model_tiers:
                    entry['missing_reasons'].append('QUANTITY_TIER_PRECEDENCE_UNVERIFIED')
                match = next((t for t in tiers if _decimal(t['value'])==value),None)
                if match:
                    entry['quantity']['selected_tier'] = dict(match, source_path='goods.more.gold['+str(match['source_index'])+']')
                    entry['verified_parts'].append('original_quantity_in_current_goods_tiers')
                    if any(_decimal(t['value'])==value for t in model_tiers):
                        entry['verified_parts'].append('original_quantity_in_current_model_tiers')
                else:
                    entry['missing_reasons'].append('ORIGINAL_QUANTITY_TIER_NOT_OBSERVED')
                entry['missing_reasons'].append('QUANTITY_TIER_TO_CART_ENCODING_UNVERIFIED')
            except ContractError as error:
                entry['missing_reasons'].append(str(error))
        else:
            entry['missing_reasons'].append('SELECTABLE_PROPERTY_MAPPING_REQUIRED')
        # An absent public read is an evidence gap, not proof that the main site lacks the feature.
        page = next((p for p in evidence.get('public_pages',[]) if p.get('path')==reference['public_path']),None)
        entry['public_purchase_evidence'] = dict(path=reference['public_path'],
            observation='observed' if page and page.get('status')=='observed' else 'unresolved')
        if page and re.fullmatch(r'[a-f0-9]{64}',page.get('sha256','')):
            entry['public_purchase_evidence']['sha256'] = page['sha256']
        entry['verified_parts'] = sorted(set(entry['verified_parts']))
        entry['missing_reasons'] = sorted(set(entry['missing_reasons']))
        mappings[key] = entry
    return dict(schema_version=1,mapping_version='campaign-catalog-mapping-v1',summary=_mapping_summary(mappings),
        source_revision=seed.get('source_revision'),source_evidence=evidence_hashes,mappings=mappings,
        mappings_sha256=_json_hash(mappings),authoritative=False,checkout_enabled=False)


def read_reference_mapping(artifact, reference_key=None):
    """Server-configured persisted artifact only. Reject corruption; never accept caller file paths."""
    if (artifact.get('schema_version')!=1 or artifact.get('mapping_version')!='campaign-catalog-mapping-v1'
            or artifact.get('mappings_sha256')!=_json_hash(artifact.get('mappings'))):
        raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID')
    mappings = artifact['mappings']
    allowed = {'reference_key','family','game_key','product_ref','platform','quantity','verified_parts','missing_reasons',
        'selection_schema','selectable_attributes','sku_options','metadata_state','available','authoritative','checkout_enabled',
        'source_evidence','observed_platform_attribute_id','server_id','category_id','raw_status','original_status_guard_passed',
        'specification_evidence','quantity_tiers','model_quantity_tiers','public_purchase_evidence','original_cart_serialization'}
    def check_tree(value):
        if isinstance(value,dict):
            if any(_PRIVATE.search(str(k)) for k in value):
                raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID')
            for v in value.values():check_tree(v)
        elif isinstance(value,list):
            for v in value:check_tree(v)
        elif isinstance(value,str) and (re.search(r'[\x00-\x1f]|phx_|https?://|@',value) or _PRIVATE.search(value)):
            raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID')
    for key, row in mappings.items():
        if set(row)-allowed or row.get('reference_key')!=key or any(row.get(k) is not False for k in ('available','authoritative','checkout_enabled')):
            raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID')
        check_tree(row)
        if 'original_cart_serialization' in row:
            try:
                expected = _fc_fixed_serialization(dict(family=row['family'],game_key=row['game_key'],
                    source_artifact=row['source_evidence']['original_artifact'],product_ref=row['product_ref'],
                    expected_platform=row['platform'],expected_quantity=dict(value=row['quantity']['reference_value'],
                        group=row['quantity']['reference_group'],source_unit=row['quantity']['reference_unit'])),
                    row['quantity']['reference_value'])
                if (expected is None or _json_hash(row['original_cart_serialization']) != _json_hash(expected)
                        or row['quantity'].get('selection_mode') != 'fixed_original_choice'
                        or row['quantity'].get('step_required') is not False
                        or row['quantity'].get('maximum_required') is not False):
                    raise ContractError('FC_FIXED_SELECTION_CONTRACT_INVALID')
            except (KeyError, TypeError, ContractError):
                raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID') from None
    if artifact.get('summary')!=_mapping_summary(mappings):
        raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID')
    source_evidence=artifact.get('source_evidence',{})
    file_hashes=artifact.get('evidence_file_hashes',{})
    for hashes in (source_evidence,file_hashes):
        if set(hashes)-{'seed','catalog_get','currency_schema_get'} or any(not re.fullmatch(r'[a-f0-9]{64}',v) for v in hashes.values()):
            raise ContractError('CATALOG_MAPPING_ARTIFACT_INVALID')
    if reference_key is not None:
        identity(reference_key)
        if reference_key not in mappings:
            raise ContractError('CATALOG_REFERENCE_NOT_FOUND')
        return json.loads(json.dumps(mappings[reference_key]))
    return dict(schema_version=1,mapping_version=artifact['mapping_version'],summary=artifact['summary'],
        source_evidence=dict(source_evidence),evidence_file_hashes=dict(file_hashes),mappings=json.loads(json.dumps(mappings)),
        authoritative=False,checkout_enabled=False)


def validate_purchase_mapping(mapping, selection):
    """Validate a known metadata selection without granting purchase/quote/cart capability."""
    if (set(selection)-{'product_ref','platform_attribute_id','quantity','sku_id','attributes'}
            or mapping.get('metadata_state')!='observed' or mapping.get('selection_schema')=='unresolved'
            or mapping.get('original_status_guard_passed') is not True
            or mapping.get('quantity',{}).get('meets_observed_minimum') is not True
            or any('CONFLICT' in r for r in mapping.get('missing_reasons',[]))):
        raise ContractError('PURCHASE_MAPPING_REQUIRED')
    if (mapping.get('original_cart_serialization') is not None
            and mapping['quantity'].get('original_group_matches_observed_num') is not True):
        raise ContractError('PURCHASE_MAPPING_REQUIRED')
    if selection.get('product_ref')!=mapping['product_ref'] or str(selection.get('platform_attribute_id'))!=mapping['observed_platform_attribute_id']:
        raise ContractError('PRODUCT_SCOPE_MISMATCH')
    if selection.get('sku_id') or selection.get('attributes'):
        raise ContractError('SELECTABLE_PROPERTY_MAPPING_REQUIRED')
    value = _decimal(selection.get('quantity'))
    if value!=_decimal(mapping['quantity']['reference_value']):
        raise ContractError('ORIGINAL_QUANTITY_CONFLICT')
    if mapping['selection_schema']=='admin_gold_quantity_tiers_v1' and 'selected_tier' not in mapping['quantity']:
        raise ContractError('QUANTITY_TIER_MAPPING_REQUIRED')
    return dict(product_ref=dict(mapping['product_ref']),platform_attribute_id=mapping['observed_platform_attribute_id'],
        quantity=format(value,'f'),selection_schema=mapping['selection_schema'],
        available=False,authoritative=False,checkout_enabled=False)


def field(row, path):
    try:
        for part in path.split('.'):
            row = row[part]
        return row
    except (KeyError, TypeError, AttributeError):
        raise ContractError('SOURCE_FIELD_MISSING') from None


def mapped(value, enums):
    # Preserve type distinctions: True and 1 must not become the same payment enum.
    for raw, normalized in enums:
        if type(value) is type(raw) and value == raw:
            return normalized
    raise ContractError('SOURCE_ENUM_UNKNOWN')


@dataclass(frozen=True)
class CatalogMapping:
    verification_ref: str
    goods_fields: dict
    model_fields: dict
    sale_states: tuple
    currency_scales: dict
    currency_code: str = None


def project_product(model, goods, mapping, purchase):
    """purchase is an independently verified normalized buying descriptor, never guessed from title."""
    identity(mapping.verification_ref)
    g = lambda key: field(goods, mapping.goods_fields[key])
    m = lambda key: field(model, mapping.model_fields[key])
    try:
        ref = {key: source_identity(g(key)) for key in ('site_id', 'game_id', 'model_id', 'goods_id')}
        if ref['site_id'] == '0' or ref['model_id'] != source_identity(m('model_id')):
            raise ContractError('PRODUCT_SCOPE_MISMATCH')
        if 'sku_id' in mapping.goods_fields:
            ref['sku_id'] = source_identity(g('sku_id'))
        title = identity(m('title'))
        available = mapped(g('sale_state'), mapping.sale_states)
        if type(available) is not bool:
            raise ContractError('INVALID_SALE_MAPPING')
        currency = g('currency') if 'currency' in mapping.goods_fields else mapping.currency_code
        if mapping.currency_code is not None and mapping.currency_code != currency:
            raise ContractError('CURRENCY_MAPPING_CONFLICT')
        price = Money.parse(g('price'), currency, mapping.currency_scales)
        timestamp(purchase['captured_at'])
        identity(purchase['catalog_version'])
        identity(purchase['verification_ref'])
        platform = purchase['platform']
        platform = {key: identity(platform[key]) for key in ('code', 'attribute_id', 'label')}
        if source_identity(g('platform_attribute_id')) != platform['attribute_id']:
            raise ContractError('PLATFORM_SCOPE_MISMATCH')
        quantity = purchase['quantity']
        if (set(quantity) - {'unit', 'minimum', 'step', 'group'}
                or type(quantity['minimum']) is not int or quantity['minimum'] < 1
                or type(quantity['step']) is not int or quantity['step'] < 1):
            raise ContractError('INVALID_QUANTITY')
        identity(quantity['unit'])
        if 'group' in quantity:
            identity(quantity['group'])
        attributes = []
        seen = set()
        for attribute in purchase['attributes']:
            aid = identity(attribute['attribute_id'])
            if aid in seen:
                raise ContractError('DUPLICATE_ATTRIBUTE')
            seen.add(aid)
            values = [{key: identity(v[key]) for key in ('value_id', 'label')}
                      for v in attribute['values']]
            if not values or len({v['value_id'] for v in values}) != len(values):
                raise ContractError('INVALID_ATTRIBUTE_VALUES')
            if type(attribute['required']) is not bool:
                raise ContractError('INVALID_ATTRIBUTE')
            attributes.append(dict(attribute_id=aid, required=attribute['required'], values=values))
        urls = {}
        for key in ('image_url', 'product_url'):
            if purchase.get(key):
                parsed = urlsplit(purchase[key])
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                    raise ContractError('INVALID_PUBLIC_URL')
                urls[key] = purchase[key]
        return dict(product_ref=ref, title=title, platform=platform, quantity=dict(quantity),
                    attributes=attributes, price=asdict(price), availability={'available': available},
                    catalog_version=purchase['catalog_version'], captured_at=purchase['captured_at'],
                    authoritative=False, **urls)
    except (KeyError, TypeError, AttributeError):
        raise ContractError('CATALOG_MAPPING_REQUIRED') from None
