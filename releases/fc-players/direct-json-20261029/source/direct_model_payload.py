"""Pure FC27 player-to-model mapping; no network, credentials or writes."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence


ATTRIBUTE_COLUMNS = {
    "Version": "Version", "PlayersType": None, "Position": "Position",
    "Rating": "Rating", "IS": "IS", "Playstyles+": "PlayStyle+",
    "WeakFoot": "WeakFoot", "Skills": "Skills", "Foot": "Foot",
    "AlternativePositions": "AlternativePositions", "Player_Height": "Player_Height",
    "Playstyles": "PlayStyle", "PAC": "PAC", "SHO": "SHO", "PAS": "PAS",
    "DRI": "DRI", "DEF": "DEF", "PHY": "PHY", "Nation": "Nation",
    "League": "League", "Club": "Club",
}
EXTEND_COLUMNS = {"player_id": "FUTBIN ID", "is_score": "IS", "ps_price": "PS", "pc_price": "PC"}


def resolve_players_types(rows: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
    """Resolve the user's same-name/version IS pairs from the full source export.

    A single card is normal: Signature upgrades follow the base card (2026-11-07 rule).
    Duplicate/missing IS in pairs or groups larger than two remain unknown.
    """
    groups: dict[tuple[str, str], list[tuple[str, Decimal | None]]] = {}
    result: dict[str, str | None] = {}
    for row in rows:
        fid = _text(row.get("FUTBIN ID"))
        if not fid.isdecimal() or int(fid) <= 0:
            raise ValueError("INVALID_PLAYER_ID")
        if fid in result:
            raise ValueError(f"DUPLICATE_PLAYER_ID:{fid}")
        result[fid] = None
        try:
            key = (_text(row.get("name")), _text(row.get("Version")))
            if not all(key):
                continue
        except ValueError:
            continue
        try:
            score = Decimal(_number(row.get("IS"), "IS"))
        except ValueError:
            score = None
        groups.setdefault(key, []).append((fid, score))
    for pairs in groups.values():
        if len(pairs) == 1:
            result[pairs[0][0]] = "normal"
            continue
        if len(pairs) != 2 or any(score is None for _, score in pairs) or pairs[0][1] == pairs[1][1]:
            continue
        low, high = sorted(pairs, key=lambda item: item[1])
        result[low[0]], result[high[0]] = "normal", "Signature"
    return result


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def missing_platforms(source_row: Mapping[str, Any]) -> list[str]:
    """Metadata for the frozen plan; never put these names in the upstream API body."""
    result = ["PlayStation", "Xbox"] if _missing(source_row.get("PS")) else []
    if _missing(source_row.get("PC")):
        result.append("PC")
    return result


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError("MISSING_OR_BOOLEAN_VALUE")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value: Any, field: str, *, positive: bool = False) -> str:
    try:
        number = Decimal(_text(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"INVALID_NUMBER:{field}") from None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError(f"INVALID_NUMBER:{field}")
    return format(number.normalize(), "f")


def _values(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    parts = value if isinstance(value, (list, tuple)) else re.split(r"[,;，；\n]", _text(value))
    result = [_text(part) for part in parts if _text(part)]
    if len(set(result)) != len(result):
        raise ValueError("DUPLICATE_ATTRIBUTE_VALUE")
    return result


def _row(form: Mapping[str, Any]) -> Mapping[str, Any]:
    if "data" in form:
        form = form["data"]
    return form.get("row", form)


def _selected(prop: Mapping[str, Any], value: Any) -> tuple[Any, Any]:
    """Return the native selection ID(s) and direct-input value, never another card's defaults."""
    kind = int(prop["input_type"])
    if kind == 4:
        raw = _number(value, prop["name"]) if int(prop["value_type"]) == 2 else _text(value)
        if not raw:
            raise ValueError(f"MISSING_ATTRIBUTE:{prop['name']}")
        matches = [pv for pv in prop.get("pvs", []) if _text(pv["name"]) == raw]
        if len(matches) > 1:
            raise ValueError(f"AMBIGUOUS_ATTRIBUTE:{prop['name']}")
        return matches[0]["id"] if matches else "0", raw
    if kind not in (2, 3):
        raise ValueError(f"UNSUPPORTED_ATTRIBUTE_TYPE:{prop['name']}")
    requested = _values(value) if kind == 3 else [_text(value)]
    if kind == 2 and not requested[0]:
        raise ValueError(f"MISSING_ATTRIBUTE:{prop['name']}")
    selected = []
    for item in requested:
        matches = [pv for pv in prop.get("pvs", []) if _text(pv["name"]) == item]
        if not matches and kind == 2:
            return "", item
        if len(matches) != 1:
            raise ValueError(f"UNRESOLVED_ATTRIBUTE:{prop['name']}:{item}")
        selected.append(matches[0]["id"])
    return selected if kind == 3 else selected[0], ""


