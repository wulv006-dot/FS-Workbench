"""Pinned71d34bad SDK facade fixture, used only by the direct integration test.
SourceSHA3f51a7efbf94eceaaf968019fa5c2870f75cfe925a98592de5ee3f2d363851b6.
Original function/class bodies below are byte-identical source segments.
Engine/summary, portal context and SessionDB remain explicit fixture dependencies.
"""
from __future__ import annotations
import contextlib,logging,threading
logger=logging.getLogger(__name__)

class _CommitFenceRegistration:
    """One ``_compress_context`` attempt's entry on the agent's commit-fence stack.

    The fence slot is a stack, not a save/restore cell: overlapping attempts register in
    order but may complete in any order, so each attempt removes only its own entry and the
    published slot always tracks the newest *live* attempt. The stall-fallback retry swaps
    ``fence`` in place so the slot update stays tied to the owning registration.
    """

    __slots__ = ("fence",)

    def __init__(self, fence) -> None:
        self.fence = fence

def _sync_persisted_markers(target_messages, source_messages) -> None:
    """Mirror ``_DB_PERSISTED_MARKER`` stamps from the worker's snapshot onto a live list.
    Matched by scoped identity; timestamp-less repeated content is ambiguous, so every scoped match is
    stamped. Imported UNCONDITIONALLY: a silent fallback literal would split the stamping key from the flush's
    and resurrect the duplicate-row bug."""
    from agent.context_compressor import _DB_PERSISTED_MARKER
    from agent.conversation_compression import _stamp_scoped_twins
    if not isinstance(target_messages, list) or not isinstance(source_messages, list):
        return
    for source_message in source_messages:
        if isinstance(source_message, dict) and source_message.get(_DB_PERSISTED_MARKER):
            _stamp_scoped_twins(target_messages, source_message)

def _mirror_result_onto_live_lists(agent, result, messages, *, direct_path: bool) -> None:
    """Mirror persisted-marker stamps from the result list onto the live list(s)."""
    if not (isinstance(result, tuple) and result and isinstance(result[0], list)):
        return
    result_messages = result[0]
    # Direct-path callers bypass the snapshot worker but still need the post-publish mirror.
    if direct_path or result_messages is not messages:
        _sync_persisted_markers(messages, result_messages)
    session_messages = getattr(agent, "_session_messages", None)
    if isinstance(session_messages, list) and session_messages is not messages:
        # Durable-parent adoption can leave `_session_messages` on the pre-adoption list.
        _sync_persisted_markers(session_messages, result_messages)

def _rebind_caller_session_context(agent) -> None:
    """Propagate a rotated session id to the CALLER's thread/ContextVar (idempotent otherwise).
    The worker thread rotated hermes_logging's thread-local id; post-compression tools must resolve
    HERMES_SESSION_ID to the child id."""
    with contextlib.suppress(Exception):
        from hermes_logging import set_session_context
        set_session_context(agent.session_id)
    try:
        from gateway.session_context import set_current_session_id
        if agent.session_id:
            set_current_session_id(agent.session_id)
    except Exception:
        logger.debug("post-compression session ContextVar rebind failed", exc_info=True)

