"""服务器候选球员只读拉取；不包含任何后台写入路径。"""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from 球员维护工具.models import ExportFilters
from 球员维护工具.selection import extract_player_futbin_id

from .client_factory import player_client
from .repository import Repository, now
from .settings import Settings


DISPLAY_FIELDS = (
    "futbin_id", "futbinId", "FUTBIN ID", "name", "common_name", "rating",
    "position", "club_name", "league_name", "nation_name", "rare_type_name",
    "resource_id", "updated_at",
)


@contextmanager
def collection_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
        yield acquired
    finally:
        if acquired:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def read_all_candidate_pages(source: Any, filters: Mapping[str, Any], maximum: int) -> tuple[int, list[Mapping[str, Any]]]:
    """每页都传同一 days_new；允许多卡版本但拒绝分页缺失、漂移和重复卡片。"""
    page, total, rows = 1, None, []
    seen_keys: set[str] = set()
    while True:
        result = source.list_players(ExportFilters(dict(filters)), page=page, per_page=200)
        if total is None:
            total = result.total
            if total < 0 or total > maximum:
                raise ValueError("SOURCE_CANDIDATE_LIMIT")
        if result.total != total or (result.page is not None and result.page != page) or (
            result.per_page is not None and result.per_page != 200
        ):
            raise ValueError("SOURCE_PAGE_DRIFT")
        remaining = total - len(rows)
        expected = min(200, remaining)
        if len(result.items) != expected:
            raise ValueError("SOURCE_PAGE_INCOMPLETE")
        for item in result.items:
            futbin_id = extract_player_futbin_id(item)
            resource_id = item.get("resource_id")
            if not futbin_id:
                raise ValueError("SOURCE_ID_MISSING")
            key = str(resource_id) if resource_id is not None else "futbin:" + str(futbin_id)
            if key in seen_keys:
                raise ValueError("SOURCE_CARD_DUPLICATE")
            seen_keys.add(key)
            rows.append(item)
        if len(rows) == total:
            return total, rows
        page += 1


def collect_only(settings: Settings, repository: Repository, *, client: Any = None,
                 days_new: int | None = None) -> dict[str, Any]:
    if not settings.collector_enabled:
        raise RuntimeError("COLLECTOR_DISABLED")
    days = settings.lookback_days if days_new is None else days_new
    if isinstance(days, bool) or not isinstance(days, int) or days not in {1, 3, 7, 14, 30}:
        raise ValueError("INVALID_DAYS_NEW")
    source = client or player_client(settings)
    filters = {"days_new": str(days)}
    source_id = hashlib.sha256(settings.player_db_base_url.encode("utf-8")).hexdigest()[:16]
    lock_name = "collection.lock" if days_new is None else f"manual-{days}.lock"
    with collection_lock(settings.data_root / "locks" / lock_name) as acquired:
        if not acquired:
            raise RuntimeError("COLLECTION_ALREADY_RUNNING")
        started = now()
        try:
            status = source.get_status()
            if not isinstance(status, Mapping):
                raise ValueError("SOURCE_STATUS_INVALID")
            total, rows = read_all_candidate_pages(source, filters, settings.max_candidates)
            if total != len(rows):
                raise ValueError("SOURCE_INCOMPLETE")
            clean: list[dict[str, Any]] = []
            for row in rows:
                item = {key: row[key] for key in DISPLAY_FIELDS if key in row}
                item["futbin_id"] = extract_player_futbin_id(row)
                clean.append(item)
            # /api/status 字段没有在当前材料中被证明代表源更新时间。
            collection_id = repository.save_collection(source_id, filters, clean, source_time=None,
                                                       started_at=started)
            repository.audit("collector", "collection_success", collection_id, {"total": total})
            snapshot = repository.get_collection(collection_id)
            return {"collection_id": collection_id, "query_hash": snapshot["query_hash"],
                    "days_new": days, "status": "success_no_candidates" if total == 0 else "success",
                    "total": total, "read_count": len(rows), "source_freshness": "unknown"}
        except Exception as exc:
            collection_id = repository.save_collection_failure(source_id, filters, type(exc).__name__,
                                                               started_at=started)
            repository.audit("collector", "collection_failed", collection_id, {"error_type": type(exc).__name__})
            raise
