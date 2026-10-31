from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "source" / "direct_model_payload.py"
spec = importlib.util.spec_from_file_location("direct_model_payload", SOURCE)
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


def source_row():
    return {
        "name": "Current Player", "Version": "Team of the Week", "Club": "Current Club",
        "League": "Current League", "Nation": "Current Nation", "AlternativePositions": "ST,LW",
        "Position": "ST++", "untradeable": "是", "Rating": 92, "IS": 37500,
        "Player_Height": '182cm | 6\'0"', "Foot": "Right", "Skills": 5, "WeakFoot": 4,
        "PAC": 97, "SHO": 92, "PAS": 81, "DRI": 93, "DEF": 31, "PHY": 78,
        "PC": 150000, "PS": 200000, "PlayStyle": "Finesse Shot, Rapid", "PlayStyle+": "Quick Step",
        "FUTBIN ID": 23691,
    }


def form():
    row = source_row()
    props = []
    for index, (name, column) in enumerate(payload.ATTRIBUTE_COLUMNS.items()):
        kind = 3 if name in ("AlternativePositions", "Playstyles", "Playstyles+") else (
            4 if name in ("IS", "Skills", "WeakFoot", "Player_Height", "PAC", "SHO", "PAS", "DRI", "DEF", "PHY") else 2)
        value = "normal" if column is None else row[column]
        options = str(value).split(",") if kind == 3 else [str(value)]
        options = [item.strip() for item in options]
        pvs = [{"id": 70000 + index * 100 + i, "name": item, "checked": False} for i, item in enumerate(options)]
        pvs.append({"id": 70000 + index * 100 + 99, "name": "Another card", "checked": True})
        props.append({"id": 40000 + index, "name": name, "input_type": kind,
                      "value_type": 1 if name == "Player_Height" or kind != 4 else 2,
                      "pvs": pvs, "default": {"checked_item": pvs[-1]["id"], "monodromy": "WRONG CARD"}})
    return {"row": {"top_cid": 2, "sid": 0, "more": {"baseprop": props, "extend": [{"key": "unexpected", "value": "reference"}]}}}


DEFAULTS = {"players_type": "normal", "coefficient": "1.1", "discount": "90", "model_price": 9999}


def build(row=None, schema=None, **kwargs):
    return payload.build_model_payload(row or source_row(), schema or form(), icon=123456,
                                       icon_url="https://images.example.test/current.webp", tag_ids=[12307, 12411],
                                       business_defaults=kwargs.get("business_defaults", DEFAULTS))


def readback(expected):
    row = deepcopy(expected)
    row["id"] = 222
    row["is_put"] = 1
    row["price"] = "123.00000"
    row["tid"] = ["12307", "12411"]
    return row


