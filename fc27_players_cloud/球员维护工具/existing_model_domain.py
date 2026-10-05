"""后台已有球员模型的筛选、选择和安全操作计划。

这个模块与新增球员导入流程分开，供 GUI 在非更新期管理后台现有模型。
模型列表只读加载；标签和推荐动作只把用户当前选择的模型 ID 交给已有的
``AdminAdapter``。下架目前只生成可审阅计划并明确阻断写入，因为本地证据尚未
核实模型扩展和实际产品 ``Goods`` 的写入/回读契约。

模块不记录 token、密码、验证码或请求响应原文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .admin_adapter import extract_futbin_id, extract_model_id
from .admin_client import SUPPORTED_CID, SUPPORTED_GID


class ExistingModelError(ValueError):
    """已有模型列表或选择状态无法安全解释。"""


class UnlistBlocked(ExistingModelError):
    """下架接口或证据尚未达到可安全写入的条件。"""


def selected_futbin_ids(rows: Sequence["ExistingModelRow"]) -> tuple[str, ...]:
    """从所选后台行读取明确 FUTBIN ID，验证后按原顺序去重。"""

    if not rows:
        raise ExistingModelError("请先选择至少一个后台模型")
    result: list[str] = []
    model_by_futbin: dict[str, int] = {}
    for row in rows:
        value = str(row.futbin_id or "").strip()
        if not value.isascii() or not value.isdigit() or int(value) < 1:
            raise ExistingModelError(f"模型 {row.model_id} 缺少可核实的 FUTBIN ID，无法导出")
        prior_model = model_by_futbin.get(value)
        if prior_model is not None and prior_model != row.model_id:
            raise ExistingModelError(
                f"FUTBIN ID {value} 同时映射到模型 {prior_model} 和模型 {row.model_id}，映射冲突，已阻断导出"
            )
        model_by_futbin[value] = row.model_id
        if value not in result:
            result.append(value)
    return tuple(result)


def format_futbin_id_export(rows: Sequence["ExistingModelRow"]) -> str:
    """返回 UTF-8 TXT 内容，每行一个去重后的 FUTBIN ID。"""

    return "\n".join(selected_futbin_ids(rows)) + "\n"


def widget_is_descendant(widget: Any, parent: Any) -> bool:
    """判断 Tk widget 是否属于指定容器，便于区分嵌套滚动区域。"""

    current = widget
    while current is not None:
        if current is parent:
            return True
        current = getattr(current, "master", None)
    return False


def _as_int(value: Any, label: str, *, allow_none: bool = True) -> Optional[int]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise ExistingModelError(f"{label} 缺少")
    if isinstance(value, bool):
        return int(value)
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        if allow_none:
            return None
        raise ExistingModelError(f"{label} 不是整数") from exc
    return parsed


def _binary(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if int(value) in (0, 1) else None
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on", "enabled", "enable"}:
        return 1
    if text in {"0", "false", "no", "off", "disabled", "disable"}:
        return 0
    return None


def _split_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return [value]


def _tag_ids(row: Mapping[str, Any]) -> tuple[int, ...]:
    """读取列表行明确提供的标签 ID；不从标签名称反推 ID。"""

    values: list[Any] = []
    for key in ("tid", "tag_ids", "tagIds"):
        if key in row:
            values.extend(_split_values(row.get(key)))
    # 某些列表响应只把标签放在 goodsTag 中；其中的 id 仍是明确字段。
    for value in _split_values(row.get("goodsTag", row.get("goods_tag"))):
        if isinstance(value, Mapping) and "id" in value:
            values.append(value.get("id"))
    result: list[int] = []
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("id", value.get("tag_id", value.get("tagId")))
        parsed = _as_int(value, "标签 ID")
        if parsed is not None and parsed > 0 and parsed not in result:
            result.append(parsed)
    return tuple(result)


def _tag_names(row: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[Any] = []
    for key in ("tag_names", "tagNames", "goodsTag", "goods_tag", "tags"):
        if key in row:
            values.extend(_split_values(row.get(key)))
    result: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("name", value.get("title"))
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _extend_entries(row: Mapping[str, Any]) -> Optional[list[Mapping[str, Any]]]:
    more = row.get("more")
    if not isinstance(more, Mapping) or not isinstance(more.get("extend"), list):
        return None
    entries = more["extend"]
    if not all(isinstance(item, Mapping) and "key" in item for item in entries):
        return None
    return [item for item in entries if isinstance(item, Mapping)]


@dataclass(frozen=True)
class ExistingModelRow:
    """用于选择表格的一行；``raw`` 只保留当前进程内的后台行。"""

    model_id: int
    futbin_id: str
    title: str
    is_rec: Optional[int]
    tag_ids: tuple[int, ...]
    tag_names: tuple[str, ...]
    status: Optional[int]
    auto_off: Optional[int]
    raw: Mapping[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "ExistingModelRow":
        if not isinstance(row, Mapping):
            raise ExistingModelError("模型列表含非对象行")
        model_id = extract_model_id(row)
        if model_id is None:
            raise ExistingModelError("模型列表含缺少明确模型 ID 的行")
        title = str(row.get("title") or "").strip()
        return cls(
            model_id=model_id,
            futbin_id=extract_futbin_id(row) or "",
            title=title,
            is_rec=_binary(row.get("is_rec", row.get("isRec"))),
            tag_ids=_tag_ids(row),
            tag_names=_tag_names(row),
            status=_binary(row.get("status")),
            auto_off=_binary(row.get("auto_off", row.get("autoOff"))),
            raw=row,
        )


def normalize_model_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[ExistingModelRow, ...]:
    result: list[ExistingModelRow] = []
    seen: set[int] = set()
    for row in rows:
        item = ExistingModelRow.from_mapping(row)
        if item.model_id in seen:
            raise ExistingModelError(f"模型列表含重复模型 ID：{item.model_id}")
        seen.add(item.model_id)
        result.append(item)
    return tuple(result)


def build_existing_action_preview(
    rows: Sequence[ExistingModelRow],
    action: str,
    *,
    tag_ids: Sequence[Any] = (),
) -> str:
    """生成日常模型动作的完整确认内容，不发起任何后台调用。"""

    action_labels = {
        "tags": "追加指定标签",
        "tags_remove": "移除指定标签",
        "remove_tags": "移除指定标签",
        "recommend_enable": "开启推荐",
        "recommend_disable": "关闭推荐",
    }
    label = action_labels.get(action, action)
    lines = [
        "本次后台模型操作预览",
        f"动作：{label}",
        f"模型数量：{len(rows)}",
    ]
    if action in {"tags", "tags_remove", "remove_tags"}:
        lines.append(f"标签 ID：{', '.join(str(item) for item in tag_ids)}")
    lines.append("")
    for index, row in enumerate(rows, start=1):
        title = row.title or "名称待核实"
        lines.append(f"[{index}/{len(rows)}] 模型 ID：{row.model_id}；名称：{title}")
        lines.append(f"    执行动作：{label}")
    lines.extend(("", "只有点击“确认执行”才会进入写入线程；取消或关闭此窗口不会写入。"))
    return "\n".join(lines)


def build_unlist_action_preview(plan: Any) -> str:
    """生成下架写入前的模型/产品明细预览，不发起任何后台调用。"""

    model_ids = tuple(int(item) for item in getattr(plan, "model_ids", ()) or ())
    models = getattr(plan, "models", {}) or {}
    products_by_model = getattr(plan, "products_by_model", {}) or {}
    steps = tuple(getattr(plan, "steps", ()) or ())
    lines = [
        "本次下架操作预览（只读预检结果）",
        f"模型数量：{len(model_ids)}",
        f"动作步骤：{'；'.join(str(item) for item in steps)}",
        "模型级：设置 untradeable=1、status=0、auto_off=1；产品级：库存 total=0；不修改产品 auto_off。",
        "",
    ]
    for model_index, model_id in enumerate(model_ids, start=1):
        model = models.get(model_id, models.get(str(model_id), {})) if isinstance(models, Mapping) else {}
        title = str(model.get("title") or "名称待核实") if isinstance(model, Mapping) else "名称待核实"
        lines.append(f"[{model_index}/{len(model_ids)}] 模型 ID：{model_id}；名称：{title}")
        lines.append("    执行动作：按上方四步下架，并将该模型全部关联产品库存 total 设为 0")
        rows = products_by_model.get(model_id, products_by_model.get(str(model_id), ())) if isinstance(products_by_model, Mapping) else ()
        rows = tuple(rows or ())
        lines.append(f"    关联产品数量：{len(rows)}")
        for product_index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                lines.append(f"    产品 {product_index}：行结构无效；预检：阻断")
                continue
            product_id = row.get("id", row.get("product_id", row.get("productId")))
            total = row.get("total", "缺失")
            auto_off = row.get("auto_off", row.get("autoOff", "缺失"))
            total_ok = _product_total_is_valid(total)
            auto_off_value = _binary(auto_off)
            if auto_off_value == 1:
                auto_result = "通过（auto_off=1）"
            elif auto_off_value == 0:
                auto_result = "阻断（auto_off=0）"
            else:
                auto_result = "阻断（auto_off待核实）"
            total_result = "通过" if total_ok else "阻断（total待核实）"
            lines.append(
                f"    产品 {product_index}：产品 ID：{product_id}；库存 total：{total}；"
                f"auto_off：{auto_off}；预检：库存 {total_result}；{auto_result}"
            )
    lines.extend(("", "只有点击“确认执行”才会进入写入线程；取消或关闭此窗口不会写入。"))
    return "\n".join(lines)


def _product_total_is_valid(value: Any) -> bool:
    try:
        total = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return False
    return total.is_finite() and total >= 0


@dataclass(frozen=True)
class ExistingModelFilter:
    """后台已有模型筛选条件；``None`` 表示该条件不筛选。"""

    is_rec: Optional[int] = None
    tag_id: Optional[int] = None
    tag_name: str = ""
    keyword: str = ""
    status: Optional[int] = None

    def normalized(self) -> "ExistingModelFilter":
        is_rec = _binary(self.is_rec)
        status = _binary(self.status)
        tag_id = _as_int(self.tag_id, "标签 ID")
        if tag_id is not None and tag_id < 1:
            raise ExistingModelError("标签 ID 必须大于 0")
        return ExistingModelFilter(
            is_rec=is_rec,
            tag_id=tag_id,
            tag_name=str(self.tag_name or "").strip(),
            keyword=str(self.keyword or "").strip(),
            status=status,
        )


def filter_model_rows(
    rows: Sequence[ExistingModelRow],
    criteria: ExistingModelFilter | None = None,
    *,
    tag_catalog: Mapping[int | str, str] | None = None,
) -> tuple[ExistingModelRow, ...]:
    """纯函数筛选模型；标签名称采用不区分大小写的包含匹配。"""

    value = (criteria or ExistingModelFilter()).normalized()
    keyword = value.keyword.casefold()
    tag_name = value.tag_name.casefold()
    result: list[ExistingModelRow] = []
    for row in rows:
        catalog_names = tuple(
            str(tag_catalog.get(tag_id, "")).strip()
            for tag_id in row.tag_ids
            if tag_catalog and str(tag_catalog.get(tag_id, "")).strip()
        )
        names = tuple(dict.fromkeys((*row.tag_names, *catalog_names)))
        if value.is_rec is not None and row.is_rec != value.is_rec:
            continue
        if value.status is not None and row.status != value.status:
            continue
        if value.tag_id is not None and value.tag_id not in row.tag_ids:
            continue
        if tag_name and not any(tag_name in item.casefold() for item in names):
            continue
        if keyword:
            haystack = " ".join((row.title, row.futbin_id, str(row.model_id))).casefold()
            if keyword not in haystack:
                continue
        result.append(row)
    return tuple(result)


class ExistingModelManager:
    """后台模型行、当前筛选和选择集合的无界面状态容器。"""

    def __init__(self, rows: Iterable[Mapping[str, Any]] = ()) -> None:
        self._rows: tuple[ExistingModelRow, ...] = ()
        self._selected: set[int] = set()
        self._filter = ExistingModelFilter()
        self._tag_catalog: dict[int, str] = {}
        self.replace_rows(rows)

    @property
    def rows(self) -> tuple[ExistingModelRow, ...]:
        return self._rows

    @property
    def filter(self) -> ExistingModelFilter:
        return self._filter

    @property
    def tag_catalog(self) -> Mapping[int, str]:
        return dict(self._tag_catalog)

    def set_tag_catalog(self, catalog: Mapping[int | str, Any] | None) -> Mapping[int, str]:
        normalized: dict[int, str] = {}
        for key, value in (catalog or {}).items():
            parsed = _as_int(key, "标签 ID")
            name = str(value or "").strip()
            if parsed is not None and parsed > 0 and name:
                normalized[parsed] = name
        self._tag_catalog = normalized
        return dict(self._tag_catalog)

    def replace_rows(self, rows: Iterable[Mapping[str, Any]]) -> tuple[ExistingModelRow, ...]:
        normalized = normalize_model_rows(rows)
        self._rows = normalized
        self._selected.intersection_update({item.model_id for item in normalized})
        return normalized

    def load(self, backend: Any) -> tuple[ExistingModelRow, ...]:
        loader = getattr(backend, "list_all_models", None)
        if not callable(loader):
            raise ExistingModelError("后台对象缺少 list_all_models，只接受已核验的全量读取适配器")
        return self.replace_rows(loader())

    def set_filter(self, criteria: ExistingModelFilter | None = None, **changes: Any) -> ExistingModelFilter:
        value = criteria or self._filter
        if changes:
            data = {
                "is_rec": value.is_rec,
                "tag_id": value.tag_id,
                "tag_name": value.tag_name,
                "keyword": value.keyword,
                "status": value.status,
            }
            data.update(changes)
            value = ExistingModelFilter(**data)
        self._filter = value.normalized()
        return self._filter

    def visible_rows(self) -> tuple[ExistingModelRow, ...]:
        return filter_model_rows(self._rows, self._filter, tag_catalog=self._tag_catalog)

    def tag_names_for(self, row: ExistingModelRow) -> tuple[str, ...]:
        mapped = tuple(self._tag_catalog[tag_id] for tag_id in row.tag_ids if tag_id in self._tag_catalog)
        return tuple(dict.fromkeys((*row.tag_names, *mapped)))

    def select(self, model_ids: Iterable[int], *, replace: bool = False) -> tuple[int, ...]:
        valid = {item.model_id for item in self._rows}
        requested: set[int] = set()
        for value in model_ids:
            parsed = _as_int(value, "模型 ID", allow_none=False)
            assert parsed is not None
            if parsed not in valid:
                raise ExistingModelError(f"选择的模型 ID 不在当前后台列表：{parsed}")
            requested.add(parsed)
        if replace:
            self._selected = requested
        else:
            self._selected.update(requested)
        return self.selected_model_ids()

    def deselect(self, model_ids: Iterable[int]) -> tuple[int, ...]:
        for value in model_ids:
            parsed = _as_int(value, "模型 ID", allow_none=False)
            if parsed is not None:
                self._selected.discard(parsed)
        return self.selected_model_ids()

    def toggle(self, model_id: int) -> tuple[int, ...]:
        parsed = _as_int(model_id, "模型 ID", allow_none=False)
        assert parsed is not None
        if parsed in self._selected:
            self._selected.remove(parsed)
        else:
            self.select([parsed])
        return self.selected_model_ids()

    def select_visible(self) -> tuple[int, ...]:
        return self.select((item.model_id for item in self.visible_rows()))

    def deselect_visible(self) -> tuple[int, ...]:
        return self.deselect((item.model_id for item in self.visible_rows()))

    def clear_selection(self) -> tuple[int, ...]:
        self._selected.clear()
        return ()

    def selected_model_ids(self) -> tuple[int, ...]:
        # 后台列表顺序稳定时，动作范围也保持该顺序，便于预览和回读。
        return tuple(item.model_id for item in self._rows if item.model_id in self._selected)

    def selected_rows(self) -> tuple[ExistingModelRow, ...]:
        selected = set(self._selected)
        return tuple(item for item in self._rows if item.model_id in selected)

    def build_unlist_plan(self, products_by_model: Mapping[int | str, Sequence[Mapping[str, Any]]] | None = None) -> "UnlistPlan":
        return build_unlist_plan(self.selected_rows(), products_by_model or {})


@dataclass(frozen=True)
class UnlistProductScope:
    model_id: int
    product_ids: tuple[int, ...]
    total_target: int = 0


@dataclass(frozen=True)
class UnlistPlan:
    """下架四步的审阅结果；``executable`` 始终为 False，直到契约补证。"""

    model_ids: tuple[int, ...]
    model_extension_targets: Mapping[int, Mapping[str, Any]]
    product_scopes: tuple[UnlistProductScope, ...]
    model_targets: Mapping[int, Mapping[str, int]]
    blocked_reasons: tuple[str, ...]
    executable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_ids": list(self.model_ids),
            "model_extension_targets": {str(key): dict(value) for key, value in self.model_extension_targets.items()},
            "product_scopes": [
                {"model_id": item.model_id, "product_ids": list(item.product_ids), "total_target": item.total_target}
                for item in self.product_scopes
            ],
            "model_targets": {str(key): dict(value) for key, value in self.model_targets.items()},
            "blocked_reasons": list(self.blocked_reasons),
            "executable": self.executable,
        }


def _validate_products(model_id: int, rows: Sequence[Mapping[str, Any]]) -> tuple[UnlistProductScope, list[str]]:
    reasons: list[str] = []
    product_ids: list[int] = []
    product_auto_off: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            reasons.append(f"模型 {model_id} 产品第 {index + 1} 行不是对象")
            continue
        product_id = _as_int(row.get("id", row.get("product_id", row.get("productId"))), "产品 ID")
        mid = _as_int(row.get("mid", row.get("model_id", row.get("modelId"))), "产品 mid")
        gid = _as_int(row.get("gid", row.get("game_id", row.get("gameId"))), "产品 gid")
        cid = _as_int(row.get("cid", row.get("category_id", row.get("categoryId"))), "产品 cid")
        if product_id is None or mid is None or gid is None or cid is None:
            reasons.append(f"模型 {model_id} 产品第 {index + 1} 行缺少 id/mid/gid/cid")
            continue
        if mid != model_id or gid != SUPPORTED_GID or cid != SUPPORTED_CID:
            reasons.append(f"模型 {model_id} 产品 {product_id} 超出 FC27/Players 或模型范围")
        if "total" not in row:
            reasons.append(f"模型 {model_id} 产品 {product_id} 缺少库存字段 total")
        else:
            try:
                total = Decimal(str(row.get("total")).strip())
                if not total.is_finite() or total < 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                reasons.append(f"模型 {model_id} 产品 {product_id} total 不是合法非负数")
        # 用户已明确不修改产品 auto_off，但要回读它才能判断 total=0 的效果。
        auto_off = _binary(row.get("auto_off", row.get("autoOff")))
        if auto_off is None:
            reasons.append(f"模型 {model_id} 产品 {product_id} 缺少可核验 auto_off；无法证明下架效果")
        else:
            product_auto_off.append(auto_off)
        if product_id in product_ids:
            reasons.append(f"模型 {model_id} 产品 ID 重复：{product_id}")
        product_ids.append(product_id)
    if not rows:
        reasons.append(f"模型 {model_id} 没有完整关联产品列表")
    if product_auto_off and any(value != 1 for value in product_auto_off):
        reasons.append(f"模型 {model_id} 关联产品存在 auto_off=0；不修改产品 auto_off，total=0 的实际下架效果待核验")
    return UnlistProductScope(model_id, tuple(product_ids)), reasons


def build_unlist_plan(
    rows: Sequence[ExistingModelRow],
    products_by_model: Mapping[int | str, Sequence[Mapping[str, Any]]],
) -> UnlistPlan:
    """构造下架四步计划，不发起任何网络请求。"""

    if not rows:
        raise UnlistBlocked("未选择任何后台模型")
    model_ids = tuple(item.model_id for item in rows)
    extension_targets: dict[int, Mapping[str, Any]] = {}
    model_targets: dict[int, Mapping[str, int]] = {}
    product_scopes: list[UnlistProductScope] = []
    reasons: list[str] = [
        "模型扩展 untradeable 与产品 Goods/edit 写入/回读契约尚未在本地证据中核实",
        "本地安全边界未开放下架真实写入；完成计划不会改变后台数据",
    ]
    for item in rows:
        entries = _extend_entries(item.raw)
        if entries is None:
            reasons.append(f"模型 {item.model_id} 缺少已核实的 more.extend，无法安全设置 untradeable=1")
        else:
            matching = [entry for entry in entries if str(entry.get("key") or "").strip().casefold() == "untradeable"]
            if len(matching) > 1:
                reasons.append(f"模型 {item.model_id} more.extend 含重复 untradeable")
            elif not matching:
                reasons.append(f"模型 {item.model_id} more.extend 未找到 untradeable，追加扩展项的写入语义待核验")
            extension_targets[item.model_id] = {"untradeable": 1}
        if item.status is None:
            reasons.append(f"模型 {item.model_id} 缺少可回读 status")
        if item.auto_off is None:
            reasons.append(f"模型 {item.model_id} 缺少可回读 auto_off")
        model_targets[item.model_id] = {"status": 0, "auto_off": 1}
        product_rows = products_by_model.get(item.model_id)
        if product_rows is None and str(item.model_id) in products_by_model:
            product_rows = products_by_model[str(item.model_id)]  # type: ignore[index]
        if product_rows is None:
            reasons.append(f"模型 {item.model_id} 未提供完整关联产品列表")
            continue
        scope, product_reasons = _validate_products(item.model_id, product_rows)
        product_scopes.append(scope)
        reasons.extend(product_reasons)
    return UnlistPlan(model_ids, extension_targets, tuple(product_scopes), model_targets, tuple(dict.fromkeys(reasons)), False)


