"""Shared customer stage, value tier, and repeat-purchase rules."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
_STAGES = ("recent", "silent", "lost", "long_lost")
_COMMON_THRESHOLDS = (30, 60, 90)
_DEFAULT_TIER = {"ultra": 1000, "high": 500}
_DEFAULT_VERSION = 0
_CONFIG_FIELDS = {"version", "stages", "tiers"}
# user_config.json resolves the FC series to fc-v1 unless a project sets its own policy.
_GAME_THRESHOLDS = {"1327": (14, 30, 60), "833": (14, 30, 90)}


def _shanghai_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.utcoffset() is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def thresholds(gid, config):
    """Return the stage thresholds for a game or the fixed all-games scope."""
    gid = str(gid)
    if gid == "all":
        return _COMMON_THRESHOLDS
    return tuple(config["stages"].get(gid, _GAME_THRESHOLDS.get(gid, _COMMON_THRESHOLDS)))


def stage(last_paid_at, observation_date, gid, config, covered):
    """Classify the customer at the observation day in Shanghai."""
    if not covered:
        return "unverified"
    if isinstance(observation_date, str):
        observation_date = date.fromisoformat(observation_date)
    if isinstance(observation_date, datetime):
        observation_date = _shanghai_time(observation_date).date()
    days = (observation_date - _shanghai_time(last_paid_at).date()).days
    return _STAGES[sum(days >= point for point in thresholds(gid, config))]


def is_repeat(first_paid_at, paid_at):
    """Check the elapsed time between two distinct, valid orders."""
    first = _shanghai_time(first_paid_at).astimezone(timezone.utc)
    paid = _shanghai_time(paid_at).astimezone(timezone.utc)
    return paid - first >= timedelta(hours=24)


def _amount(value):
    if type(value) not in (str, int, float, Decimal):
        raise ValueError("invalid USD amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("invalid USD amount") from error
    if not amount.is_finite():
        raise ValueError("invalid USD amount")
    return amount


def tier(cumulative_usd, gid, config):
    """Classify known cumulative USD spend for a game."""
    spend = _amount(cumulative_usd)
    limits = config["tiers"].get(str(gid), _DEFAULT_TIER)
    if spend >= _amount(limits["ultra"]):
        return "ultra"
    if spend >= _amount(limits["high"]):
        return "high"
    return None


def _default_config():
    return {
        "version": _DEFAULT_VERSION,
        "stages": {gid: list(points) for gid, points in _GAME_THRESHOLDS.items()},
        "tiers": {},
    }


def _check_gid(gid):
    if not isinstance(gid, str) or re.fullmatch(r"[1-9][0-9]*", gid) is None:
        raise ValueError(f"invalid game ID: {gid!r}")


def _validate_config(config):
    if not isinstance(config, dict) or set(config) != _CONFIG_FIELDS:
        raise ValueError("config must contain exactly version, stages, and tiers")
    if type(config["version"]) is not int or config["version"] < _DEFAULT_VERSION:
        raise ValueError("invalid config version")
    if not isinstance(config["stages"], dict) or not isinstance(config["tiers"], dict):
        raise ValueError("stages and tiers must be objects keyed by game ID")

    for gid, points in config["stages"].items():
        _check_gid(gid)
        if (
            not isinstance(points, (list, tuple))
            or len(points) != 3
            or any(type(point) is not int for point in points)
            or not 0 < points[0] < points[1] < points[2]
        ):
            raise ValueError(f"invalid stage thresholds for game {gid}")

    for gid, limits in config["tiers"].items():
        _check_gid(gid)
        if not isinstance(limits, dict) or set(limits) != {"ultra", "high"}:
            raise ValueError(f"tier for game {gid} must contain exactly ultra and high")
        if not 0 <= _amount(limits["high"]) < _amount(limits["ultra"]):
            raise ValueError(f"invalid tier thresholds for game {gid}")


def _unique_object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate field in config")
    return obj


def _decode_config(payload):
    # Keep fractional JSON numbers exact and the loaded configuration JSON-serializable.
    config = json.loads(payload.decode("utf-8"), parse_float=str, object_pairs_hook=_unique_object)
    _validate_config(config)
    return config


def load_config(path):
    """Read one versioned configuration or use built-in defaults for a missing file."""
    try:
        payload = Path(path).read_bytes()
    except FileNotFoundError:
        return _default_config(), _DEFAULT_VERSION, "default"
    config = _decode_config(payload)
    return config, config["version"], "file"


class ConfigVersionConflict(ValueError):
    """The active configuration changed since the caller read it."""


def _lock_writer(stream):
    # Lock a stable file because replacing the configuration changes its inode.
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _sync_directory(directory):
    if os.name != "nt":
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_write(path, payload):
    temporary = NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    temp_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, path)
        _sync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)


def _archive(path, version, payload):
    history = path.parent / "history"
    history.mkdir(exist_ok=True)
    target = history / f"{version}.json"
    try:
        archived = target.read_bytes()
    except FileNotFoundError:
        _atomic_write(target, payload)
    else:
        if archived != payload:
            raise ValueError(f"history already contains different data for version {version}")
    # Persist the history directory entry before replacing the live configuration.
    _sync_directory(path.parent)


def write_config(path, config, expected_version):
    """Atomically replace the configuration after comparing its current version."""
    _validate_config(config)
    if type(expected_version) is not int or expected_version < _DEFAULT_VERSION:
        raise ValueError("invalid expected config version")
    if config["version"] != expected_version + 1:
        raise ValueError("new config version must equal expected_version + 1")

    payload = (json.dumps(config, sort_keys=True, allow_nan=False, default=str) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f".{path.name}.lock").open("a+b") as lock:
        _lock_writer(lock)
        try:
            previous = path.read_bytes()
        except FileNotFoundError:
            previous = None
        current_version = _DEFAULT_VERSION if previous is None else _decode_config(previous)["version"]
        if current_version != expected_version:
            raise ConfigVersionConflict(f"expected config version {expected_version}, found {current_version}")
        if previous is not None:
            _archive(path, current_version, previous)
        _atomic_write(path, payload)
