"""新卡流程的本地选择状态和安全的工作簿筛选。

这个模块只处理本地选择状态，不执行后台写入。每个 FUTBIN ID 都有三个
相互独立的意图位：导入上架、添加标签、开启推荐。选择文件只会包含导入
上架集合，避免把列表中未勾选的球员带入后台任务。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def _clean_id(value: Any) -> str:
    text = str(value or "").strip()
    return text


def player_futbin_id(row: Mapping[str, Any]) -> str:
    for key in ("futbin_id", "futbinId", "FUTBIN ID"):
        value = _clean_id(row.get(key))
        if value:
            return value
    return ""


def validate_intent_scope(
    upload_ids: Iterable[Any],
    tag_ids: Iterable[Any] = (),
    recommend_ids: Iterable[Any] = (),
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """确保新卡后续动作只引用本次勾选上架集合。"""

    upload = tuple(dict.fromkeys(item for item in (_clean_id(value) for value in upload_ids) if item))
    tags = tuple(dict.fromkeys(item for item in (_clean_id(value) for value in tag_ids) if item))
    recommend = tuple(dict.fromkeys(item for item in (_clean_id(value) for value in recommend_ids) if item))
    scope = set(upload)
    extras = sorted((set(tags) | set(recommend)) - scope)
    if extras:
        raise ValueError(f"标签/推荐选择包含未勾选上架的 FUTBIN ID：{', '.join(extras)}")
    return upload, tags, recommend


@dataclass
class NewCardSelection:
    """可保存的单行选择意图。"""

    futbin_id: str
    player: dict[str, Any] = field(default_factory=dict)
    upload: bool = False
    tags: bool = False
    recommend: bool = False
    existing_model_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        # player 是数据库只读结果，可能包含价格和图片 URL；保存选择时保留
        # 展示所需字段即可，不写入账号、token 或后台响应。
        display_keys = (
            "futbin_id", "name", "common_name", "rating", "position", "pos_all",
            "club_name", "league_name", "nation_name", "rare_type_name",
            "pc_price", "ps_price", "xbox_price", "updated_at", "resource_id",
        )
        safe_player = {key: self.player.get(key) for key in display_keys if key in self.player}
        result: dict[str, Any] = {
            "futbin_id": self.futbin_id,
            "player": safe_player,
            "upload": bool(self.upload),
            "tags": bool(self.tags),
            "recommend": bool(self.recommend),
        }
        if self.existing_model_id is not None:
            result["existing_model_id"] = int(self.existing_model_id)
        return result


class NewCardSelectionBasket:
    """按 FUTBIN ID 去重的选择集合，供 GUI 和测试共同使用。"""

    def __init__(self, rows: Iterable[Mapping[str, Any]] = ()) -> None:
        self.rows: dict[str, NewCardSelection] = {}
        self.replace(rows)

    def replace(self, rows: Iterable[Mapping[str, Any]]) -> None:
        updated: dict[str, NewCardSelection] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            futbin_id = player_futbin_id(row)
            if not futbin_id:
                raise ValueError("球员行缺少明确 FUTBIN ID")
            if futbin_id in updated:
                raise ValueError(f"球员列表含重复 FUTBIN ID：{futbin_id}")
            updated[futbin_id] = NewCardSelection(futbin_id=futbin_id, player=dict(row))
        self.rows = updated

    def set_existing_models(self, model_map: Mapping[Any, Any]) -> None:
        for key, model_id in model_map.items():
            futbin_id = _clean_id(key)
            if futbin_id not in self.rows:
                continue
            try:
                parsed = int(model_id)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                self.rows[futbin_id].existing_model_id = parsed

    def set_intent(self, futbin_ids: Iterable[Any], intent: str, enabled: bool = True) -> None:
        if intent not in {"upload", "tags", "recommend"}:
            raise ValueError(f"未知选择意图：{intent}")
        for value in futbin_ids:
            futbin_id = _clean_id(value)
            row = self.rows.get(futbin_id)
            if row is None:
                continue
            setattr(row, intent, bool(enabled))

    def selected_ids(self, intent: str, *, include_existing: bool = True) -> tuple[str, ...]:
        if intent not in {"upload", "tags", "recommend"}:
            raise ValueError(f"未知选择意图：{intent}")
        result: list[str] = []
        for row in self.rows.values():
            if not getattr(row, intent):
                continue
            if not include_existing and row.existing_model_id is not None:
                continue
            result.append(row.futbin_id)
        return tuple(result)

    def selected_existing_model_ids(self, intent: str) -> tuple[int, ...]:
        if intent not in {"tags", "recommend"}:
            raise ValueError("只有标签和推荐支持已有模型范围")
        result: list[int] = []
        for row in self.rows.values():
            if not getattr(row, intent) or row.existing_model_id is None:
                continue
            if row.existing_model_id not in result:
                result.append(row.existing_model_id)
        return tuple(result)

    def selected_existing_model_pairs(self, intent: str) -> tuple[tuple[str, int], ...]:
        """返回已有卡动作的冻结 ``(FUTBIN ID, 模型 ID)`` 对。

        模型 ID 不能单独作为新卡批次的范围依据；保留 FUTBIN ID 便于
        写入前重新读取模型并核对映射是否漂移。
        """

        if intent not in {"tags", "recommend"}:
            raise ValueError("只有标签和推荐支持已有模型范围")
        result: list[tuple[str, int]] = []
        seen_model_ids: set[int] = set()
        for row in self.rows.values():
            if not getattr(row, intent) or row.existing_model_id is None:
                continue
            model_id = int(row.existing_model_id)
            if model_id in seen_model_ids:
                raise ValueError(f"已有模型 ID 重复，无法冻结安全范围：{model_id}")
            seen_model_ids.add(model_id)
            result.append((row.futbin_id, model_id))
        return tuple(result)

    def selected_new_ids(self, intent: str) -> tuple[str, ...]:
        return self.selected_ids(intent, include_existing=False)

    def rows_for(self, query: str = "") -> tuple[NewCardSelection, ...]:
        needle = str(query or "").strip().casefold()
        if not needle:
            return tuple(self.rows.values())
        result: list[NewCardSelection] = []
        for row in self.rows.values():
            values = (row.futbin_id, row.player.get("name"), row.player.get("common_name"), row.player.get("position"), row.player.get("club_name"), row.player.get("league_name"))
            if any(needle in str(value or "").casefold() for value in values):
                result.append(row)
        return tuple(result)

    def to_dict(self) -> dict[str, Any]:
        return {"rows": [row.to_dict() for row in self.rows.values()]}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NewCardSelectionBasket":
        rows: list[Mapping[str, Any]] = []
        for item in payload.get("rows", []) if isinstance(payload, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            player = item.get("player") if isinstance(item.get("player"), Mapping) else item
            row = dict(player)
            row["futbin_id"] = item.get("futbin_id", row.get("futbin_id"))
            rows.append(row)
        basket = cls(rows)
        for item in payload.get("rows", []) if isinstance(payload, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            futbin_id = _clean_id(item.get("futbin_id"))
            if futbin_id not in basket.rows:
                continue
            current = basket.rows[futbin_id]
            for key in ("upload", "tags", "recommend"):
                setattr(current, key, bool(item.get(key, False)))
            try:
                current.existing_model_id = int(item["existing_model_id"]) if item.get("existing_model_id") is not None else None
            except (TypeError, ValueError):
                current.existing_model_id = None
        return basket

    def save(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.part")
        partial.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        partial.replace(target)
        return target

    @classmethod
    def load(cls, path: str | Path) -> "NewCardSelectionBasket":
        target = Path(path).expanduser()
        return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))


def filter_rows_by_ids(source: str | Path, destination: str | Path, futbin_ids: Sequence[Any]) -> Path:
    """从已转换的纯数据 XLSX 生成只含选中 FUTBIN ID 的上传文件。

    使用 openpyxl 读取/写入工作簿；源文件永不覆盖。任何 ID 缺失或重复都
    阻断，防止用户以为勾选集合已经完整而实际上传了部分数据。
    """

    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - bundled runtime supplies it
        raise RuntimeError("当前运行环境缺少 openpyxl，无法生成选中上架文件") from exc
    wanted = [value for value in (_clean_id(item) for item in futbin_ids) if value]
    if len(wanted) != len(set(wanted)):
        raise ValueError("上架选择含重复 FUTBIN ID")
    if not wanted:
        raise ValueError("至少选择一名球员上架")
    source_path = Path(source).expanduser()
    target = Path(destination).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.resolve() == target.resolve():
        raise ValueError("选中上架文件不得覆盖源文件")
    workbook = openpyxl.load_workbook(source_path, read_only=True, data_only=False)
    try:
        sheet = workbook["球员"] if "球员" in workbook.sheetnames else workbook[workbook.sheetnames[0]]
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            raise ValueError("源工作簿没有数据行")
        headers = [str(value or "").strip() for value in rows[0]]
        id_index = next((index for index, value in enumerate(headers) if value.casefold() == "futbin id"), None)
        if id_index is None:
            raise ValueError("源工作簿缺少 FUTBIN ID 列")
        selected: dict[str, tuple[Any, ...]] = {}
        for row in rows[1:]:
            values = tuple(row)
            futbin_id = _clean_id(values[id_index] if id_index < len(values) else "")
            if not futbin_id:
                raise ValueError("源工作簿含空 FUTBIN ID")
            if futbin_id in selected:
                raise ValueError(f"源工作簿含重复 FUTBIN ID：{futbin_id}")
            if futbin_id in wanted:
                selected[futbin_id] = values
        missing = [item for item in wanted if item not in selected]
        if missing:
            raise ValueError(f"上架选择的 FUTBIN ID 不在转换文件中：{', '.join(missing)}")
    finally:
        workbook.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    output = openpyxl.Workbook()
    partial = target.with_name(f".{target.name}.part")
    try:
        sheet_out = output.active
        sheet_out.title = "球员"
        sheet_out.append(list(rows[0]))
        for futbin_id in wanted:
            sheet_out.append(list(selected[futbin_id]))
        output.save(partial)
        partial.replace(target)
    finally:
        output.close()
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
    return target


__all__ = [
    "NewCardSelection",
    "NewCardSelectionBasket",
    "filter_rows_by_ids",
    "player_futbin_id",
    "validate_intent_scope",
]
