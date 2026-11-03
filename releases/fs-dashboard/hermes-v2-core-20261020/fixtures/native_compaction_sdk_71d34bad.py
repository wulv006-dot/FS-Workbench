"""Exact pinned SDK compaction assembly + post-commit event function bodies.
Source: NousResearch/hermes-agent@71d34bad1045610252eda02ee79549436896e784.
This is a direct function fixture, not a full SDK, SessionDB or compression LLM test.
"""
from __future__ import annotations
import logging
from types import SimpleNamespace
from contextlib import nullcontext

HISTORICAL_TASK_HEADING = "## Historical Task Snapshot"

SUMMARY_PREFIX = (
    # Jul 2026 (#65848 class): identical to the pre-#69619 prefix except it lacked the explicit "tools
    # remain fully active" clause — the strong REFERENCE ONLY framing bled into general tool-use suppression
    # (observed: 7 consecutive narration-only turns immediately after a compression event on a production
    # deployment).
    # Carveout era (#41607/#38364/#42812): "consistent → use as background" licensed stale-task resumption
    # on topic overlap.
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. "
    "Respond ONLY to the latest user message that appears AFTER this "
    "summary — that message is the single source of truth for what to do "
    "right now. "
    "If no user message appears AFTER this summary, do nothing: do not "
    "resume, wrap up, or continue work from "
    f"'{HISTORICAL_TASK_HEADING}' or any other section, do not call tools, "
    "and wait for a new user message. This handoff must never become the "
    "active turn by itself. (Exception: if tool results or your own "
    "tool calls appear after this summary, you are mid-way through an "
    "in-flight exchange — continue that exchange normally.) "
    "Topic overlap with the summary does NOT mean you should resume its "
    "task: even on similar topics, the latest user message WINS. Treat ONLY "
    "the latest message as the active task and discard stale items from "
    f"'{HISTORICAL_TASK_HEADING}' entirely — do not 'wrap up' or "
    "'finish' work described there unless the latest message explicitly "
    "asks for it. "
    "Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll "
    "back', 'just verify', 'don't do that anymore', 'never mind', a new "
    "topic) must immediately end any in-flight work described in the "
    "summary; do not re-surface it in later turns. "
    "IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system "
    "prompt is ALWAYS authoritative and active — never ignore or deprioritize "
    "memory content due to this compaction note. "
    "None of the above restricts HOW you work: your tools remain fully "
    "active — keep calling them normally for the active task (edit files, "
    "run commands, search) instead of merely narrating what you would do. "
    "The current session state (files, config, etc.) may reflect work "
    "described here — avoid repeating it:"
)

LEGACY_SUMMARY_PREFIX = "[CONTEXT SUMMARY]:"

COMPRESSED_SUMMARY_METADATA_KEY = "_compressed_summary"

COMPRESSED_SUMMARY_HAS_USER_TURN_KEY = "_compressed_summary_has_user_turn"

_DB_PERSISTED_MARKER = "_db_persisted"

_COMPACTION_TAIL_MARKER = "_compaction_tail"

def _fresh_compaction_message_copy(msg: dict[str, Any]) -> dict[str, Any]:
    """Copy a message for compaction assembly without persistence markers (``_strip_persistence_markers`` is authoritative)."""
    fresh = msg.copy()
    fresh.pop(_DB_PERSISTED_MARKER, None)
    return fresh

def _template_visible_role(message: Any) -> Optional[str]:
    """Role as counted by strict chat-template alternation checks.
    Mistral-family templates exempt ``tool`` rows and assistant rows with ``tool_calls`` from
    alternation. Returns ``None`` for messages the check skips."""
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    return None if role == "tool" or (role == "assistant" and message.get("tool_calls")) else role

def _last_template_visible_role(messages: list[dict[str, Any]]) -> Optional[str]:
    """Last role a strict alternation template would count in *messages*.

    ``None`` when every row is template-exempt (tool flow only).
    """
    return next(
        (
            role
            for role in (_template_visible_role(m) for m in reversed(messages))
            if role is not None
        ),
        None,
    )

_SUMMARY_END_MARKER = "--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---"

_MERGED_PRIOR_CONTEXT_HEADER = "[PRIOR CONTEXT — for reference only; not a new message]"

_MERGED_SUMMARY_DELIMITER = "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]"

