import copy
import hashlib
import json
from pathlib import Path
import unittest

from campaign_backend.catalog import (build_reference_mappings,quantity_tiers,read_reference_mapping,
    read_product_metadata,validate_purchase_mapping)
from campaign_backend.core import ContractError


def fixture():
    refs=[dict(reference_key='seasonal-fc-'+str(i),family='seasonal',game_key='fc',
        product_ref=dict(site_id='266',game_id='1327',goods_id='111'),expected_platform=dict(code='ps',attribute_id='21587'),
        expected_quantity=dict(value=str(value),source_unit='K'),server_id='7645',category_id='9623',
        source_artifact='app/seasonal/campaign-data.js',public_path='/Fc-27/Coins.html') for i,value in enumerate((100,300,1000))]
    seed=dict(schema_version=1,source_revision='fixture',source_artifacts={'app/seasonal/campaign-data.js':'a'*64},references=refs)
    spec=dict(more={k:dict(present=False) for k in ('saleprop','skuTableSet')})
    product=dict(product_ref=dict(site_id='266',game_id='1327',goods_id='111'),status='observed',
        goods=dict(identity=dict(id='111',site_id='266',gid='1327',mid='222',aid='21587',sid='7645',cid='9623'),
            purchase_fields=dict(min_qty=1,unit='K',num=1,sku_switch=1,attr_switch=1,status=1,buy_status=0,auto_off=0),
            specifications=spec,nested_purchase_fields={'gold':[100,300,1000]}),
        model=dict(identity=dict(id='222',gid='1327'),specifications=copy.deepcopy(spec),nested_purchase_fields={'gold':[100,300,1000]}))
    evidence=dict(schema_version=1,method='GET',products=[product],public_pages=[])
    return seed,evidence