def _untradeable(value: Any) -> str:
    # The 25-column workbook retains the source 可交易 yes/no wording.
    text = _text(value)
    if text in ("是", "否"):
        return "0" if text == "是" else "1"
    if text in ("0", "1"):
        return text
    raise ValueError("INVALID_TRADEABILITY")


def build_model_payload(
    source_row: Mapping[str, Any], add_form: Mapping[str, Any], *,
    icon: int, icon_url: str, tag_ids: Sequence[int], business_defaults: Mapping[str, Any],
) -> dict[str, Any]:
    """Map the frozen 25-column row using current property IDs and explicit business values.

    business_defaults must contain players_type, coefficient, discount and model_price.
    Missing single-select options use the native base='' / custom=source-value fields.
    Multi-select options must already exist. No independent property API is called.
    missing_price_policy='preserve_unknown' or 'fallback_9999' keeps market inputs blank.
    The caller freezes missing_platforms(source_row) and separately applies the authorized
    product fallback. A product's USD 9999 fallback is never a market-coin input here.
    """
    for field in ("players_type", "coefficient", "discount", "model_price"):
        if field not in business_defaults:
            raise ValueError(f"BUSINESS_VALUE_REQUIRED:{field}")
    missing_policy = business_defaults.get("missing_price_policy", "reject")
    if missing_policy not in ("reject", "preserve_unknown", "fallback_9999"):
        raise ValueError("INVALID_MISSING_PRICE_POLICY")
    if business_defaults["players_type"] not in ("normal", "Signature"):
        raise ValueError("PLAYERS_TYPE_UNKNOWN")
    if type(icon) is not int or icon < 0 or not isinstance(icon_url, str) or (
        (icon == 0 and icon_url != "") or (icon > 0 and not icon_url.startswith("https://"))
    ):
        raise ValueError("ATTACHMENT_REQUIRED")
    tags = list(tag_ids)
    if any(type(tag) is not int or tag <= 0 for tag in tags) or len(set(tags)) != len(tags):
        raise ValueError("INVALID_TAG_IDS")
    form_row = _row(add_form)
    props = form_row.get("more", {}).get("baseprop")
    if not isinstance(props, list) or len(props) != len(ATTRIBUTE_COLUMNS):
        raise ValueError("ATTRIBUTE_SCHEMA_CHANGED")
    names = [prop.get("name") for prop in props]
    if set(names) != set(ATTRIBUTE_COLUMNS) or len(set(names)) != len(names):
        raise ValueError("ATTRIBUTE_SCHEMA_CHANGED")
    ids = [prop.get("id") for prop in props]
    if any(type(item) is not int or item <= 0 for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("INVALID_ATTRIBUTE_IDS")
    player_id = _text(source_row.get("FUTBIN ID"))
    if not player_id.isdecimal() or int(player_id) <= 0:
        raise ValueError("INVALID_PLAYER_ID")
    properties = []
    for template in props:
        name = template["name"]
        column = ATTRIBUTE_COLUMNS[name]
        value = business_defaults["players_type"] if column is None else source_row.get(column)
        selected, direct = _selected(template, value)
        prop = deepcopy(dict(template))
        multiple = isinstance(selected, list)
        prop["default"] = {"checked_item": selected, "price": [0] * len(selected) if multiple else "0", "monodromy": direct}
        # The native form submits base/custom for selectors and monodromy for direct input.
        for key in ("base", "custom", "monodromy", "index", "price"):
            prop.pop(key, None)
        if int(prop["input_type"]) == 4:
            prop["monodromy"] = float(direct) if int(prop["value_type"]) == 2 else direct
            if isinstance(prop["monodromy"], float) and prop["monodromy"].is_integer():
                prop["monodromy"] = int(prop["monodromy"])
        else:
            prop["base"] = selected
            prop["custom"] = direct
        chosen = set(selected if multiple else [selected])
        for pv in prop.get("pvs", []):
            pv["checked"] = pv["id"] in chosen
        properties.append(prop)
    extend = {}
    for key, column in EXTEND_COLUMNS.items():
        value = source_row.get(column)
        if key in ("ps_price", "pc_price") and _missing(value) and missing_policy in ("preserve_unknown", "fallback_9999"):
            # Native text fields submit blank strings; JSON null fails the upstream add.
            extend[key] = ""
        else:
            extend[key] = _number(value, column, positive=key in ("player_id", "ps_price", "pc_price"))
    extend["player_id"] = player_id
    extend["untradeable"] = _untradeable(source_row.get("untradeable"))
    extend["coefficient"] = _number(business_defaults["coefficient"], "coefficient", positive=True)
    extend["discount"] = _number(business_defaults["discount"], "discount", positive=True)
    if Decimal(extend["discount"]) > 100:
        raise ValueError("INVALID_NUMBER:discount")
    title = "/".join(_text(source_row.get(key)) for key in ("name", "Rating", "Position", "Version"))
    if any(not _text(source_row.get(key)) for key in ("name", "Rating", "Position", "Version")):
        raise ValueError("MISSING_TITLE_FIELD")
    if business_defaults["players_type"] == "Signature":
        title += "/Signature"
    return {
        "gid": 1327, "cid": 9627, "top_cid": int(form_row["top_cid"]), "sid": int(form_row["sid"]), "aid": 0,
        "title": title, "icon": icon, "pic": "", "price": _number(business_defaults["model_price"], "model_price", positive=True),
        "discount": 100, "min_qty": 1, "sort": 1000, "status": "1", "is_put": "0", "auto_off": "0",
        "attr_switch": "1", "sku_switch": "0", "is_hot": "0", "is_rec": "0", "is_code": "0",
        "tid": tags, "duration": "0", "shelf_time": "0", "partner": "", "summary": "", "desc": "",
        "more": {"baseprop": properties, "saleprop": [], "skuTableSet": [],
                 "extend": [{"key": key, "value": value} for key, value in extend.items()]},
        "_format": {"icon_format": icon_url},
        "_extend": {"site_ids": [], "aids": [], "duration": "0"},
    }


def _equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_equivalent(a, b) for a, b in zip(actual, expected))
    if actual is None or isinstance(actual, bool) or isinstance(expected, bool):
        return actual == expected
    try:
        return Decimal(str(actual)) == Decimal(str(expected))
    except InvalidOperation:
        return str(actual) == str(expected)