_HISTORICAL_SUMMARY_PREFIXES = (
    # Pre-#80622: lacked the "no user message after summary => do nothing" clause.
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff "
    "from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer "
    "questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the "
    "latest user message that appears AFTER this summary — that message is the single source of truth for what to do "
    "right now. Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the "
    "latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '## "
    "Historical Task Snapshot' entirely — do not 'wrap up' or 'finish' work described there unless the latest "
    "message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just "
    "verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described "
    "in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in "
    "the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this "
    "compaction note. None of the above restricts HOW you work: your tools remain fully active — keep calling them "
    "normally for the active task (edit files, run commands, search) instead of merely narrating what you would do. "
    "The current session state (files, config, etc.) may reflect work described here — avoid repeating it:",
    # Pre-#69619: discard clause still named all four historical headings.
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff "
    "from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer "
    "questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the "
    "latest user message that appears AFTER this summary — that message is the single source of truth for what to do "
    "right now. Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the "
    "latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '## "
    "Historical Task Snapshot' / '## Historical In-Progress State' / '## Historical Pending User Asks' / '## "
    "Historical Remaining Work' entirely — do not 'wrap up' or 'finish' work described there unless the latest "
    "message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just "
    "verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described "
    "in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in "
    "the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this "
    "compaction note. None of the above restricts HOW you work: your tools remain fully active — keep calling them "
    "normally for the active task (edit files, run commands, search) instead of merely narrating what you would do. "
    "The current session state (files, config, etc.) may reflect work described here — avoid repeating it:",
    # Lacked the "tools remain fully active" clause (suppressed tool use).
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff "
    "from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer "
    "questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the "
    "latest user message that appears AFTER this summary — that message is the single source of truth for what to do "
    "right now. Topic overlap with the summary does NOT mean you should resume its task: even on similar topics, the "
    "latest user message WINS. Treat ONLY the latest message as the active task and discard stale items from '## "
    "Historical Task Snapshot' / '## Historical In-Progress State' / '## Historical Pending User Asks' / '## "
    "Historical Remaining Work' entirely — do not 'wrap up' or 'finish' work described there unless the latest "
    "message explicitly asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', 'roll back', 'just "
    "verify', 'don't do that anymore', 'never mind', a new topic) must immediately end any in-flight work described "
    "in the summary; do not re-surface it in later turns. IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in "
    "the system prompt is ALWAYS authoritative and active — never ignore or deprioritize memory content due to this "
    "compaction note. The current session state (files, config, etc.) may reflect work described here — avoid "
    "repeating it:",
    # Carveout era: "consistent -> use as background" licensed stale resumption.
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a handoff "
    "from a previous context window — treat it as background reference, NOT as active instructions. Do NOT answer "
    "questions or fulfill requests mentioned in this summary; they were already addressed. Respond ONLY to the "
    "latest user message that appears AFTER this summary — that message is the single source of truth for what to do "
    "right now. If the latest user message is consistent with the '## Active Task' section, you may use the summary "
    "as background. If the latest user message contradicts, supersedes, changes topic from, or in any way diverges "
    "from '## Active Task' / '## In Progress' / '## Pending User Asks' / '## Remaining Work', the latest message "
    "WINS — discard those stale items entirely and do not 'wrap up the old task first'. Reverse signals in the "
    "latest message (e.g. 'stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', 'never mind', a new "
    "topic) must immediately end any in-flight work described in the summary; do not re-surface it in later turns. "
    "IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative and active "
    "— never ignore or deprioritize memory content due to this compaction note. The current session state (files, "
    "config, etc.) may reflect work described here — avoid repeating it:",
    # Pre-#35344: contained the self-contradicting "resume exactly" directive.
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. This is a "
    "handoff from a previous context window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; they were already addressed. "
    "Your current task is identified in the '## Active Task' section of the summary — resume exactly from "
    "there. Respond ONLY to the latest user message that appears AFTER this summary. The current session "
    "state (files, config, etc.) may reflect work described here — avoid repeating it:",
)

def _part_text(item: Any) -> Optional[str]:
    """Text of a content part: the string itself, a dict's ``text``, else None."""
    return item if isinstance(item, str) else item.get("text") if isinstance(item, dict) else None

def _with_part_text(item: Any, text: str) -> Any:
    """Copy of a content part carrying ``text`` (string parts become the text itself)."""
    return {**item, "text": text} if isinstance(item, dict) else text

def _content_text_for_contains(content: Any) -> str:
    """Return a best-effort text view of message content (for substring checks only)."""
    if isinstance(content, list):
        return "\n".join(t for t in map(_part_text, content) if isinstance(t, str) and t)
    return "" if content is None else content if isinstance(content, str) else str(content)

