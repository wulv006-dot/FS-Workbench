import ast
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import prepare_candidate


class QueryReadTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.cfg = {"a": ("456", "alpha", ["1"]), "b": ("456", "beta", ["2"])}
        self.category = ({}, {"1", "2"}, 0)
        self.search = {}
        self.full = []
        self.env = {
            "keywords_of": lambda cfg: {k: v[1] for k, v in cfg.items()},
            "game_gid_of": lambda cfg, key: cfg[key][0],
            "ids_of": lambda cfg, key: cfg[key][2],
            "read_needed_by_cid": self.read_category,
            "read_all_pages": self.read_pages,
            "_search_kw": lambda keyword: keyword.split("'")[0],
            "KEYWORD_SEARCH_MAX": 40,
            "log": lambda message: None,
        }
        exec(Path(__file__).with_name("query_read.py").read_text(encoding="utf-8"), self.env)

    def read_category(self, session, gid, ids):
        self.calls.append(("category", gid, set(ids)))
        if isinstance(self.category, Exception):
            raise self.category
        return self.category

    def read_pages(self, session, gid, **kwargs):
        self.calls.append(("search" if kwargs.get("keyword") else "full", gid, kwargs))
        rows = self.search.get(kwargs.get("keyword"), []) if kwargs.get("keyword") else self.full
        if isinstance(rows, Exception):
            raise rows
        return rows, 1

    def run_read(self):
        return self.env["fetch_all_needed"](object(), self.cfg, list(self.cfg))

    def test_complete_category_skips_keyword_and_full(self):
        self.category = ({"1": {"id": "1"}, "2": {"id": "2"}}, set(), 1)
        self.assertEqual(set(self.run_read()), {"1", "2"})
        self.assertEqual([c[0] for c in self.calls], ["category"])

    def test_partial_category_searches_only_missing_key(self):
        self.category = ({"1": {"id": "1"}}, {"2"}, 1)
        self.search["beta"] = [{"id": "2"}]
        self.assertEqual(set(self.run_read()), {"1", "2"})
        self.assertEqual([c[0] for c in self.calls], ["category", "search"])
        self.assertEqual(self.calls[-1][2]["keyword"], "beta")

    def test_no_mapping_preserves_keyword_search(self):
        self.search = {"alpha": [{"id": "1"}], "beta": [{"id": "2"}]}
        self.assertEqual(set(self.run_read()), {"1", "2"})
        self.assertEqual([c[0] for c in self.calls], ["category", "search", "search"])

    def test_category_exception_preserves_fallback(self):
        self.category = TimeoutError()
        self.full = [{"id": "1"}, {"id": "2"}]
        self.assertEqual(set(self.run_read()), {"1", "2"})
        self.assertEqual(self.calls[-1][0], "full")

    def test_stale_mapped_ids_are_not_dropped(self):
        self.category = ({}, set(), 1)
        self.search = {"alpha": TimeoutError(), "beta": TimeoutError()}
        self.full = [{"id": "1"}, {"id": "2"}]
        self.assertEqual(set(self.run_read()), {"1", "2"})
        self.assertEqual(self.calls[-1][2]["need_ids"], {"1", "2"})
        self.assertIsNone(self.calls[-1][2]["max_pages"])

    def test_large_batch_keeps_full_fallback_without_keyword(self):
        self.env["KEYWORD_SEARCH_MAX"] = 1
        self.full = [{"id": "1"}, {"id": "2"}]
        self.assertEqual(set(self.run_read()), {"1", "2"})
        self.assertEqual([c[0] for c in self.calls], ["category", "full"])

    def test_failed_reads_do_not_invent_missing_rows(self):
        self.category = TimeoutError()
        self.search = {"alpha": TimeoutError(), "beta": TimeoutError()}
        self.full = TimeoutError()
        self.assertEqual(self.run_read(), {})

    def test_original_keyword_normalization_preserved(self):
        self.cfg = {"a": ("456", "Adept's", ["1"])}
        self.search = {"Adept": [{"id": "1"}]}
        self.assertEqual(set(self.run_read()), {"1"})
        self.assertEqual(self.calls[-1][2]["keyword"], "Adept")

    def test_only_read_calls_no_write_or_session_mutation(self):
        tree = ast.parse(Path(__file__).with_name("query_read.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"write_rows", "set_gold_cost", "clear_main_cache", "login", "before_write"})

    def test_generator_refuses_changed_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary, "baseline.py")
            output = Path(temporary, "candidate.py")
            baseline.write_bytes(b"def fetch_all_needed(s,cfg,keys): return {}\n")
            with self.assertRaisesRegex(ValueError, "baseline_sha"):
                prepare_candidate.prepare(baseline, output)
            self.assertFalse(output.exists())

    def test_generator_preserves_other_ast_and_source(self):
        fixture = b"VALUE = 'synthetic'\n\ndef fetch_all_needed(s,cfg,keys):\n    return {}\n\ndef before_write():\n    raise RuntimeError('preserved')\n"
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary, "baseline.py")
            output = Path(temporary, "candidate.py")
            baseline.write_bytes(fixture)
            with mock.patch.object(prepare_candidate, "BASELINE_SHA256", hashlib.sha256(fixture).hexdigest()):
                sha = prepare_candidate.prepare(baseline, output)
            candidate = output.read_bytes()
            self.assertEqual(sha, hashlib.sha256(candidate).hexdigest())
            self.assertTrue(candidate.startswith(b"VALUE = 'synthetic'\n\n"))
            self.assertTrue(candidate.endswith(b"def before_write():\n    raise RuntimeError('preserved')\n"))

    def test_generator_requires_exactly_one_entry(self):
        fixture = b"VALUE = 'synthetic'\n"
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary, "baseline.py")
            output = Path(temporary, "candidate.py")
            baseline.write_bytes(fixture)
            with mock.patch.object(prepare_candidate, "BASELINE_SHA256", hashlib.sha256(fixture).hexdigest()):
                with self.assertRaisesRegex(ValueError, "one_read_entry"):
                    prepare_candidate.prepare(baseline, output)


if __name__ == "__main__":
    unittest.main()
