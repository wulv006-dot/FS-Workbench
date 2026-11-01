"""Frozen inputs for the real FS materials runtime, with no I/O or grants.

A supplies authenticated binding, selected metadata and explicit operation, then
owns byte/expiry/goal/task/lease checks on every call. Hashes identify inputs;
they do not authorize them or verify a runtime receipt. No FC spec is fabricated.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re

from b1_model_routing import handoff as checked_handoff
from conversation_file_tools import NAMES, WIRE_NAMES, file_prompt, validate as validate_tool

KIND = "conversation_materials_v1"
SCOPE = "material_execution_files"
BINDING = {"owner", "cid", "goal_id", "scope_ref", "request_id", "intent_sha256"}
FILE_FIELDS = {"file_id", "sha256", "parent_id", "version", "size", "expires_at"}
SYSTEM_PROMPT = (
    "执行用户在FS正常入口明确授权的本次材料读或确定性修订。"
    "仅使用冻结的最小handoff和当前选择，不加载历史会话、经营数据或其它目标。"
    "先回答当前问题，明确事实、覆盖与缺项，按需读取必要页，不虚构业务时点。"
    + file_prompt(scope=SCOPE)
)
EXECUTION_FIELDS = {"kind", "binding", "handoff", "selection_revision", "manifest", "operation",
                    "deadline_at", "snapshot_id", "template_version", "knowledge_version",
                    "system_prompt", "input", "payload_sha256", "fact_version"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value, limit=256):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("material_identity")
    return value


def _hex(value, size):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{%d}" % size, value):
        raise ValueError("material_hash_or_file_id")
    return value


def _moment(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("material_aware_time_required")
    return value.astimezone(timezone.utc)


def _operation(operation, files, request_id):
    if not isinstance(operation, dict):
        raise ValueError("material_operation")
    if operation == {"mode": "read"}:
        return {"mode": "read"}
    if set(operation) != {"mode", "file_id", "edits", "format"} or operation["mode"] != "revise":
        raise ValueError("material_operation")
    if operation["file_id"] not in {f["file_id"] for f in files}:
        raise PermissionError("material_revision_input_not_selected")
    # A's deterministic revision namespace is distinct from runtime POST identity.
    revision_id = "mr_" + _sha({"request_id": request_id, "operation": operation})
    validate_tool(NAMES[2], {k: deepcopy(operation[k]) for k in ("file_id", "edits", "format")}
                  | {"request_id": revision_id})
    if not operation["edits"]:
        raise ValueError("material_explicit_edits_required")
    return dict(deepcopy(operation), revision_request_id=revision_id)


def _manifest(files, current):
    if not isinstance(files, list) or not 1 <= len(files) <= 10:
        raise ValueError("material_selection")
    selected, seen = [], set()
    for item in files:
        if not isinstance(item, dict) or not FILE_FIELDS <= set(item):
            raise ValueError("material_metadata")
        fid = _hex(item["file_id"], 32)
        if fid in seen:
            raise ValueError("material_duplicate_input")
        seen.add(fid)
        _hex(item["sha256"], 64)
        if item["parent_id"] is not None:
            _hex(item["parent_id"], 32)
        if (type(item["version"]) is not int or item["version"] < 1
                or type(item["size"]) is not int or item["size"] < 0
                or type(item["expires_at"]) not in (int, float)
                or not math.isfinite(item["expires_at"])):
            raise ValueError("material_metadata")
        if ((current is not None and item["expires_at"] <= current.timestamp())
                or item.get("status", "available") != "available"):
            raise PermissionError("material_input_unavailable")
        selected.append({k: deepcopy(item[k]) for k in FILE_FIELDS})
    selected.sort(key=lambda f: f["file_id"])
    return {"version": "conversation_material_manifest_v1", "files": selected}


def _facts(*, owner, cid, scope_ref, selection_revision, manifest, operation):
    for value in (owner, cid):
        _text(value)
    _text(scope_ref, 2048)
    if type(selection_revision) is not int or selection_revision < 1:
        raise ValueError("material_selection_revision")
    # The operation's revision ID is execution bookkeeping, not a new fact.
    semantic = {k: deepcopy(v) for k, v in operation.items() if k != "revision_request_id"}
    return "materials-facts-" + _sha(dict(kind=KIND, owner=owner, cid=cid, scope_ref=scope_ref,
        selection_revision=selection_revision, manifest=manifest, operation=semantic,
        template_version="materials-template-" + _sha(SYSTEM_PROMPT)))


def prepare_materials(*, owner, cid, scope_ref, selection_revision, files, operation, now):
    """Version server-verified material facts BEFORE GoalHost.step creates work.

