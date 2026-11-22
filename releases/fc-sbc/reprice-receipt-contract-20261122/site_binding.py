"""Offline selection of one explicitly configured Admin product row."""
from dataclasses import dataclass
from typing import Iterable, Optional

from shadow_verify import RowScope


@dataclass(frozen=True)
class BindingKey:
    model_id: int
    site_id: int
    platform_id: int
    game_id: int
    category_id: int

    def __post_init__(self):
        ids = (self.model_id, self.platform_id, self.game_id, self.category_id)
        if any(type(v) is not int or v <= 0 for v in ids):
            raise ValueError("explicit model, platform, game and category required")
        if type(self.site_id) is not int or self.site_id < 0:
            raise ValueError("explicit site required; 0 means the template")


@dataclass(frozen=True)
class AdminRow:
    key: BindingKey
    goods_id: int

    def __post_init__(self):
        if type(self.goods_id) is not int or self.goods_id < 1:
            raise ValueError("explicit goods row required")


@dataclass(frozen=True)
class Binding:
    state: str
    row: Optional[RowScope] = None


def bind(configured: Optional[BindingKey], candidates: Iterable[AdminRow]) -> Binding:
    """Input candidates must be the complete Admin list for the requested scope.

    No wildcard or fallback is permitted, including to or from the site-0
    template. This resolver does not discover config or perform a query.
    """
    if configured is None:
        return Binding("not_configured")
    rows = list(candidates)
    if any(row.key != configured for row in rows):
        return Binding("scope_mismatch")
    if len(rows) != 1:
        return Binding("ambiguous" if rows else "not_found")
    return Binding("bound", RowScope(configured.site_id, configured.platform_id, rows[0].goods_id))
