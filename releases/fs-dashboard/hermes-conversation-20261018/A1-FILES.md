# A1 first slice: conversation file backend

Business A owns `source/conversation_files.py`, `source/conversation_http.py`
and the related file tests in `tests/test_conversation_store.py`.
No shared schema, controller, migration, model adapter or production manifest changed.

## Interface

All paths below are relative to `/api/hermes/conversations/{conversation_id}`.
Existing FS authentication, authorization and same-origin POST checks apply.
The owner comes from the authenticated server context. Knowing an ID grants no access.

| Method/path | Contract |
| --- | --- |
| POST `/files` | Raw `application/octet-stream`, `Content-Length`, `X-FS-Filename` (CSV/XLSX), `X-FS-Request-ID` (8–80 ASCII letters/digits/underscore/hyphen). Returns immutable file metadata. |
| GET `/files` | Metadata including parent, version, bytes, SHA256, expiry and expired state. Also removes expired bytes within this conversation's new file namespace. |
| GET `/files/{id}` | Actual bytes as attachment, correct MIME and UTF-8 filename. Rechecks authorization, ownership, expiry and integrity. |
| GET `/files/{id}/table` | All accepted worksheets/rows/cells, `complete=true`, cell count and formula policy. No preview-only truncation. |
| POST `/files/{id}/revisions` | JSON `{edits: [{sheet: 0, row: 1, column: 1, value: "7"}], format: "xlsx", client_request_id: "revision_001"}`. Zero-based positions must exist. Format CSV/XLSX/HTML. New ID, parent and version; original bytes unchanged. |

Normal response includes `file_id`, `filename`, `mime`, `sha256`, `size`,
`parent_id`, `version`, `created_at`, `expires_at`, `expired`.
Cross-owner access returns 404; revoked function permission returns 403;
invalid input returns 422; dependency/service failure returns 503.
Retry the same request ID and input. Changed input with the same ID is rejected.

XLSX formulas are returned as expressions, never calculated. XLSX output writes
strings as text; CSV output prefixes formula-like text with an apostrophe. HTML
escapes cell content and is downloaded rather than rendered in the FS origin.
This is a bounded table revision/export tool, not an arbitrary calculation sandbox.
Dates and styles are not preserved on export; this is a values-only derivative.

## Bounds and lifecycle

Local implementation limits: 10 MiB per file, 100,000 parsed cells including blank
positions, 1,000 ZIP entries/32 MiB uncompressed workbook, 1,000 edits per revision.
CSV accepts UTF-8/UTF-8 BOM and comma delimiter. Oversized tables fail explicitly.
New namespace only: 100 MiB live bytes and 1,000 records per conversation.
Input retention is 30 days and generated derivatives 90 days, not extended by reads.
Expired bytes are removed on file access/list/upload; metadata remains as a receipt.
These limits do not implement user/global quotas. No background cleanup job is installed.
Legacy artifacts, business history, backups and provider files are untouched.
An interrupted exclusive write can leave an orphan; reconciliation is still pending,
and an unknown write is never silently overwritten.

## Dependencies and evidence boundary

CSV/HTML use the standard library. XLSX needs the existing openpyxl package;
the pinned dependency list is `requirements-files.txt`. The existing `pr-fast`
workflow installs this list when conversation files change, before running the
isolated offline checks. Production dependency installation remains outside this slice.

Local tests exercise real synthetic CSV/XLSX bytes, immutable revisions, restart,
idempotency, HTTP adaptation, ownership, revocation, integrity and expiry. Existing
socket HTTP tests cover the original adapter. No real customer data, model calls,
business API calls or production actions are used.

Pending: UI attachment controls, actual natural-language follow-up with a real model, isolated calculation, global
quotas, scheduled/orphan cleanup, publisher mapping and production acceptance.
This PR is the first backend slice; it does not claim the complete A1 workflow.

## Turn-bound file work package (local/mock acceptance)

`POST /turns` additionally accepts optional `file_ids` (at most 10 IDs, normalized
as a set). The request identity includes the attachment set; the same request ID
with different attachments fails. Empty attachments retain compatibility with
legacy text-only requests. Every ID must belong to the authenticated conversation,
exist, pass integrity checks and be unexpired before the turn is reserved.

