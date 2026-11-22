"""Offline interpretation of SBC/Packs receipts; no production writer."""
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple


STEP_NAME = "⑧ 改价"


@dataclass(frozen=True)
class LegacyProjection:
    receipt_state: str
    pipeline_reported_ok: Optional[bool]
    reprice_reported_ok: Optional[bool]
    write_state: str = "unknown"


def _flag(value: object) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def project_legacy_receipt(receipt: Mapping) -> LegacyProjection:
    """Report what the flags actually say, not whether a price changed."""
    pipeline_ok = _flag(receipt.get("ok"))
    steps = receipt.get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return LegacyProjection("insufficient", pipeline_ok, None)
    matches = [step for step in steps if step.get("name") == STEP_NAME]
    if len(matches) != 1:
        return LegacyProjection("insufficient", pipeline_ok, None)
    reprice_ok = _flag(matches[0].get("ok"))
    if pipeline_ok is True and any(step.get("ok") is False for step in steps):
        state = "conflict"
    elif pipeline_ok is None or reprice_ok is None:
        state = "insufficient"
    else:
        state = "reported"
    return LegacyProjection(state, pipeline_ok, reprice_ok)


# Result labels are a candidate offline evidence contract, not a live API.
OUTCOMES = frozenset({"changed", "unchanged", "rejected", "not_attempted", "unknown"})


@dataclass(frozen=True)
class WriteSummary:
    state: str
    total: int
    changed: int
    unchanged: int
    rejected: int
    not_attempted: int
    unknown: int


def summarize_evidence(
    planned_rows: Iterable[str], outcomes: Iterable[Tuple[str, str]]
) -> WriteSummary:
    """Reconcile one frozen plan with its independently verified outcomes.

    A missing row outcome defaults to unknown. A row label may be changed
    only after matching the write to a read-back for the same operation.
    Unchanged means the plan required no write and the comparison was verified.
    """
    plan = set()
    for row in planned_rows:
        if not isinstance(row, str) or not row.strip() or row in plan:
            raise ValueError("invalid or duplicate plan row")
        plan.add(row)

    seen = set()
    counts: Counter = Counter()
    for row, outcome in outcomes:
        if not isinstance(row, str) or row not in plan or row in seen:
            raise ValueError("unplanned, invalid or duplicate outcome row")
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise ValueError("invalid outcome label")
        seen.add(row)
        counts[outcome] += 1

    total = len(plan)
    counts["unknown"] += total - len(seen)
    changed, unchanged = counts["changed"], counts["unchanged"]
    rejected, not_attempted, unknown = (
        counts["rejected"],
        counts["not_attempted"],
        counts["unknown"],
    )
    if changed and (rejected or not_attempted or unknown):
        state = "partial"
    elif unknown:
        state = "unknown"
    elif rejected:
        state = "rejected"
    elif not_attempted:
        state = "not_completed"
    elif changed:
        state = "confirmed"
    else:
        state = "no_op"
    return WriteSummary(state, total, changed, unchanged, rejected, not_attempted, unknown)