def _append_text_to_content(content: Any, text: str, *, prepend: bool = False) -> Any:
    """Append or prepend plain text to message content (string or multimodal list)."""
    if content is None:
        return text
    if isinstance(content, list):
        text_block = {"type": "text", "text": text}
        return [text_block, *content] if prepend else [*content, text_block]
    rendered = content if isinstance(content, str) else str(content)
    return text + rendered if prepend else rendered + text

def drop_stale_api_content(msg: dict[str, Any]) -> None:
    """Drop the ``api_content`` sidecar from a message whose content was rewritten
    (replaying it would resend what the rewrite removed; cost is one cache miss)."""
    msg.pop("api_content", None)

class SDKAssembler:
    @staticmethod
    def _starts_with_summary_prefix(text: str) -> bool:
        """Return True if *text* begins with any known handoff prefix."""
        return text.startswith((SUMMARY_PREFIX, LEGACY_SUMMARY_PREFIX, *_HISTORICAL_SUMMARY_PREFIXES))
    @classmethod
    def classify_summary_content(cls, content: Any) -> Optional[str]:
        """Classify how *content* relates to a compaction summary.
        Returns ``"standalone"`` (whole message is a handoff), ``"merged"`` (preserved content +
        delimiter + summary body), or None."""
        text = _content_text_for_contains(content).lstrip()
        # Merged summaries carry the handoff prefix after the delimiter; detect it there too.
        if _MERGED_SUMMARY_DELIMITER in text:
            after = text.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
            return "merged" if cls._starts_with_summary_prefix(after) else None
        return "standalone" if cls._starts_with_summary_prefix(text) else None
    @classmethod
    def _is_context_summary_content(cls, content: Any) -> bool:
        return cls.classify_summary_content(content) is not None
    @staticmethod
    def _has_compressed_summary_metadata(message: Any) -> bool:
        """Return True if *message* carries the in-process compressed-summary flag."""
        return isinstance(message, dict) and bool(message.get(COMPRESSED_SUMMARY_METADATA_KEY))
    @classmethod
    def _is_context_summary_message(cls, message: Any) -> bool:
        """Return True for summary handoff messages by metadata or content."""
        if not isinstance(message, dict):
            return False
        return cls._has_compressed_summary_metadata(message) or cls._is_context_summary_content(message.get("content"))
    @classmethod
    def _strip_context_summary_handoff_message(cls, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Drop stale handoff data while preserving merged prior-tail content.
        Returns a copy for non-handoff rows, the unwrapped prior-tail content for merged handoffs
        (delimiter form, or legacy end-marker form), and ``None`` for standalone ones."""
        if not isinstance(message, dict):
            return message
        if not cls._is_context_summary_message(message):
            return message.copy()
        content = message.get("content")

        def _unwrapped(new_content: Any) -> dict[str, Any]:
            unwrapped = {**message, "content": new_content}
            unwrapped.pop(COMPRESSED_SUMMARY_METADATA_KEY, None)
            return unwrapped

        if isinstance(content, str):
            if _MERGED_SUMMARY_DELIMITER in content:
                prior = content.split(_MERGED_SUMMARY_DELIMITER, 1)[0].strip()
                if prior.startswith(_MERGED_PRIOR_CONTEXT_HEADER):
                    prior = prior[len(_MERGED_PRIOR_CONTEXT_HEADER):].lstrip()
            elif _SUMMARY_END_MARKER in content:
                prior = content.split(_SUMMARY_END_MARKER, 1)[1].lstrip()
            else:
                prior = ""
            return _unwrapped(prior) if prior else None
        if isinstance(content, list):
            prior_blocks: list[Any] = []
            found_delimiter = False
            for item in content:
                text = _part_text(item)
                if isinstance(text, str) and _MERGED_SUMMARY_DELIMITER in text:
                    before = text.split(_MERGED_SUMMARY_DELIMITER, 1)[0]
                    if before.strip():
                        prior_blocks.append(_with_part_text(item, before))
                    found_delimiter = True
                    break
                prior_blocks.append(item.copy() if isinstance(item, dict) else item)
            if not found_delimiter:
                # Legacy end-marker form: live content follows the marker inside/after one part.
                for index, item in enumerate(content):
                    text = _part_text(item)
                    if isinstance(text, str) and _SUMMARY_END_MARKER in text:
                        remainder = text.split(_SUMMARY_END_MARKER, 1)[1].lstrip()
                        legacy_blocks = [_with_part_text(item, remainder)] if remainder else []
                        legacy_blocks += [later.copy() if isinstance(later, dict) else later for later in content[index + 1:]]
                        return _unwrapped(legacy_blocks) if legacy_blocks else None
                return None

            # Strip the PRIOR CONTEXT header from the first block that carries it.
            for index, item in enumerate(prior_blocks):
                text = _part_text(item)
                if isinstance(text, str) and text.lstrip().startswith(_MERGED_PRIOR_CONTEXT_HEADER):
                    leading = text.lstrip()[len(_MERGED_PRIOR_CONTEXT_HEADER):].lstrip()
                    if leading:
                        prior_blocks[index] = _with_part_text(item, leading)
                    else:
                        prior_blocks.pop(index)
                    break
            return _unwrapped(prior_blocks) if prior_blocks else None
        return None
    _COMPRESSION_NOTE = "[Note: Some earlier conversation turns have been compacted into a handoff summary to preserve context space. The current session state may still reflect earlier work, so build on that summary and state rather than re-doing work. Your persistent memory (MEMORY.md, USER.md) remains fully authoritative regardless of compaction.]"
    def _assemble_head(self, messages: list[dict[str, Any]], compress_start: int) -> list[dict[str, Any]]:
        """Protected head with the compaction note on the system prompt and stale handoffs stripped."""
        compressed = []
        for i in range(compress_start):
            # Head handoff already lives in _previous_summary: strip it (standalone dropped, merged
            # keeps prior-tail text). Merged rows hold real user text — never blanket-skip.
            msg = _fresh_compaction_message_copy(messages[i])
            if i == 0 and msg.get("role") == "system":
                existing = msg.get("content")
                if self._COMPRESSION_NOTE not in _content_text_for_contains(existing):
                    sep = "\n\n" if isinstance(existing, str) and existing else ""
                    msg["content"] = _append_text_to_content(existing, sep + self._COMPRESSION_NOTE)
            stripped = self._strip_context_summary_handoff_message(msg)
            if stripped is not None:
                compressed.append(stripped)
        return compressed
    def _assemble_tail(
        self, messages: list[dict[str, Any]], compress_end: int, tail_start: int, summary_indices: set,
    ) -> list[dict[str, Any]]:
        """Protected tail with already-folded handoff rows dropped and merged handoffs unwrapped."""
        tail_messages: list[dict[str, Any]] = []
        # Start at tail_start, not compress_end: the rehydration scan may have advanced it (#57835).
        for i in range(max(compress_end, tail_start), len(messages)):
            if i in summary_indices and i >= tail_start:
                continue  # already folded into _previous_summary; don't re-emit
            stripped = self._strip_context_summary_handoff_message(_fresh_compaction_message_copy(messages[i]))
            if stripped is not None:
                tail_messages.append(stripped)
        return tail_messages
    @staticmethod
    def _summary_placement(
        compressed: list[dict[str, Any]], tail_messages: list[dict[str, Any]], compress_start: int,
    ) -> tuple[str, bool, bool, Optional[int]]:
        """Pick the summary row's role so template-visible alternation holds.
        Returns ``(summary_role, merge_into_tail, force_user_leading, first_tail_visible_idx)``. Roles
        read the assembled (post-strip) head/tail and are TEMPLATE-VISIBLE: Mistral-strict templates
        skip tool rows for alternation, so alternate against what the template counts."""
        last_head_role: Optional[str] = "user"
        if compressed:
            # None = all-exempt head: the summary opens the visible sequence and must be "user".
            last_head_role = _last_template_visible_role(compressed)
        first_tail_visible_idx, first_tail_role = next(
            ((idx, role) for idx, role in enumerate(map(_template_visible_role, tail_messages)) if role is not None),
            (None, None),
        )
        # System-only head: the summary is the first visible message and Anthropic requires role=user
        # (#52160). Zero-user-turn guard (#58753): if no user row with non-empty TEXT survives, the
        # summary must be role="user" or OpenAI-compatible backends reject. Image-only rows don't count.
        force_user_leading = compress_start == 0 or last_head_role == "system" or not any(
            m.get("role") == "user" and bool(_content_text_for_contains(m.get("content")).strip())
            for m in (*compressed, *tail_messages)
        )
        # Alternate against head first, then tail; None (all-exempt head) means "user".
        summary_role = "user" if last_head_role in {None, "assistant", "tool"} or force_user_leading else "assistant"
        merge_into_tail = False
        # Flip on a tail collision only if that doesn't collide with the head. All-exempt head pins "user";
        # flipping would open the visible sequence with "assistant". Neither alternates: merge into the first tail row.
        if first_tail_role is not None and summary_role == first_tail_role:
            flipped = "assistant" if summary_role == "user" else "user"
            if flipped != last_head_role and last_head_role is not None and not force_user_leading:
                summary_role = flipped
            else:
                merge_into_tail = bool(tail_messages)
        return summary_role, merge_into_tail, force_user_leading, first_tail_visible_idx
    def _merge_summary_into_tail_row(
        self, msg: dict[str, Any], summary: str, summary_role: str, force_user_leading: bool,
    ) -> None:
        """Fold the summary into a carried tail row (in place) when no standalone role alternates."""
        old_content = msg.get("content", "")
        if force_user_leading and summary_role == "user":
            # Anthropic/Bedrock: summary must lead the first visible message; the real request
            # follows the end marker.
            msg["content"] = _append_text_to_content(old_content, summary + "\n\n" + _SUMMARY_END_MARKER + "\n\n", prepend=True)
        else:
            # Old tail content is kept as delimited reference BEFORE the summary; the end marker goes last.
            suffix = "\n\n" + _MERGED_SUMMARY_DELIMITER + "\n\n" + summary + "\n\n" + _SUMMARY_END_MARKER
            msg["content"] = _append_text_to_content(
                _append_text_to_content(old_content, suffix, prepend=False),
                _MERGED_PRIOR_CONTEXT_HEADER + "\n", prepend=True,
            )
        # Frontends use this to detect a summary-prefixed message.
        msg[COMPRESSED_SUMMARY_METADATA_KEY], msg[COMPRESSED_SUMMARY_HAS_USER_TURN_KEY] = True, bool(self._summary_has_user_turn)
        # Rewritten content: drop the stale api_content sidecar so replay can't resend pre-merge bytes.
        drop_stale_api_content(msg)
    def _assemble_compressed(
        self, messages: list[dict[str, Any]], compress_start: int, compress_end: int, scan: _HandoffScan, summary: str,
    ) -> list[dict[str, Any]]:
        """Head + summary + tail from the pruned copy: its tool-result demotions are what let an oversized
        head/tail compress at all (#61932); tool-call arguments are never rewritten by pruning."""
        compressed = self._assemble_head(messages, compress_start)
        tail_messages = self._assemble_tail(messages, compress_end, scan.tail_start, scan.summary_indices)
        summary_role, merge_into_tail, force_user_leading, first_tail_visible_idx = (
            self._summary_placement(compressed, tail_messages, compress_start)
        )
        if not merge_into_tail:
            # End marker stops weak models treating the quoted summary as fresh input (#11475) or
            # regurgitating it (#33256).
            compressed.append({
                "role": summary_role, "content": summary + "\n\n" + _SUMMARY_END_MARKER,
                COMPRESSED_SUMMARY_METADATA_KEY: True,
                COMPRESSED_SUMMARY_HAS_USER_TURN_KEY: bool(self._summary_has_user_turn),
            })
        # Default carrier is tail[0]: an exempt row absorbs the summary invisibly. The forced repair
        # path needs a non-empty role=user row, so it targets the template-visible row.
        merge_target_idx = first_tail_visible_idx if force_user_leading and first_tail_visible_idx is not None else 0
        for tail_idx, msg in enumerate(tail_messages):
            # Tag carried-forward tail rows so archive_and_compact treats their originals as
            # superseded duplicates (#86366).
            if isinstance(msg, dict):
                msg[_COMPACTION_TAIL_MARKER] = True
            if merge_into_tail and tail_idx == merge_target_idx:
                self._merge_summary_into_tail_row(msg, summary, summary_role, force_user_leading)
            compressed.append(msg)
        return compressed

# Side effects outside the SDK event are explicit fixture dependencies.
logger=logging.getLogger(__name__)
_swallow=lambda *args,**kwargs:nullcontext()
_notify_context_engine_compression_complete=lambda *args,**kwargs:None
_queue_context_engine_compression_notification=lambda *args,**kwargs:None
set_usage_anchor=lambda *args,**kwargs:None
_reset_read_dedup_caches=lambda *args,**kwargs:None
estimate_request_tokens_rough=lambda messages,**kwargs:len(repr(messages))

def _finish_compaction_boundary(
    agent: Any, compressed: list, *, new_system_prompt: str, old_session_id: Optional[str], in_place: bool,
    compacted_in_place: bool, session_commit_succeeded: bool, defer_context_engine_notification: bool,
    compression_made_progress: bool, compression_used_fallback: bool, compression_feasibility_skip: bool,
    task_id: str,
) -> int:
    """Post-commit bookkeeping: notify engines/providers/hooks, re-arm usage tracking.
    Returns the rough post-compression token estimate (diagnostics only)."""
    # old_session_id is bound only on rotation; _boundary_parent is the id the
    # boundary notifications attribute prior state to (old id, or same id in-place).
    _old_sid = old_session_id
    _boundary_parent = _old_sid or agent.session_id or ""

    # The heartbeat's terminal stamp landed on the PARENT before the id re-pointed;
    # clear labels (keep last_activity_at) so the archived row isn't falsely fresh.
    if _old_sid and session_commit_succeeded:
        with _swallow("failed to clear archived compression parent's activity labels (ignored)", exc_info=True):
            _labels_db = getattr(agent, "_session_db", None)
            if callable(_clear_labels := getattr(type(_labels_db), "clear_session_activity_labels", None)):
                _clear_labels(_labels_db, _old_sid)

    # Plugin engines use boundary_reason="compression" to keep lineage/checkpoint
    # state. Fires in BOTH modes: in-place passes the same id, the boundary is real.
    if session_commit_succeeded and (bool(_old_sid) or compacted_in_place):
        notify = (
            _queue_context_engine_compression_notification
            if defer_context_engine_notification
            else _notify_context_engine_compression_complete
        )
        notify(agent, new_session_id=agent.session_id or "", old_session_id=_boundary_parent)

    # Providers refresh cached per-session state; reset=False, conversation goes on.
    # Fires in BOTH modes so buffers don't double-count dropped turns in-place.
    with _swallow('memory manager on_session_switch (compression): %s'):
        if (bool(_old_sid) or in_place) and agent._memory_manager:
            agent._memory_manager.on_session_switch(
                agent.session_id or "", parent_session_id=_boundary_parent, reset=False, reason="compression"
            )

    # Route via _emit_status so the warning reaches gateway platforms; store it on
    # _compression_warning so a late-bound status_callback can replay it.
    compressor = agent.context_compressor
    _cc = compressor.compression_count
    if _cc >= 2:
        _cc_msg = (
            f"{agent.log_prefix}⚠️  Session compressed {_cc} times — accuracy may degrade. Consider /new to start fresh."
        )
        agent._compression_warning = _cc_msg
        agent._emit_diagnostic_status(_cc_msg)

    # session:compress lets hooks ingest the old session before it's lost;
    # in_place=True tells them the same id was compacted rather than rotated.
    if getattr(agent, "event_callback", None):
        with _swallow('event_callback error on session:compress: %s'):
            agent.event_callback(
                "session:compress",
                {
                    "platform": agent.platform or "", "session_id": agent.session_id,
                    "old_session_id": _old_sid or "", "in_place": in_place,
                    "compression_count": compressor.compression_count,
                },
            )

    # Rotation-independent flag: the gateway uses it (not an id diff) to re-baseline
    # transcript handling (history_offset=0 + rewrite on the same id) in-place.
    agent._last_compression_attempt_in_place = compacted_in_place
    agent._last_compaction_in_place = compacted_in_place

    # Diagnostics only, not provider usage: schema-heavy rough estimates can stay
    # above threshold even after the next real request fits.
    _compressed_est = estimate_request_tokens_rough(
        compressed, system_prompt=new_system_prompt or "", tools=agent.tools or None
    )
    compressor.last_compression_rough_tokens = _compressed_est
    compressor.last_prompt_tokens = -1
    compressor.last_completion_tokens = 0
    compressor.awaiting_real_usage_after_compression = True
    # Transcript rewritten: invalidate the usage anchor's base snapshot explicitly
    # (its structural check would fail closed anyway); estimate until re-anchored.
    set_usage_anchor(agent, None)
    # Arm the effectiveness verdict only after a completed rewrite crosses the
    # boundary so later usage isn't charged to an attempt that changed nothing.
    if compression_made_progress:
        record_boundary = getattr(type(compressor), "record_completed_compaction", None)
        if callable(record_boundary):
            record_boundary(
                compressor, used_fallback=compression_used_fallback, feasibility_skip=compression_feasibility_skip
            )
        else:
            compressor._verify_compaction_cleared_threshold = True
    _reset_read_dedup_caches(task_id, session_id=agent.session_id or "")
    return _compressed_est