class PayloadTests(unittest.TestCase):
    def test_fallback_9999_does_not_turn_missing_market_inputs_into_9999_coins(self):
        row = source_row()
        row["PS"] = None
        defaults = {**DEFAULTS, "missing_price_policy": "fallback_9999"}
        result = build(row, business_defaults=defaults)
        ext = {entry["key"]: entry["value"] for entry in result["more"]["extend"]}
        self.assertEqual(ext["ps_price"], "")
        self.assertEqual(ext["pc_price"], "150000")
        self.assertEqual(result["price"], "9999")
        self.assertEqual(payload.missing_platforms(row), ["PlayStation", "Xbox"])
        actual = readback(result)
        payload.validate_model_readback(result, actual)
        for entry in actual["more"]["extend"]:
            if entry["key"] == "ps_price":
                entry["value"] = "9999"
        with self.assertRaisesRegex(ValueError, "ps_price"):
            payload.validate_model_readback(result, actual)
        row["PC"] = ""
        result = build(row, business_defaults=defaults)
        self.assertEqual(next(e["value"] for e in result["more"]["extend"] if e["key"] == "pc_price"), "")
        row["PC"] = 0
        with self.assertRaisesRegex(ValueError, "INVALID_NUMBER:PC"):
            build(row, business_defaults=defaults)

    def test_missing_market_values_always_use_native_blank_strings(self):
        for policy in ("preserve_unknown", "fallback_9999"):
            for missing in (None, "", "   "):
                row = {**source_row(), "PS": missing, "PC": missing}
                result = build(row, business_defaults={**DEFAULTS, "missing_price_policy": policy})
                ext = {e["key"]: e["value"] for e in result["more"]["extend"]}
                self.assertEqual((ext["ps_price"], ext["pc_price"]), ("", ""))
                self.assertEqual(row["PC"], missing)
                payload.validate_model_readback(result, readback(result))

    def test_signature_and_normal_keep_their_own_ids_scores_and_prices(self):
        normal = source_row()
        signature = {**normal, "FUTBIN ID": 23692, "IS": 56250, "PS": 310000, "PC": 225000}
        types = payload.resolve_players_types([normal, signature])
        schema = form()
        player_type = next(p for p in schema["row"]["more"]["baseprop"] if p["name"] == "PlayersType")
        player_type["id"] = 393
        player_type["pvs"] = [{"id": 8067, "name": "normal"}, {"id": 8115, "name": "Signature"}]
        outputs = []
        for row in (normal, signature):
            result = build(row, schema, business_defaults={**DEFAULTS, "players_type": types[str(row["FUTBIN ID"])]})
            outputs.append(result)
            ext = {entry["key"]: entry["value"] for entry in result["more"]["extend"]}
            self.assertEqual(ext["player_id"], str(row["FUTBIN ID"]))
            self.assertEqual(ext["is_score"], str(row["IS"]))
            self.assertEqual(ext["ps_price"], str(row["PS"]))
            self.assertEqual(ext["pc_price"], str(row["PC"]))
            self.assertEqual(set(ext), {"player_id", "untradeable", "coefficient", "discount", "ps_price", "pc_price", "is_score"})
            self.assertEqual(result["price"], "9999")
            payload.validate_model_readback(result, readback(result))
        normal_prop = next(p for p in outputs[0]["more"]["baseprop"] if p["id"] == 393)
        signature_prop = next(p for p in outputs[1]["more"]["baseprop"] if p["id"] == 393)
        self.assertEqual(normal_prop["base"], 8067)
        self.assertEqual(signature_prop["base"], 8115)
        self.assertEqual(outputs[1]["title"], outputs[0]["title"] + "/Signature")
        changed = readback(outputs[1])
        wrong_prices = {e["key"]: e["value"] for e in outputs[0]["more"]["extend"]}
        for entry in changed["more"]["extend"]:
            if entry["key"] in ("ps_price", "pc_price"):
                entry["value"] = wrong_prices[entry["key"]]
        with self.assertRaisesRegex(ValueError, "ps_price"):
            payload.validate_model_readback(outputs[1], changed)

    def test_signature_pair_uses_is_within_exact_name_and_version(self):
        normal = source_row()
        signature = {**normal, "FUTBIN ID": 23692, "IS": 56250}
        self.assertEqual(payload.resolve_players_types([signature, normal]), {"23692": "Signature", "23691": "normal"})
        defaults = {**DEFAULTS, "players_type": payload.resolve_players_types([normal, signature])["23692"]}
        schema = form()
        prop = next(p for p in schema["row"]["more"]["baseprop"] if p["name"] == "PlayersType")
        prop["pvs"].append({"id": 9999, "name": "Signature", "checked": False})
        result = build(signature, schema, business_defaults=defaults)
        self.assertTrue(result["title"].endswith("/Signature"))
        selected = next(p for p in result["more"]["baseprop"] if p["name"] == "PlayersType")
        self.assertEqual(selected["base"], 9999)

    def test_signature_cannot_be_resolved_from_selected_singleton(self):
        self.assertEqual(payload.resolve_players_types([source_row()]), {"23691": None})
        with self.assertRaises(ValueError):
            build(business_defaults={**DEFAULTS, "players_type": None})

    def test_signature_does_not_compare_other_names_or_versions(self):
        row = source_row()
        other = {**row, "FUTBIN ID": 23692, "IS": 56250, "Version": "Other Version"}
        self.assertEqual(payload.resolve_players_types([row, other]), {"23691": None, "23692": None})
        other["Version"] = row["Version"]
        other["name"] = "Different Player"
        self.assertEqual(payload.resolve_players_types([row, other]), {"23691": None, "23692": None})

    def test_signature_equal_is_for_multiple_ids_stays_unknown(self):
        row = source_row()
        other = {**row, "FUTBIN ID": 23692}
        self.assertEqual(payload.resolve_players_types([row, other]), {"23691": None, "23692": None})

    def test_signature_more_than_two_cards_stays_unknown(self):
        row = source_row()
        for third_is in (56250, 70000):
            rows = [row, {**row, "FUTBIN ID": 23692, "IS": 56250}, {**row, "FUTBIN ID": 23693, "IS": third_is}]
            self.assertEqual(payload.resolve_players_types(rows), {"23691": None, "23692": None, "23693": None})

    def test_signature_missing_or_invalid_is_stays_unknown(self):
        row = source_row()
        for value in (None, "", -1, float("nan"), True):
            other = {**row, "FUTBIN ID": 23692, "IS": value}
            self.assertEqual(payload.resolve_players_types([row, other]), {"23691": None, "23692": None})

    def test_signature_duplicate_id_is_an_identity_error(self):
        row = source_row()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PLAYER_ID"):
            payload.resolve_players_types([row, {**row, "Version": "Other", "IS": 1}])

    def test_signature_numeric_score_representation_is_equivalent(self):
        row = source_row()
        other = {**row, "FUTBIN ID": 23692, "IS": "37500.000"}
        self.assertEqual(payload.resolve_players_types([row, other]), {"23691": None, "23692": None})

    def test_explicit_missing_price_policy_preserves_unknown_and_plan_metadata(self):
        row = source_row()
        row["PS"] = None
        row["PC"] = ""
        defaults = {**DEFAULTS, "missing_price_policy": "preserve_unknown"}
        result = build(row, business_defaults=defaults)
        ext = {e["key"]: e["value"] for e in result["more"]["extend"]}
        self.assertEqual(ext["ps_price"], "")
        self.assertEqual(ext["pc_price"], "")
        self.assertEqual(payload.missing_platforms(row), ["PlayStation", "Xbox", "PC"])
        self.assertNotIn("missing_platforms", result)
        actual = readback(result)
        for e in actual["more"]["extend"]:
            if e["key"] in ("ps_price", "pc_price"):
                e["value"] = ""
        payload.validate_model_readback(result, actual)
        actual["more"]["extend"][2]["value"] = "0"
        with self.assertRaisesRegex(ValueError, "ps_price"):
            payload.validate_model_readback(result, actual)

    def test_missing_policy_does_not_accept_zero_negative_or_nan(self):
        defaults = {**DEFAULTS, "missing_price_policy": "preserve_unknown"}
        row = source_row()
        for value in (0, -1, float("nan")):
            row["PC"] = value
            with self.assertRaisesRegex(ValueError, "INVALID_NUMBER:PC"):
                build(row, business_defaults=defaults)
        with self.assertRaisesRegex(ValueError, "INVALID_MISSING_PRICE_POLICY"):
            build(business_defaults={**DEFAULTS, "missing_price_policy": "fill_zero"})

    def test_add_stage_can_explicitly_leave_labels_to_original_tag_step(self):
        result = payload.build_model_payload(source_row(), form(), icon=0, icon_url="", tag_ids=[], business_defaults=DEFAULTS)
        self.assertEqual(result["tid"], [])

    def test_explicit_no_image_stage_is_supported(self):
        result = payload.build_model_payload(source_row(), form(), icon=0, icon_url="", tag_ids=[12307, 12411], business_defaults=DEFAULTS)
        self.assertEqual(result["icon"], 0)
        self.assertEqual(result["_format"]["icon_format"], "")
        payload.validate_model_readback(result, readback(result))

    def test_dynamic_property_ids_and_no_reference_card_values(self):
        schema = form()
        original = deepcopy(schema)
        result = build(schema=schema)
        self.assertEqual(schema, original)
        self.assertEqual(result["title"], "Current Player/92/ST++/Team of the Week")
        self.assertEqual(result["tid"], [12307, 12411])
        self.assertEqual(result["_extend"]["site_ids"], [])
        self.assertEqual(len(result["more"]["baseprop"]), 21)
        for index, prop in enumerate(result["more"]["baseprop"]):
            self.assertEqual(prop["id"], 40000 + index)
            self.assertFalse(prop["pvs"][-1]["checked"])
            self.assertNotEqual(prop["default"]["monodromy"], "WRONG CARD")
        self.assertEqual(result["more"]["baseprop"][0]["base"], 70000)
        self.assertNotIn("unexpected", {e["key"] for e in result["more"]["extend"]})

    def test_direct_values_and_platform_inputs(self):
        result = build()
        props = {p["name"]: p for p in result["more"]["baseprop"]}
        self.assertEqual(props["IS"]["monodromy"], 37500)
        self.assertEqual(props["AlternativePositions"]["base"], [70900, 70901])
        self.assertEqual(props["Player_Height"]["monodromy"], '182cm | 6\'0"')
        ext = {entry["key"]: entry["value"] for entry in result["more"]["extend"]}
        self.assertEqual(ext, {"player_id": "23691", "is_score": "37500", "ps_price": "200000", "pc_price": "150000",
                               "untradeable": "0", "coefficient": "1.1", "discount": "90"})

    def test_unknown_single_select_uses_exact_native_custom_fields(self):
        row = source_row()
        row["Club"] = "TSG Hoffenheim"
        result = build(row)
        prop = next(p for p in result["more"]["baseprop"] if p["name"] == "Club")
        self.assertEqual(prop["base"], "")
        self.assertEqual(prop["custom"], "TSG Hoffenheim")
        self.assertFalse(any(pv["checked"] for pv in prop["pvs"]))
        payload.validate_model_readback(result, readback(result))
        actual = readback(result)
        actual_prop = next(p for p in actual["more"]["baseprop"] if p["name"] == "Club")
        actual_prop["default"] = {"checked_item": 12345678, "monodromy": ""}
        actual_prop["pvs"].append({"id": 12345678, "name": "TSG Hoffenheim", "checked": True})
        payload.validate_model_readback(result, actual)
        actual_prop["pvs"][-1]["name"] = "TSG 1899 Hoffenheim"
        with self.assertRaisesRegex(ValueError, "Club:custom"):
            payload.validate_model_readback(result, actual)

    def test_unknown_multi_select_and_ambiguous_single_select_still_block(self):
        row = source_row()
        row["PlayStyle"] = "Unknown playstyle"
        with self.assertRaisesRegex(ValueError, "UNRESOLVED_ATTRIBUTE:Playstyles"):
            build(row)
        schema = form()
        club = next(p for p in schema["row"]["more"]["baseprop"] if p["name"] == "Club")
        club["pvs"].append({"id": 999999, "name": "Current Club"})
        with self.assertRaisesRegex(ValueError, "UNRESOLVED_ATTRIBUTE:Club"):
            build(schema=schema)

    def test_unknown_players_type_cannot_become_custom(self):
        with self.assertRaisesRegex(ValueError, "PLAYERS_TYPE_UNKNOWN"):
            build(business_defaults={**DEFAULTS, "players_type": "invented"})

    def test_missing_platform_price_is_never_zero_or_copied(self):
        row = source_row()
        for value in (None, "", 0, -1, float("nan")):
            row["PC"] = value
            with self.assertRaisesRegex(ValueError, "INVALID_NUMBER:PC"):
                build(row)

    def test_defaults_cannot_be_silently_inherited(self):
        for key in DEFAULTS:
            defaults = dict(DEFAULTS)
            defaults.pop(key)
            with self.assertRaisesRegex(ValueError, "BUSINESS_VALUE_REQUIRED:" + key):
                build(business_defaults=defaults)

    def test_blank_multiselect_means_no_selected_playstyle(self):
        row = source_row()
        row["PlayStyle+"] = None
        props = {p["name"]: p for p in build(row)["more"]["baseprop"]}
        self.assertEqual(props["Playstyles+"]["base"], [])
        self.assertFalse(any(p["checked"] for p in props["Playstyles+"]["pvs"]))

    def test_untradeable_retains_source_yes_no_meaning(self):
        row = source_row()
        row["untradeable"] = "否"
        ext = {e["key"]: e["value"] for e in build(row)["more"]["extend"]}
        self.assertEqual(ext["untradeable"], "1")

    def test_attribute_schema_and_duplicates_block(self):
        for mutate in (lambda p: p.pop(), lambda p: p.append(deepcopy(p[0])),
                       lambda p: p[0].update(id=p[1]["id"])):
            schema = form()
            mutate(schema["row"]["more"]["baseprop"])
            with self.assertRaises(ValueError):
                build(schema=schema)

    def test_full_model_readback_after_shelves(self):
        expected = build()
        actual = readback(expected)
        for prop in actual["more"]["baseprop"]:
            if prop["input_type"] == 4:
                prop["default"]["checked_item"] = 999999
            elif isinstance(prop["default"]["checked_item"], list):
                prop["default"]["checked_item"].reverse()
        payload.validate_model_readback(expected, {"data": {"row": actual}})

    def test_readback_does_not_accept_correct_count_wrong_player(self):
        expected = build()
        for field in ("icon", "title", "gid"):
            actual = readback(expected)
            actual[field] = "wrong"
            with self.assertRaisesRegex(ValueError, "MODEL_READBACK_MISMATCH:" + field):
                payload.validate_model_readback(expected, actual)
        actual = readback(expected)
        actual["more"]["baseprop"][0]["default"]["checked_item"] = 999
        with self.assertRaisesRegex(ValueError, "Version:checked_item"):
            payload.validate_model_readback(expected, actual)

    def test_readback_pricing_inputs_and_tags_required(self):
        expected = build()
        actual = readback(expected)
        actual["more"]["extend"][0]["value"] = "999"
        with self.assertRaisesRegex(ValueError, "player_id"):
            payload.validate_model_readback(expected, actual)
        actual = readback(expected)
        actual["tid"] = [12307]
        with self.assertRaisesRegex(ValueError, "tid"):
            payload.validate_model_readback(expected, actual)

    def test_readback_rejects_duplicate_extended_identity(self):
        expected = build()
        actual = readback(expected)
        actual["more"]["extend"].append(deepcopy(actual["more"]["extend"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_extend"):
            payload.validate_model_readback(expected, actual)


if __name__ == "__main__":
    unittest.main()
