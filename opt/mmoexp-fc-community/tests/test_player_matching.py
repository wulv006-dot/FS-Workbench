import copy
import json
from pathlib import Path
import unittest
from player_matching import resolve, PublicSource

FIXTURE = json.loads((Path(__file__).parent/'fixtures/easysbc-public-lukaku.json').read_text(encoding='utf-8'))
CARD = {'model_id': 45490779, 'title': 'Romelu Lukaku/87/ST++/UCL RTTK'}

class Source:
    def __init__(self):
        self.data = copy.deepcopy(FIXTURE)
        self.complete = True
    def base_data(self): return self.data['base']
    def search(self, name): return {'items': self.data['search'], 'complete': self.complete}
    def detail(self, rid, role): return self.data['detail']

class MatchingTests(unittest.TestCase):
    def test_live_fixture_normal_card_matches_without_futbin_id(self):
        result = resolve(dict(CARD, futbin_player_id='999999'), source=Source())
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['mapping']['easysbc_id'], '50524153')
        self.assertEqual(result['mapping']['easysbc_role_id'], '44')
        self.assertEqual(len(result['candidates']), 2)

    def test_signature_not_inferred_from_foil_and_unknown_version_not_guessed(self):
        result = resolve(dict(CARD, title=CARD['title']+'/Signature'), source=Source())
        self.assertEqual(result['status'], 'ambiguous')
        self.assertNotIn('mapping', result)
        result = resolve(dict(CARD, card_version='Future Stars'), source=Source())
        self.assertEqual(result['status'], 'ambiguous')

    def test_saved_canonical_url_identity_is_rechecked(self):
        mapping = {'model_id':45490779,'easysbc_id':'50524153','easysbc_role_id':'44',
                   'easysbc_url':'https://www.easysbc.io/players/romelu-lukaku/uefa-champions-league-rttk/50524153?player-role-id=44'}
        self.assertEqual(resolve(CARD, mapping, source=Source())['status'], 'matched')
        source=Source();source.data['detail']['rating']=88
        self.assertNotEqual(resolve(CARD,mapping,source=source)['status'],'matched')

    def test_duplicate_non_cosmetic_or_missing_variant_requires_confirmation(self):
        source=Source();source.data['search'][1].pop('foil')
        self.assertEqual(resolve(CARD,source=source)['status'],'ambiguous')
        source=Source();source.data['search']=source.data['search'][:1]
        self.assertEqual(resolve(CARD,source=source)['reason'],'incomplete_card_variants')
        source=Source();source.complete=False
        self.assertEqual(resolve(CARD,source=source)['reason'],'incomplete_search')

    def test_wrong_season_unknown_person_and_source_failure_never_match(self):
        self.assertEqual(resolve(dict(CARD,season=26),source=Source())['status'],'unavailable')
        self.assertEqual(resolve(dict(CARD,name='Different Person'),source=Source())['status'],'unavailable')
        source=Source();source.base_data=lambda: (_ for _ in ()).throw(RuntimeError('private transport error'))
        result=resolve(CARD,source=source)
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('private transport',json.dumps(result))

    def test_public_reader_uses_observed_read_only_search_shape(self):
        source=PublicSource();calls=[]
        def request(path,payload=None):
            calls.append((path,payload));return copy.deepcopy(FIXTURE['search'])
        source._request=request
        result=source.search('Romelu Lukaku')
        self.assertTrue(result['complete'])
        self.assertEqual(calls,[('/players/search',{'searchText':'Romelu Lukaku','page':1,'platform':'Playstation'})])
        with self.assertRaises(ValueError):source.detail('../admin','44')

    def test_name_alias_offers_candidates_but_only_reuses_explicit_confirmed_choice(self):
        source=Source()
        card={'model_id':123,'title':'Romelu Lukaku AdditionalSurname/87/ST/UCL RTTK'}
        result=resolve(card,source=source)
        self.assertEqual(result['status'],'ambiguous')
        self.assertEqual(len(result['candidates']),2)
        mapping={key:result['candidates'][0][key] for key in ('model_id','easysbc_id','easysbc_role_id','easysbc_url')}
        self.assertEqual(resolve(card,mapping,source=Source())['status'],'matched')