No request, CAS, handoff or fake binding is needed to determine the fact version.
This is selected material metadata/operation identity, never a business cutoff.
"""
    manifest = _manifest(files, _moment(now))
    checked = _operation(operation, manifest["files"], "validation-only")
    return dict(manifest=manifest, snapshot_id="materials-" + _sha(manifest),
        fact_version=_facts(owner=owner, cid=cid, scope_ref=scope_ref, selection_revision=selection_revision,
                            manifest=manifest, operation=checked))


def _freeze_execution(*, binding, handoff, selection_revision, files, operation, deadline_at, now):
    """Freeze A-verified inputs; binding digest and complete payload stay distinct."""
    if not isinstance(binding, dict) or set(binding) != BINDING:
        raise ValueError("material_binding")
    for key in BINDING - {"intent_sha256"}:
        _text(binding[key], 2048 if key == "scope_ref" else 256)
    _hex(binding["intent_sha256"], 64)
    if not isinstance(handoff, dict) or set(handoff) != {
            "task_id", "revision", "goal", "constraints", "evidence", "completed_actions", "next_step"}:
        raise ValueError("material_handoff")
    minimal = checked_handoff(**handoff)
    if minimal["task_id"] != binding["request_id"]:
        raise ValueError("material_handoff_request_mismatch")
    current, deadline = _moment(now) if now is not None else None, _moment(deadline_at)
    if current is not None and deadline <= current:
        raise PermissionError("material_deadline_expired")
    manifest = _manifest(files, current)
    permitted = _operation(operation, manifest["files"], binding["request_id"])
    fact_version = _facts(owner=binding["owner"], cid=binding["cid"], scope_ref=binding["scope_ref"],
        selection_revision=selection_revision, manifest=manifest, operation=permitted)
    user_input = _json({"handoff": minimal, "operation": permitted,
                        "manifest_ref": "materials-" + _sha(manifest)})
    if len((SYSTEM_PROMPT + user_input).encode("utf-8")) > 32768:
        raise ValueError("material_context_too_large")
    result = dict(kind=KIND, binding=deepcopy(binding), handoff=minimal,
                  selection_revision=selection_revision, manifest=manifest, operation=permitted,
                  deadline_at=deadline.isoformat(), snapshot_id="materials-" + _sha(manifest),
                  template_version="materials-template-" + _sha(SYSTEM_PROMPT),
                  knowledge_version="materials-context-" + _sha({"system_prompt": SYSTEM_PROMPT, "input": user_input}),
                  system_prompt=SYSTEM_PROMPT, input=user_input, fact_version=fact_version)
    return dict(result, payload_sha256=_sha(result))


def freeze_execution(*, binding, handoff, selection_revision, files, operation, deadline_at, now):
    """Build a live intent from A-verified server inputs; never grants access."""
    _moment(now)
    return _freeze_execution(binding=binding, handoff=handoff, selection_revision=selection_revision,
        files=files, operation=operation, deadline_at=deadline_at, now=now)


def validate_execution(execution, *, now=None):
    """Rebuild a persisted frozen payload, rejecting drift; returns a deep copy.

    Does not prove a grant, disk bytes, task status or receipt. A must check those.
    now=None checks integrity ONLY, so expired tasks can still be reconciled or
    stopped. Dispatch/tools must supply the actual current time. The operation
    guard requires it; an expired deadline/file then fails before any tool.
"""
    if not isinstance(execution, dict) or set(execution) != EXECUTION_FIELDS:
        raise ValueError("material_execution_fields")
    if not isinstance(execution["manifest"], dict) or set(execution["manifest"]) != {"version", "files"}:
        raise ValueError("material_manifest")
    operation = deepcopy(execution["operation"])
    if not isinstance(operation, dict):
        raise ValueError("material_operation")
    if operation.get("mode") == "revise":
        operation.pop("revision_request_id", None)
    rebuilt = _freeze_execution(binding=execution["binding"], handoff=execution["handoff"],
        selection_revision=execution["selection_revision"], files=execution["manifest"]["files"],
        operation=operation, deadline_at=execution["deadline_at"], now=now)
    if _json(rebuilt) != _json(execution):
        raise ValueError("material_execution_changed")
    return rebuilt


def operation_guard(execution, name, arguments, *, now):
    """Restrict the model call to the frozen operation; literal True on success.

