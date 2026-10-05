"""本地配置、运行目录、历史和脱敏日志。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .models import PipelineConfig, RunRecord, utc_now_iso


_SENSITIVE_KEY = re.compile(
    r"(password|passwd|token|secret|authorization|cookie|session|api[_-]?key|backup[_-]?code|customer|phone|email)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(password|passwd|token|secret|authorization|cookie|session|api[_-]?key|refresh[_-]?token)(\s*[=:]\s*)([^\s&,;]+)"
)
_URL_CREDENTIAL = re.compile(r"(?i)(https?://)([^/@\s]+):([^/@\s]+)@")


def redact_text(value: Any) -> str:
    """去除异常文本和第三方错误信息中可能出现的凭据。"""

    text = str(value)
    text = _URL_CREDENTIAL.sub(r"\1[REDACTED]@", text)
    return _SENSITIVE_TEXT.sub(r"\1\2[REDACTED]", text)


def redact(value: Any, key: str = "") -> Any:
    """递归去除日志中的凭据和客户敏感字段。"""

    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(redact(value), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        return default


class JsonlLogger:
    """结构化 JSONL 日志；写入前会递归脱敏。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, level: str, event: str, message: str = "", **data: Any) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "timestamp": utc_now_iso(),
            "level": level.upper(),
            "event": event,
            "message": redact_text(message),
        }
        if data:
            record["data"] = redact(data)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record


class LocalStore:
    """管理工具目录下的配置、运行产物和历史索引。"""

    def __init__(self, app_dir: Path) -> None:
        self.app_dir = app_dir
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.app_dir / "config.json"
        self.history_path = self.app_dir / "history.json"

    def save_config(self, config: PipelineConfig, path: Optional[Path] = None) -> Path:
        target = path or self.config_path
        atomic_write_json(target, config.to_dict())
        return target

    def load_config(self, path: Optional[Path] = None) -> PipelineConfig:
        target = path or self.config_path
        raw = read_json(target, {})
        if not isinstance(raw, Mapping):
            raise ValueError("配置文件根节点必须是对象")
        return PipelineConfig.from_dict(raw)

    def create_run_dir(self, output_root: str, run_id: Optional[str] = None) -> tuple[str, Path]:
        base = Path(output_root).expanduser()
        if not base.is_absolute():
            base = self.app_dir / base
        base.mkdir(parents=True, exist_ok=True)
        identifier = run_id or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        run_dir = base / f"run_{identifier}"
        # 即使同一秒执行，也不覆盖已有运行目录。
        suffix = 1
        unique_dir = run_dir
        while unique_dir.exists():
            unique_dir = base / f"run_{identifier}_{suffix}"
            suffix += 1
        unique_dir.mkdir(parents=True, exist_ok=False)
        return identifier if unique_dir == run_dir else unique_dir.name.removeprefix("run_"), unique_dir

    def append_history(self, record: RunRecord) -> None:
        history = read_json(self.history_path, [])
        if not isinstance(history, list):
            history = []
        history.insert(0, redact(record.to_dict()))
        atomic_write_json(self.history_path, history[:200])

    def load_history(self) -> List[Dict[str, Any]]:
        history = read_json(self.history_path, [])
        return history if isinstance(history, list) else []
