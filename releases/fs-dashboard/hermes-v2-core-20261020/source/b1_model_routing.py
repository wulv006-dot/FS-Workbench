"""Unwired B1 contracts. No HTTP, credentials, storage or tool execution.

Trusted host supplies capabilities, channel grants and injected provider clients.
Local contract verification does not establish live provider availability.
"""
from copy import deepcopy
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class Capability:
    provider: str
    model: str
    inputs: frozenset
    tasks: frozenset
    tools: bool = False
    available: bool = False
    verification: str = "local_contract_only"


def select_model(capabilities, *, task, inputs, needs_tools, allowed_providers):
    """Host-owned grants only; task class comes from the trusted planner.

No automatic fallback after dispatch: an unknown outcome keeps its identity.
"""
    if task not in {"routine", "investigation"}:
        raise ValueError("unsupported_task_class")
    candidates = [c for c in capabilities if c.available
                  and c.provider in allowed_providers and task in c.tasks
                  and set(inputs) <= c.inputs and (not needs_tools or c.tools)]
    preferred = "deepseek" if task == "routine" else "openai"
    candidates.sort(key=lambda c: (c.provider != preferred, c.provider, c.model))
    if not candidates:
        return {"status": "unavailable", "reason": "no_eligible_model"}
    c = candidates[0]
    return {"status": "selected", "provider": c.provider, "model": c.model,
            "reason": task, "verification": c.verification}


def handoff(*, task_id, revision, goal, constraints, evidence, completed_actions, next_step):
    """Minimal planner state, never raw chat, order exports or private reasoning.

Evidence references are locators, not access grants; A must authorize resolution.
"""
    if not isinstance(task_id, str) or not task_id or type(revision) is not int or revision < 1:
        raise ValueError("task_identity")
    if not all(isinstance(s, str) and s.strip() for s in (goal, next_step)):
        raise ValueError("task_summary")
    if not isinstance(constraints, list) or not all(isinstance(s, str) for s in constraints):
        raise ValueError("task_constraints")
    fields = {"ref", "source", "as_of", "coverage", "missing", "version"}
    if not isinstance(evidence, list) or any(
        not isinstance(e, dict) or set(e) != fields
        or not all(isinstance(e[k], str) and e[k] for k in fields - {"missing"})
        or not isinstance(e["missing"], list)
        or not all(isinstance(s, str) for s in e["missing"]) for e in evidence
    ):
        raise ValueError("evidence_contract")
    if not isinstance(completed_actions, list) or not all(
        isinstance(a, str) and a for a in completed_actions
    ):
        raise ValueError("action_receipt_references")
    result = dict(task_id=task_id, revision=revision, goal=goal, constraints=constraints,
                  evidence=evidence, completed_actions=completed_actions, next_step=next_step)
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 32768:
        raise ValueError("handoff_too_large")
    return deepcopy(result)


class DeepSeekAdapter:
    """Delegate unchanged to the existing direct_provider.request_model contract."""
    def __init__(self, legacy_request_model):
        self.client = legacy_request_model

    def invoke(self, request, approved_tools, deadline=None):
        # Retain native validation, thinking/effort, token budgets and receipts.
        if deadline is None:
            return self.client(deepcopy(request), deepcopy(approved_tools))
        return self.client(deepcopy(request), deepcopy(approved_tools), deadline=deadline)


class OpenAIAdapter:
    """Injected Responses subset; no SDK import or live client constructed here.

No streaming, image or tool support is advertised by this first local contract.
Tool-enabled routes must therefore exclude this adapter until separately built.
"""
    def __init__(self, create_response, model):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model_required")
        self.client, self.model = create_response, model

    def invoke(self, *, request_id, text, max_output_tokens):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_identity")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text_required")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("output_limit")
        base = dict(request_id=request_id, provider="openai", model=self.model,
                    verification="local_contract_only", cost=None)
        try:
            result = self.client(model=self.model, input=text, store=False,
                                 max_output_tokens=max_output_tokens)
        except (TimeoutError, ConnectionError, OSError):
            return dict(base, status="unknown", reason="transport_outcome_unknown",
                        retry_allowed=False)
        if not isinstance(result, dict) or result.get("model") != self.model:
            return dict(base, status="invalid_response", retry_allowed=False)
        base["provider_response_id"] = result.get("id")
        status = result.get("status")
        if status != "completed":
            outcome = "unknown" if status == "unknown" else "partial" if status == "incomplete" else "unavailable"
            return dict(base, status=outcome,
                        reason="provider_not_completed", retry_allowed=False)
        output = result.get("output")
        if not isinstance(output, list) or not isinstance(result.get("id"), str) or not result["id"]:
            return dict(base, status="invalid_response", retry_allowed=False)
        texts = []
        for item in output:
            if not isinstance(item, dict):
                return dict(base, status="invalid_response", retry_allowed=False)
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message" or item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                return dict(base, status="unavailable", reason="unsupported_output", retry_allowed=False)
            for part in item["content"]:
                if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                    return dict(base, status="unavailable", reason="unsupported_output", retry_allowed=False)
                texts.append(part["text"])
        if not texts or not any(t.strip() for t in texts):
            return dict(base, status="invalid_response", retry_allowed=False)
        usage = result.get("usage")
        counts = ("input_tokens", "output_tokens", "total_tokens")
        if usage is not None and (not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] < 0 for k in counts
        ) or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]):
            return dict(base, status="invalid_response", retry_allowed=False)
        # Output already includes provider reasoning usage. Never add it twice.
        return dict(base, status="completed", text="\n".join(texts), usage=deepcopy(usage))