def validate_model_readback(expected_payload: Mapping[str, Any], actual_row: Mapping[str, Any]) -> None:
    """Check the frozen player identity, attributes, image, labels and pricing inputs.

    Product creation/state and computed product prices have their own phase verification.
    """
    actual = _row(actual_row)
    for field in ("gid", "cid", "title", "icon", "attr_switch"):
        if not _equivalent(actual.get(field), expected_payload[field]):
            raise ValueError(f"MODEL_READBACK_MISMATCH:{field}")
    expected_more = expected_payload["more"]
    actual_more = actual.get("more")
    if not isinstance(actual_more, Mapping):
        raise ValueError("MODEL_READBACK_MISMATCH:more")
    props = actual_more.get("baseprop", [])
    if len(props) != len(expected_more["baseprop"]):
        raise ValueError("MODEL_READBACK_MISMATCH:baseprop")
    by_id = {str(prop.get("id")): prop for prop in props}
    if len(by_id) != len(props):
        raise ValueError("MODEL_READBACK_MISMATCH:duplicate_baseprop")
    for expected in expected_more["baseprop"]:
        prop = by_id.get(str(expected["id"]), {})
        if prop.get("name") != expected["name"]:
            raise ValueError(f"MODEL_READBACK_MISMATCH:{expected['name']}")
        default = prop.get("default", {})
        if int(expected["input_type"]) == 2 and expected.get("custom"):
            selected_id = default.get("checked_item")
            if selected_id in (None, "", 0, "0"):
                matches = default.get("monodromy") == expected["custom"]
            else:
                selected_pvs = [pv for pv in prop.get("pvs", []) if str(pv.get("id")) == str(selected_id)]
                matches = len(selected_pvs) == 1 and selected_pvs[0].get("name") == expected["custom"]
            if not matches:
                raise ValueError(f"MODEL_READBACK_MISMATCH:{expected['name']}:custom")
            continue
        # Direct-input IDs may be assigned by the server; the entered value is authoritative.
        field = "monodromy" if int(expected["input_type"]) == 4 else "checked_item"
        wanted, observed = expected["default"][field], default.get(field)
        if isinstance(wanted, list) and isinstance(observed, list):
            matches = len(wanted) == len(observed) and {str(item) for item in wanted} == {str(item) for item in observed}
        else:
            matches = _equivalent(observed, wanted)
        if not matches:
            raise ValueError(f"MODEL_READBACK_MISMATCH:{expected['name']}:{field}")
    entries = actual_more.get("extend", [])
    if not isinstance(entries, list) or any(not isinstance(entry, Mapping) or "key" not in entry or "value" not in entry for entry in entries):
        raise ValueError("MODEL_READBACK_MISMATCH:extend")
    values = {entry["key"]: entry["value"] for entry in entries}
    if len(values) != len(entries):
        raise ValueError("MODEL_READBACK_MISMATCH:duplicate_extend")
    for entry in expected_more["extend"]:
        actual_value = values.get(entry["key"])
        unknown_price = entry["key"] in ("ps_price", "pc_price") and _missing(entry["value"])
        matches = (entry["key"] in values and _missing(actual_value)) if unknown_price else _equivalent(actual_value, entry["value"])
        if not matches:
            raise ValueError(f"MODEL_READBACK_MISMATCH:{entry['key']}")
    tags = actual.get("tid", [])
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, (list, tuple)) or not {str(tag) for tag in expected_payload["tid"]}.issubset({str(tag) for tag in tags}):
        raise ValueError("MODEL_READBACK_MISMATCH:tid")
