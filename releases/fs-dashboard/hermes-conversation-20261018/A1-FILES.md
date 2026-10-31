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
the pinned dependency list is `requirements-files.txt`. No dependency was installed
in this task. Shared CI preparation belongs to the Personal coordinator and must
include these dependencies before XLSX tests can pass in a clean runner.

Local tests exercise real synthetic CSV/XLSX bytes, immutable revisions, restart,
idempotency, HTTP adaptation, ownership, revocation, integrity and expiry. Existing
socket HTTP tests cover the original adapter. No real customer data, model calls,
business API calls or production actions are used.

Pending: UI attachment controls, binding files to a turn and exposing scoped file
tools to Hermes, actual natural-language follow-up, isolated calculation, global
quotas, scheduled/orphan cleanup, publisher mapping and production acceptance.
This PR is the first backend slice; it does not claim the complete A1 workflow.
