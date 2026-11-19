"""The official Admin PNG uploader; signing material never leaves process memory."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from 球员维护工具.admin_client import AdminAuthError, AdminContractError, _multipart_body, _NoRedirect

AUTH_MODULE_URL = "https://admin.p2pah.cn/assets/uploadAuth-e88263af.js"
AUTH_MODULE_SHA = "108604361886ac92e1616191569d5a9c76364115b2afe2d04cb672a87f3c94a7"
UPLOAD_URL = "https://b2c-api.p2pah.cn/upload/file"


class ImageUploadNotStarted(AdminContractError):
    """Upload preparation failed before the single POST could be dispatched."""


def upload_png(client: Any, path: Path) -> dict[str, Any]:
    if not getattr(client, "authenticated", False):
        raise AdminAuthError("尚未登录")
    opener = urllib.request.build_opener(_NoRedirect()).open
    # Load the very same public signer as the official page, pinned to its reviewed hash.
    # Never persist its source, signing material, timestamp or generated token.
    try:
        with opener(urllib.request.Request(AUTH_MODULE_URL), timeout=15) as response:
            script = response.read(65537)
        if hashlib.sha256(script).hexdigest() != AUTH_MODULE_SHA:
            raise ImageUploadNotStarted("IMAGE_UPLOAD_CONTRACT_CHANGED")
        match = re.search(r'UPLOAD_AUTH_SECRET\s*=\s*("(?:[^"\\]|\\.)*")', script.decode("utf-8"))
        if not match:
            raise ImageUploadNotStarted("IMAGE_UPLOAD_CONTRACT_CHANGED")
        material = json.loads(match.group(1))
        timestamp = int(time.time() * 1000)
        token = hashlib.md5((str(timestamp) + material).encode()).hexdigest()
        body, content_type = _multipart_body(
            {"token": token, "timestamp": timestamp, "id": 0, "view": 1, "type": 0, "watermark": 0},
            "file", path.name, path.read_bytes())
        request = urllib.request.Request(UPLOAD_URL, data=body, method="POST",
                                         headers={"Content-Type": content_type, "Accept": "application/json"})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
        raise ImageUploadNotStarted("IMAGE_UPLOAD_PRECHECK_FAILED") from None
    try:
        # This official media endpoint uses its own upload signature, not the Admin login token.
        # POST is performed once. Any missing response is left unknown, never retransmitted.
        with opener(request, timeout=client.timeout) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise AdminContractError("IMAGE_UPLOAD_RESPONSE_INVALID")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise AdminContractError("IMAGE_UPLOAD_RESPONSE_INVALID")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise AdminContractError("IMAGE_UPLOAD_RESPONSE_INVALID")
        upload = data.get("upload", {})
        picture = (upload.get("picture") if isinstance(upload, dict) else None) or data.get("picture")
        if not isinstance(picture, dict) or picture.get("code") != 200:
            raise AdminContractError("IMAGE_UPLOAD_REJECTED")
        file = picture.get("file")
        if not isinstance(file, dict) or isinstance(file.get("id"), bool) or not str(file.get("id", "")).isascii() or not str(file.get("id", "")).isdigit() or int(file["id"]) < 1:
            raise AdminContractError("IMAGE_UPLOAD_RESPONSE_INVALID")
        return {"attachment_id": int(file["id"]), "url": str(file.get("full_url") or "")}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
        # Never surface an upstream body or a multipart request containing the upload signature.
        raise AdminContractError("IMAGE_UPLOAD_UNKNOWN") from None


def edit_model_icon(client: Any, model_id: int, attachment_id: int) -> None:
    # The official model form writes `icon` as an attachment ID, never as a path or URL.
    client._edit_fields("/admin/goods.GoodsMould/edit", {"id": model_id, "icon": attachment_id},
                        allowed_fields={"icon"}, label="模型图片")