class MappingTests(unittest.TestCase):
    def test_real_committed_artifact_covers_every_original_reference_and_distinguishes_gaps(self):
        artifact=json.loads((Path(__file__).parents[1]/'catalog-mapping.json').read_text(encoding='utf8'))
        all_rows=read_reference_mapping(artifact);rows=all_rows['mappings']
        self.assertEqual(len(rows),96);self.assertEqual(artifact['summary']['unique_goods_count'],86)
        self.assertEqual(artifact['summary']['metadata_observed'],96)
        self.assertEqual(artifact['summary']['empty_selectable_properties'],81)
        self.assertEqual(artifact['summary']['quantity_tier_references'],15)
        self.assertEqual(artifact['summary']['original_status_guard_failed'],6)
        self.assertEqual({m['game_key'] for m in rows.values()},{'fc','nba','madden','diablo','poe','aion'})
        for row in rows.values():
            self.assertIn('model_id',row['product_ref']);self.assertFalse(row['available']);self.assertFalse(row['checkout_enabled']);self.assertFalse(row['authoritative']);self.assertNotIn('sku_id',row['product_ref'])
            self.assertIn('PUBLIC_PURCHASE_SERIALIZATION_UNVERIFIED',row['missing_reasons'])
            self.assertEqual(row['public_purchase_evidence']['observation'],'unresolved')
        for key in ('seasonal-aion-1','seasonal-aion-2','seasonal-aion-3'):
            self.assertIn('QUANTITY_TIER_PRECEDENCE_UNVERIFIED',rows[key]['missing_reasons'])
        self.assertEqual(rows['seasonal-diablo-1']['quantity']['reference_value'],'100000')
        self.assertEqual(rows['seasonal-diablo-1']['quantity']['observed_unit'],'M')
        self.assertEqual(rows['seasonal-fc-1']['quantity']['reference_value'],'100')

    def test_quantity_tier_values_and_indices_are_mapped_without_inventing_sku_id(self):
        seed,evidence=fixture();artifact=build_reference_mappings(seed,evidence)
        row=read_reference_mapping(artifact,'seasonal-fc-1')
        self.assertEqual(row['quantity']['selected_tier'],dict(source_index=1,value='300',source_path='goods.more.gold[1]'))
        self.assertEqual(row['sku_options'],[]);self.assertEqual(row['selectable_attributes'],[])
        self.assertFalse(row['checkout_enabled']);self.assertEqual(row['quantity']['reference_value'],'300')
        self.assertEqual(row['quantity']['observed_num'],'1');self.assertIsNone(row['quantity']['maximum'])
        self.assertIsNone(row['quantity']['step'])

    def test_metadata_selection_validator_preserves_identity_quantity_and_capability_boundary(self):
        seed,evidence=fixture();row=build_reference_mappings(seed,evidence)['mappings']['seasonal-fc-0']
        selection=dict(product_ref=row['product_ref'],platform_attribute_id='21587',quantity='100')
        self.assertFalse(validate_purchase_mapping(row,selection)['checkout_enabled'])
        for changes,code in [({'quantity':'101'},'ORIGINAL_QUANTITY_CONFLICT'),({'sku_id':'invented'},'SELECTABLE_PROPERTY_MAPPING_REQUIRED'),
            ({'attributes':[{'attribute_id':'invented'}]},'SELECTABLE_PROPERTY_MAPPING_REQUIRED'),
            ({'platform_attribute_id':'999'},'PRODUCT_SCOPE_MISMATCH'),({'price':1},'PURCHASE_MAPPING_REQUIRED')]:
            with self.assertRaisesRegex(ContractError,code):validate_purchase_mapping(row,dict(selection,**changes))

    def test_aion_style_different_goods_model_tiers_remain_separate_not_silently_reconciled(self):
        seed,evidence=fixture();evidence['products'][0]['model']['nested_purchase_fields']['gold']=[300,2000]
        row=build_reference_mappings(seed,evidence)['mappings']['seasonal-fc-0']
        self.assertIn('QUANTITY_TIER_PRECEDENCE_UNVERIFIED',row['missing_reasons'])
        self.assertNotEqual(row['quantity_tiers'],row['model_quantity_tiers']);self.assertEqual(row['quantity']['selected_tier']['value'],'100')
        self.assertNotIn('original_quantity_in_current_model_tiers',row['verified_parts'])

    def test_scope_drift_duplicate_evidence_unknown_quantity_and_flag_types_fail(self):
        seed,evidence=fixture();bad=copy.deepcopy(evidence);bad['products'][0]['goods']['identity']['gid']='999'
        with self.assertRaisesRegex(ContractError,'CATALOG_SCOPE_MISMATCH'):build_reference_mappings(seed,bad)
        bad=copy.deepcopy(evidence);bad['products'].append(bad['products'][0])
        with self.assertRaisesRegex(ContractError,'CATALOG_EVIDENCE_DUPLICATE'):build_reference_mappings(seed,bad)
        bad=copy.deepcopy(evidence);bad['products'][0]['goods']['purchase_fields']['sku_switch']=True
        with self.assertRaisesRegex(ContractError,'PRODUCT_SWITCH_UNKNOWN'):build_reference_mappings(seed,bad)
        bad=copy.deepcopy(evidence);bad['products'][0]['goods']['identity']['aid']='999'
        with self.assertRaisesRegex(ContractError,'CATALOG_EVIDENCE_CHANGED'):build_reference_mappings(seed,evidence,bad)
        for values in ([True],[-1],[1,1],['1e3']):
            with self.assertRaises(ContractError):quantity_tiers(values,values)

    def test_nonempty_specs_retain_real_ids_and_safe_values_without_financial_raw_objects(self):
        goods=dict(id=1,mid=9,site_id=266,gid=1327,aid=21587,sid=7645,cid=9627,title='Observed product',
            min_qty=1,num=1,unit='',status=1,buy_status=0,sku_switch=1,attr_switch=1,
            more=dict(saleprop=[dict(attribute_id=11,values=[dict(value_id=22,label='Edition',price='SECRET_PRICE')])],
                      skuTableSet=[dict(sku_id=77,propvalues={'11':'22'},cost='SECRET_COST')]))
        model=dict(id=9,gid=1327,title='Observed model',more=dict(saleprop=[],skuTableSet=[]))
        result=read_product_metadata(model,goods,266,1327)
        self.assertEqual(result['specification_sources']['goods']['saleprop']['observed'][0]['values'][0]['value_id'],22)
        self.assertEqual(result['specification_sources']['goods']['skuTableSet']['observed'][0]['sku_id'],77)
        self.assertTrue(result['purchase_mapping_required']);self.assertNotIn('SECRET',json.dumps(result))

    def test_persisted_artifact_corruption_sensitive_addition_and_buy_activation_are_rejected(self):
        seed,evidence=fixture();artifact=build_reference_mappings(seed,evidence)
        artifact['mappings']['seasonal-fc-0']['available']=True
        with self.assertRaisesRegex(ContractError,'CATALOG_MAPPING_ARTIFACT_INVALID'):read_reference_mapping(artifact)
        artifact=build_reference_mappings(seed,evidence);artifact['mappings']['seasonal-fc-0']['credentials']={'token':'SECRET'}
        artifact['mappings_sha256']=hashlib.sha256(json.dumps(artifact['mappings'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        with self.assertRaisesRegex(ContractError,'CATALOG_MAPPING_ARTIFACT_INVALID'):read_reference_mapping(artifact)
        artifact=build_reference_mappings(seed,evidence)
        with self.assertRaisesRegex(ContractError,'CATALOG_REFERENCE_NOT_FOUND'):read_reference_mapping(artifact,'unknown')


if __name__=='__main__':unittest.main()