`source/conversation_file_bindings.py` provides
`context_factory(store, owner, cid, turn_id, authorized)`. The service constructs
these arguments; none are model inputs. The returned capability exposes:

- `catalog()`: only this turn's explicit inputs and generated derivatives.
- `read_table(file_id, sheet=None, offset=0, limit=None)`: complete bounded parsing
  for internal callers; the model consumer always supplies a sheet and page size
  of 1–200. `complete` and `coverage.scope=selected_sheet` describe only that
  sheet in the current request, never the whole workbook. `next_offset` drives
  page traversal. Internal complete reads use `coverage.scope=workbook`.
- `revise(file_id, edits, format, request_id)`: immutable output, registered to
  this turn. The request ID is internally scoped by turn. Repeated requests with
  unchanged arguments reconcile the same file. No automatic retry occurs.

Each call rechecks the original FS authorizer, conversation owner, turn state
(queued/running only), bound membership, expiry and bytes. Stopping, terminal,
dispatch-unknown and preparing turns cannot use file tools. The existing task
gateway separately checks owner/task/lease. A new turn inherits no files: a
follow-up must explicitly bind the derivative ID.

Bindings live under the new file namespace, with atomic sidecar replacement;
reserve/bind/revise share the original conversation DB write lock. No schema or
public migration is introduced. File metadata may survive a failed binding write;
an explicit reconciliation using the original request ID reuses it rather than
creating a duplicate. No claim of cross-filesystem atomic rollback is made.

Receipts add a `download_url` pointing to the existing authenticated file route,
never a token or public URL. `detail.turns[].file_bindings` exposes inputs and
generated IDs to the authorized UI/client. For example, a 451-row sheet requested
with offset 0/limit 200 returns `complete=false`, `returned_rows=200`,
`next_offset=200` and coverage `{scope: selected_sheet, total_rows: 451,
offset: 0, end_exclusive: 200}`. A two-row selected sheet requested at offset 0
with limit 200 returns complete=true and next_offset=null for that sheet.

The active v2 `conversation_service.py` attaches B's
`attach_conversation_file_tools(book, context)` and adds its static `file_prompt()`
to the admission prompt, without reading files in preparing state. B owns the
independent consumer and the shared schema/allowlist. A owns the service seam,
bindings, storage, HTTP and the synthetic loop acceptance test. Production and
real model acceptance remain separate from this local/mock work package.

### Local combined acceptance

Combined A candidate `3d972b4f` with fixed B candidate `6c008963` using a normal
merge in A's independent worktree. The two tests in
`tests/test_conversation_file_loop.py` passed with actual A/B implementations:

1. Actual v2 submit/dispatch code, simulated provider/task services, static prompt
   attachment without preparing-stage file reads, and generated file registration.
2. Real local synthetic CSV bytes through the HTTP adapter and turn submission;
   scripted worker wire calls through the actual ScopedTools task/lease checks and
   B consumer; all 451 rows read across three pages; specified edit exported to real
   XLSX bytes; cross-user download rejected; completed-turn tools rejected; explicit
   derivative binding in a new turn produces a third immutable CSV version.

The existing pr-fast `test_conversation_store` entry includes these loop tests via
`load_tests`. Combined conversation checks: 28 passed. Combined Core checks: 83
passed (including B's 11 file-consumer/proxy tests). Existing conversation HTTP and
release checks: 10 passed. Inputs are synthetic; the model, task services and
provider are simulated. Real-model calls, production, browser/UI interaction,
standalone calculation isolation and natural cleanup cycles are not validated.

A's scripted loop loads the 20261021 proxy. B separately reports 11 boundary
tests covering both 20261021/20261026 proxies and the 20261021 runs contract,
including exact file-tool schemas/allowlists and task/lease/deadline/no-context
rejection before reaching file storage. This does not verify which proxy is
assembled in production, a real worker process, or a model run.

Only the Personal coordinator creates the final integrated work-package draft PR;
A supplies this branch/commit and repairs its owned files within that package.
