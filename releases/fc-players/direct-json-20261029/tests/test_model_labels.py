"""Real 23700 response regression: names come from catalog IDs, never list positions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve()
BASE = next(parent / 'fc27_players_cloud' for parent in HERE.parents
            if (parent / 'fc27_players_cloud/player_web/model_service.py').is_file())
sys.path.insert(0, str(BASE))
from player_web.model_service import query_models, refresh_models
from player_web.repository import Repository

FIXTURE = json.loads((HERE.parent / 'fixtures/tag-labels-23700.json').read_text(encoding='utf-8-sig'))


class Snapshot:
    def __init__(self, row=None, catalog=None):
        self.rows = [deepcopy(row or FIXTURE['cached_row'])]
        self.catalog = deepcopy(catalog or FIXTURE['tag_catalog'])

    def model_snapshot(self, snapshot_id, owner):
        return {'snapshot_id': snapshot_id, 'created_at': FIXTURE['captured_at'],
                'total': FIXTURE['snapshot_total'], 'read_count': FIXTURE['snapshot_total'],
                'tag_catalog': deepcopy(self.catalog)}

    def model_rows(self, snapshot_id, owner):
        return deepcopy(self.rows)


class ModelLabels(unittest.TestCase):
    def query(self, repo, criteria=None):
        return query_models(repo, 'wulv', FIXTURE['snapshot_id'], criteria or {'keyword': '23700'})

    def test_real_cached_response_labels_follow_ids_and_business_ids_stay_unchanged(self):
        repo = Snapshot()
        before = deepcopy(repo.rows)
        result = self.query(repo)
        self.assertEqual(result['filtered_total'], 1)
        row = result['items'][0]
        self.assertEqual(row['model_id'], 45274659)
        self.assertEqual(row['futbin_id'], '23700')
        self.assertEqual(row['tag_ids'], [int(value) for value in FIXTURE['admin_model']['tid']])
        self.assertEqual(row['tag_names'], ['Newest', 'TOTW'])
        self.assertEqual(repo.rows, before, 'reading old snapshots must not rewrite business or cached IDs')

    def test_old_composite_name_cannot_create_a_false_tag_filter_match(self):
        self.assertEqual(self.query(Snapshot(), {'tag_name': 'Newest,TOTW'})['filtered_total'], 0)
        for name in ('Newest', 'TOTW'):
            self.assertEqual(self.query(Snapshot(), {'tag_name': name})['filtered_total'], 1)

    def test_unknown_catalog_id_preserves_alignment_and_cannot_borrow_another_name(self):
        row = {**FIXTURE['cached_row'], 'tag_ids': [12307, 99999, 12411], 'tag_names': ['Wrong first', 'Wrong second']}
        result = self.query(Snapshot(row))['items'][0]
        self.assertEqual(result['tag_ids'], [12307, 99999, 12411])
        self.assertEqual(result['tag_names'], ['Newest', '', 'TOTW'])

    def test_equal_names_for_distinct_ids_are_not_deduplicated_out_of_position(self):
        result = self.query(Snapshot(catalog={'12307': 'Same name', '12411': 'Same name'}))['items'][0]
        self.assertEqual(result['tag_ids'], [12307, 12411])
        self.assertEqual(result['tag_names'], ['Same name', 'Same name'])

    def test_refresh_saves_canonical_catalog_names_without_any_business_post(self):
        fixture = FIXTURE
        class Backend:
            authenticated = True
            def list_models(self, **kwargs):
                return SimpleNamespace(total=1, rows=({**fixture['cached_row'], 'id': 45274659, 'gid': 1327, 'cid': 9627},))
            def list_tags(self, **kwargs):
                return tuple({'id': int(key), 'name': name} for key, name in fixture['tag_catalog'].items())
            def single_edit(self, *args, **kwargs):
                raise AssertionError('label presentation must never edit business tags')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = Repository(root / 'control.sqlite3'); repo.initialize()
            result = refresh_models(SimpleNamespace(data_root=root), repo, Backend(), 'wulv')
            saved = repo.model_rows(result['snapshot_id'], 'wulv')[0]
            self.assertEqual(saved['tag_ids'], [12307, 12411])
            self.assertEqual(saved['tag_names'], ['Newest', 'TOTW'])


if __name__ == '__main__':
    unittest.main()
