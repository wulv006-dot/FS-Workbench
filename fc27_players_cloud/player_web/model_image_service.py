"""Folder PNG matching, immutable image plans and per-model image readback."""
from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from PIL import Image
from 球员维护工具.admin_adapter import extract_futbin_id, extract_model_id
from .media_client import ImageUploadNotStarted, edit_model_icon, upload_png
from .repository import Repository, StateError, now
from .settings import Settings

MAX_PNG_BYTES = 2 * 1024 * 1024
MAX_BATCH_BYTES = 128 * 1024 * 1024
MAX_FILES = 500


def validate_png(content: bytes) -> dict[str, int]:
    if not content or len(content) > MAX_PNG_BYTES or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StateError("INVALID_PNG")
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            if image.format != "PNG" or width < 1 or height < 1 or width * height > 16000000:
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except Exception:
        raise StateError("INVALID_PNG") from None
    return {"width": width, "height": height}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(client: Any, model_id: int, futbin_id: str) -> Mapping[str, Any]:
    row = client.get_model(model_id)
    if (extract_model_id(row) != model_id or extract_futbin_id(row) != futbin_id
            or str(row.get("gid")) != "1327" or str(row.get("cid")) != "9627"):
        raise StateError("IMAGE_MODEL_IDENTITY_CHANGED")
    if "icon" not in row:
        raise StateError("IMAGE_FIELD_UNKNOWN")
    return row