A still checks selected/generated membership, bytes, owner, goal and task/lease.
This function never retries an unknown revision or infers task completion.
"""
    _moment(now)
    fixed = validate_execution(execution, now=now)
    if name not in NAMES:
        raise PermissionError("material_tool_denied")
    validate_tool(name, arguments)
    if name == NAMES[2]:
        allowed = fixed["operation"]
        expected = {k: deepcopy(allowed[k]) for k in ("file_id", "edits", "format")} if allowed["mode"] == "revise" else None
        if expected is None:
            raise PermissionError("material_read_only")
        expected["request_id"] = allowed["revision_request_id"]
        if _json(expected) != _json(arguments):
            raise PermissionError("material_revision_not_authorized")
    return True


def _proof_identity(execution, session_id, run_id):
    fixed = validate_execution(execution)  # Reconciliation may occur after expiry.
    _text(session_id)
    if not isinstance(run_id, str) or not re.fullmatch(r"run_[a-f0-9]{32}", run_id):
        raise ValueError("material_run_identity")
    return dict(version="materials_effective_context_v1", kind=KIND, session_id=session_id, run_id=run_id,
        payload_sha256=fixed["payload_sha256"], snapshot_id=fixed["snapshot_id"],
        template_version=fixed["template_version"], knowledge_version=fixed["knowledge_version"],
        input_sha256=hashlib.sha256(fixed["input"].encode("utf-8")).hexdigest(),
        declared_prompt_sha256=hashlib.sha256(fixed["system_prompt"].encode("utf-8")).hexdigest(),
        tool_names=sorted(WIRE_NAMES))


def build_context_proof(execution, *, session_id, run_id, actual_system_prompt, actual_input,
                        actual_tool_names, native_memory_skipped):
    """Record measurements from A's actual agent/official admission boundary.

A must supply the assembled agent prompt, actual admitted input (or input whose
full official persisted body fingerprint was verified), actual enabled tools,
    and actual skip flags (memory, context files and background loading disabled).
    Supplying expected template text is NOT runtime proof.
No text is persisted here. The authenticated A ledger binds this proof to the
real task/lease/run; this pure comparison alone cannot authenticate a worker.
"""
    fixed = validate_execution(execution)
    if (not isinstance(actual_system_prompt, str) or fixed["system_prompt"] not in actual_system_prompt
            or not isinstance(actual_input, str) or actual_input != fixed["input"] or native_memory_skipped is not True
            or not isinstance(actual_tool_names, (list, tuple))
            or len(actual_tool_names) != len(WIRE_NAMES)
            or any(not isinstance(name, str) for name in actual_tool_names)
            or sorted(actual_tool_names) != sorted(WIRE_NAMES)):
        raise PermissionError("material_effective_context_unverified")
    return dict(_proof_identity(fixed, session_id, run_id),
        system_prompt_sha256=hashlib.sha256(actual_system_prompt.encode("utf-8")).hexdigest(),
        native_memory_skipped=True, prompt_present=True, input_verified=True)


def verify_context_proof(execution, proof, *, session_id, run_id):
    """Check a proof retrieved from A's trusted task ledger, never model text.

Verifies the original frozen input/version/session/run and exact three tools.
It does not establish the provenance of the measurement or grant execution.
A's receipt verifier must first bind the actual task/lease and official record.
"""
    identity = _proof_identity(execution, session_id, run_id)
    extra = {"system_prompt_sha256", "native_memory_skipped", "prompt_present", "input_verified"}
    if (not isinstance(proof, dict) or set(proof) != set(identity) | extra
            or any(proof.get(key) != value for key, value in identity.items())
            or any(proof.get(key) is not True for key in extra - {"system_prompt_sha256"})):
        raise PermissionError("material_context_proof_changed")
    _hex(proof["system_prompt_sha256"], 64)
    return True
