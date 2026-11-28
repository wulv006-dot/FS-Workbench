from dataclasses import replace
import unittest

from shadow_verify import RowScope
from site_binding import AdminRow, BindingKey, bind


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.site = BindingKey(model_id=44, site_id=45, platform_id=11, game_id=19, category_id=71)
        self.template = replace(self.site, site_id=0)

    def test_explicit_real_and_template_scopes_are_distinct(self):
        self.assertEqual(bind(self.site, [AdminRow(self.site, 9)]).row, RowScope(45, 11, 9))
        self.assertEqual(bind(self.template, [AdminRow(self.template, 10)]).row, RowScope(0, 11, 10))

    def test_missing_explicit_config_and_no_match_never_fallback(self):
        self.assertEqual(bind(None, [AdminRow(self.template, 10)]).state, "not_configured")
        self.assertEqual(bind(self.site, []).state, "not_found")
        self.assertEqual(bind(self.site, [AdminRow(self.template, 10)]).state, "scope_mismatch")

    def test_bad_scope_never_selects_a_true_match_alongside_other_rows(self):
        for other in (self.template, replace(self.site, platform_id=12), replace(self.site, model_id=1),
                      replace(self.site, game_id=1), replace(self.site, category_id=99)):
            with self.subTest(other=other):
                result = bind(self.site, [AdminRow(self.site, 9), AdminRow(other, 10)])
                self.assertEqual(result.state, "scope_mismatch")
                self.assertIsNone(result.row)

    def test_multiple_candidates_even_duplicate_ids_are_ambiguous(self):
        for other in (9, 10):
            self.assertEqual(bind(self.site, [AdminRow(self.site, 9), AdminRow(self.site, other)]).state,
                             "ambiguous")

    def test_wildcard_and_boolean_are_not_site_identifiers(self):
        for invalid in ("all", None, True, -1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    replace(self.site, site_id=invalid)