def _batch(settings: Settings, owner: str, batch_id: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        raise StateError("IMAGE_BATCH_INVALID")
    root = settings.data_root / "image_batches" / batch_id
    try:
        meta = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StateError("IMAGE_BATCH_INVALID") from None
    if meta.get("owner") != owner or meta["expires_at"] <= now():
        raise StateError("IMAGE_BATCH_EXPIRED")
    return root, meta


def create_batch(settings: Settings, repo: Repository, client: Any, owner: str,
                 snapshot_id: str, files: Any, overwrite: bool = False) -> dict:
    if not getattr(client, "authenticated", False):
        raise StateError("AUTH_REQUIRED")
    snapshot = repo.model_snapshot(snapshot_id, owner)
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES or not isinstance(overwrite, bool):
        raise StateError("IMAGE_BATCH_INVALID")
    mapping: dict[str, list[dict]] = {}
    for row in repo.model_rows(snapshot_id, owner):
        mapping.setdefault(str(row["futbin_id"]), []).append(row)
    names = [str(item.get("name") or "") for item in files if isinstance(item, dict)]
    if len(names) != len(files) or len({name.lower() for name in names}) != len(names):
        raise StateError("IMAGE_DUPLICATE_FILENAME")
    items, total_size = [], 0
    for file in files:
        name = str(file.get("name") or "")
        item = {"name": name[:200], "status": "invalid_filename"}
        match = re.fullmatch(r"([1-9][0-9]*)\.png", name, re.IGNORECASE)
        if not match:
            items.append(item)
            continue
        futbin_id = match.group(1)
        size, digest = file.get("size"), str(file.get("sha256") or "")
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_PNG_BYTES or not re.fullmatch(r"[0-9a-f]{64}", digest):
            item["status"] = "invalid_file"
            items.append(item)
            continue
        total_size += size
        item.update(futbin_id=futbin_id, size=size, sha256=digest, stored_name=futbin_id + ".png")
        models = mapping.get(futbin_id, [])
        if len(models) != 1:
            item["status"] = "unmatched" if not models else "ambiguous_model"
        else:
            cached = models[0]
            model_id = int(cached["model_id"])
            live = _identity(client, model_id, futbin_id)
            icon = live["icon"]
            item.update(model_id=model_id, title=str(cached.get("title") or ""), before={"icon": icon})
            item["status"] = "existing_image_skipped" if str(icon or "") not in {"", "0"} and not overwrite else "matched"
        items.append(item)
    if total_size > MAX_BATCH_BYTES:
        raise StateError("IMAGE_BATCH_TOO_LARGE")
    batch_id = uuid.uuid4().hex
    root = settings.data_root / "image_batches" / batch_id
    root.mkdir(parents=True, exist_ok=False)
    meta = {"batch_id": batch_id, "owner": owner, "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot["snapshot_digest"], "overwrite": overwrite,
            "created_at": now(), "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds"),
            "items": items}
    (root / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    repo.audit(owner, "image_batch_matched", batch_id,
               {"count": len(items), "matched": sum(item["status"] == "matched" for item in items), "overwrite": overwrite})
    return meta


def stage_png(settings: Settings, owner: str, batch_id: str, name: str, content: bytes) -> dict:
    root, meta = _batch(settings, owner, batch_id)
    item = next((row for row in meta["items"] if row["name"] == name and row["status"] == "matched"), None)
    if not item or len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
        raise StateError("IMAGE_FILE_CHANGED")
    size = validate_png(content)
    path = root / item["stored_name"]
    if path.exists():
        if _sha(path) != item["sha256"]:
            raise StateError("IMAGE_FILE_CHANGED")
    else:
        with path.open("xb") as handle:
            handle.write(content)
    return {"staged": True, "name": item["name"], **size}


def prepare_image_plan(settings: Settings, repo: Repository, client: Any, owner: str, batch_id: str) -> dict:
    if not getattr(client, "authenticated", False):
        raise StateError("AUTH_REQUIRED")
    root, batch = _batch(settings, owner, batch_id)
    repo.model_snapshot(batch["snapshot_id"], owner)
    items = []
    for row in batch["items"]:
        if row["status"] != "matched":
            continue
        artifact = root / row["stored_name"]
        if not artifact.is_file() or _sha(artifact) != row["sha256"]:
            raise StateError("IMAGE_FILE_CHANGED")
        validate_png(artifact.read_bytes())
        live = _identity(client, row["model_id"], row["futbin_id"])
        if live["icon"] != row["before"]["icon"]:
            raise StateError("IMAGE_MODEL_CHANGED")
        items.append({**row, "artifact_path": str(artifact), "after": {"png_sha256": row["sha256"]}})
    if not items:
        raise StateError("IMAGE_NO_MATCHES")
    ids = [item["futbin_id"] for item in items]
    if len(set(ids)) != len(ids):
        raise StateError("IMAGE_DUPLICATE_FILENAME")
    blockers = ["LEGACY_UNRESOLVED"] if repo.legacy_blocks(ids) else []
    return repo.save_plan(owner, {"kind": "model_images", "batch_id": batch_id,
                                "scope_ids": ids, "items": items, "blockers": blockers,
                                "overwrite": batch["overwrite"], "actions": ["set_model_icon"]})


def verify_image_plan(settings: Settings, client: Any, plan: Mapping[str, Any]) -> None:
    if plan.get("kind") != "model_images" or plan.get("gid") != 1327 or plan.get("cid") != 9627 or plan.get("blockers"):
        raise StateError("PLAN_BLOCKED")
    items = plan.get("items") or []
    if not items or {item["futbin_id"] for item in items} != set(plan["scope_ids"]):
        raise StateError("IMAGE_BATCH_INVALID")
    root = (settings.data_root / "image_batches" / str(plan["batch_id"])).resolve()
    for item in items:
        path = Path(item["artifact_path"])
        if path.resolve().parent != root or path.is_symlink() or not path.is_file() or _sha(path) != item["sha256"]:
            raise StateError("IMAGE_FILE_CHANGED")
        validate_png(path.read_bytes())
        live = _identity(client, item["model_id"], item["futbin_id"])
        if live["icon"] != item["before"]["icon"]:
            raise StateError("IMAGE_MODEL_CHANGED")


def execute_image_plan(settings: Settings, repo: Repository, client: Any,
                       execution_id: str, plan: Mapping[str, Any], should_stop: Any = None) -> None:
    if not settings.model_image_write_enabled:
        raise StateError("WRITE_DISABLED")
    current_id = None
    uploaded = None
    try:
        verify_image_plan(settings, client, plan)
        for item in plan["items"]:
            if should_stop and should_stop():
                repo.set_execution(execution_id, "stopped", "image_not_started", release_scope=True)
                return
            current_id = item["model_id"]
            uploaded = None
            live = _identity(client, current_id, item["futbin_id"])
            if live["icon"] != item["before"]["icon"]:
                raise StateError("IMAGE_MODEL_CHANGED")
            repo.set_execution(execution_id, "running", "image_upload_intent", {"model_id": current_id, "sha256": item["sha256"]})
            uploaded = upload_png(client, Path(item["artifact_path"]))
            repo.set_execution_item(execution_id, current_id, "dispatch_intent", before=item["before"], after=uploaded)
            repo.set_execution(execution_id, "running", "image_attachment_readback", {"model_id": current_id, **uploaded})
            if should_stop and should_stop():
                raise StateError("IMAGE_STOPPED_AFTER_UPLOAD")
            live = _identity(client, current_id, item["futbin_id"])
            if live["icon"] != item["before"]["icon"]:
                raise StateError("IMAGE_MODEL_CHANGED")
            repo.set_execution(execution_id, "running", "image_edit_intent", {"model_id": current_id, **uploaded})
            edit_model_icon(client, current_id, uploaded["attachment_id"])
            readback = _identity(client, current_id, item["futbin_id"])
            if str(readback["icon"]) != str(uploaded["attachment_id"]):
                raise StateError("IMAGE_READBACK_INCOMPLETE")
            repo.set_execution_item(execution_id, current_id, "verified", before=item["before"],
                                    after={"icon": readback["icon"], "png_sha256": item["sha256"], **uploaded})
        repo.set_execution(execution_id, "completed_readback", "done", {"images_verified": len(plan["items"])}, release_scope=True)
    except ImageUploadNotStarted as exc:
        if current_id is not None:
            repo.set_execution_item(execution_id, current_id, "not_started", after={"error_code": str(exc)})
        repo.set_execution(execution_id, "failed", "image_not_started", {"error_code": str(exc)}, release_scope=True)
        raise
    except Exception as exc:
        if current_id is not None:
            repo.set_execution_item(execution_id, current_id, "unknown", after={**(uploaded or {}), "error_type": type(exc).__name__})
        repo.set_execution(execution_id, "needs_reconcile", "image_unknown", {"error_type": type(exc).__name__})
        raise