class CompressionFacadeMixin:
    """``_compress_context`` (see module docstring)."""

    def _compress_context(
        self, messages: list, system_message: str, *, approx_tokens: int | None = None, task_id: str = "default",
        focus_topic: str | None = None, force: bool = False, bypass_cooldown: bool = False,
        defer_context_engine_notification: bool = False, commit_fence=None, verbatim_tail: list | None = None,
        trigger: str | None = None, snapshot_is_current=None, overflow_reason: str | None = None,
    ) -> tuple:
        """Forwarder — see ``agent.conversation_compression.compress_context``.
        ``force=True`` (manual /compress) bypasses the summary-failure cooldown; ``bypass_cooldown=True``
        (provider-proven overflow recovery) runs one real attempt while the cooldown stays armed.

        ``force=True`` is passed by the manual ``/compress`` slash command so users can bypass the
        summary-failure cooldown after an auto-compress abort. Auto-compress callers use the default
        ``force=False``. See #100661.
        """
        # Per-attempt timeout signal for turn-start preflight and in-loop consumers: a stalled
        # compression must not be mistaken for a structural no-op. Thread-local + per-agent lock.
        # A stalled compression must not be mistaken for a structural no-op and followed by the oversized
        # provider request it was meant to prevent. The typed helper upgrades the simple attribute to
        # thread-local state guarded by a per-agent lock so overlapping automatic/manual entrypoints cannot
        # clobber each other's outcome (#98741).
        from agent.conversation_compression import (
            CompressionCommitFence, compress_context, reset_context_compression_timeout_outcome,
            resolve_context_compression_timeouts,
        )
        reset_context_compression_timeout_outcome(self)
        from agent.portal_tags import (
            get_affinity_scope, get_conversation_context, reset_affinity_scope, reset_conversation_context,
            set_affinity_scope, set_conversation_context,
        )
        from agent.prompt_cache_scope import declared_conversation_scope_safe
        # Out-of-turn compaction (/compact, gateway /compress, partial head compression) runs outside
        # run_conversation's ambient scope; publish the root as a fallback so the summarizer's call carries
        # the conversation tag. No-op for in-turn callers. Same for the ROUTING scope when declared.
        token = None
        if get_conversation_context() is None:
            root = self._conversation_root_id()
            if root:
                token = set_conversation_context(root)
        # Initialized alongside `token`: the turn-lease timeout/interrupt early returns leave the try block
        # before set_affinity_scope() runs, and the finally reads this name unconditionally
        # (UnboundLocalError otherwise — the 4 red cross-process lease tests on PR #97158).
        affinity_token = None
        if get_affinity_scope() is None:
            declared = declared_conversation_scope_safe(self)
            if declared:
                affinity_token = set_affinity_scope(declared)
        # Every compression has a fence; hard_interrupt() uses this exact instance to serialize cancel
        # admission against begin_commit(). Publication is serialized so overlapping automatic/manual
        # entrypoints cannot replace the fence of the attempt currently committing.
        active_fence = commit_fence or CompressionCommitFence()
        fence_registration_lock = vars(self).setdefault("_compression_commit_fence_lock", threading.RLock())
        registration = _CommitFenceRegistration(active_fence)
        try:
            with fence_registration_lock:
                fence_stack = vars(self).setdefault("_compression_commit_fence_stack", [])
                fence_stack.append(registration)
                self._active_compression_commit_fence = active_fence

            def _run(fence=None, target_messages=None, same_turn_fallback_recovery=False):
                return compress_context(
                    self, target_messages if target_messages is not None else messages, system_message,
                    approx_tokens=approx_tokens, task_id=task_id, focus_topic=focus_topic, force=force,
                    bypass_cooldown=bypass_cooldown or same_turn_fallback_recovery,
                    defer_context_engine_notification=(defer_context_engine_notification), commit_fence=fence,
                    verbatim_tail=verbatim_tail, trigger=trigger, snapshot_is_current=snapshot_is_current,
                    overflow_reason=overflow_reason,
                )

            # Callers that already own a progress-aware wait (gateway session
            # hygiene) pass commit_fence and must not be double-wrapped.
            direct_path = commit_fence is not None
            if not direct_path:
                idle_timeout, total_ceiling = resolve_context_compression_timeouts()
                direct_path = idle_timeout <= 0
            if direct_path:
                result = _run(active_fence)
            else:
                result = _run_under_progress_timeout(
                    self, _run, messages, system_message,
                    active_fence=active_fence, registration=registration,
                    fence_registration_lock=fence_registration_lock,
                    idle_timeout=idle_timeout, total_ceiling=total_ceiling, approx_tokens=approx_tokens,
                )
            _mirror_result_onto_live_lists(self, result, messages, direct_path=direct_path)
            _rebind_caller_session_context(self)
            return result
        finally:
            # Remove only THIS attempt's registration. Completion order is not registration
            # order: restoring a saved "previous" fence would resurrect a dead fence over a
            # live newer attempt (and popping the slot outright would delete that attempt's
            # fence mid-run). The slot always tracks the newest live registration.
            with fence_registration_lock:
                # Re-read rather than reuse the try-block local: an early exception before
                # the append would otherwise raise NameError here and mask the real failure.
                fence_stack = vars(self).get("_compression_commit_fence_stack") or ()
                for idx in range(len(fence_stack) - 1, -1, -1):
                    if fence_stack[idx] is registration:
                        del fence_stack[idx]
                        break
                if fence_stack:
                    self._active_compression_commit_fence = fence_stack[-1].fence
                else:
                    vars(self).pop("_active_compression_commit_fence", None)
            # Restore whatever the caller had, so a compaction never leaks its tag into the surrounding scope.
            if token is not None:
                reset_conversation_context(token)
            if affinity_token is not None:
                reset_affinity_scope(affinity_token)
