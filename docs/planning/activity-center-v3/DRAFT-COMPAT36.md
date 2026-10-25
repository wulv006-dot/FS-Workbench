# DRAFT-COMPAT36 — preserve inherited draft configuration

Scope: the single products editor and its existing center store. No report-page, Admin, production configuration, deployment or checkout changes in this task.

## Contract and user behavior

The stored draft remains the source of truth, including omitted properties. GET returns that raw draft; effective_fc_layout is a separate display-only projection of the existing legacy layout. Missing product_keys continues to inherit the page seed; an explicit empty list means no selected products. Merely reading, switching pages, querying, or cancelling never materializes those defaults.

The editor compares the rendered controls with raw values. Untouched timestamps retain timezone and sub-minute precision, text retains whitespace, and omitted language/image settings stay omitted. An actual product selection/order edit makes only that page list explicit. FC layout changes make the displayed layout explicit only when changed; valid dormant SBC routes remain preserved and validated. Before saving, the editor lists changed pages/fields and identifies inherited-to-explicit changes. An unchanged draft does not submit.

Validation still rejects unknown fields, wrong types, identity/path/mode changes, invalid products and invalid layouts. Validation does not normalize the persisted draft. Publication retains the raw draft and separately produces the existing normalized preview snapshot; this task does not authorize publication.

Restore uses server-held history, not client-supplied backup data. It is available only for the immediately preceding save/restore, with identical publication and server-owned imported-product state (including property presence). A confirmation identifies the prior revision and changed pages/fields. Current revision CAS is required. Restoring copies the exact old draft shape, appends a new revision/history/operation receipt and never deletes audit or rewinds the public snapshot. Import or publication boundaries are not automatically restorable. Existing history without operation kind is not treated as eligible.

Unknown responses retain the stable operation ID and payload; the existing durable operation recovery is reused. Different content under the same ID conflicts. A newer concurrent revision blocks restoration rather than overwriting another operator.

## Evidence and limits

All fixtures are synthetic, using local isolated data directories and mock authentication. The real local HTTP/store/browser path covers revision2 first save, no-op/page switch/cancel, sorting, selecting an existing product, page isolation, unchanged precise timestamps, a lost save/restore response, same-ID readback, stale CAS and exact shape restoration. Store tests cover invalid raw values, dormant SBC routes, restore boundaries and interruption at prepared/state/receipt. Existing editor/Seasonal/operations browser regressions remain in CI. No production draft was saved or migrated.

This does not solve unfiltered upstream keyword latency, establish an independent SKU API, or verify purchase parameters. Those previously disclosed limits remain unchanged.

## Next onsite approval (not executed)

Deploy only the four reviewed runtime files (center-store.mjs, production-server.mjs, products.html, products.js) and truthful module version metadata, after target/hash/CAS and protected-report/config checks. Do not deploy unrelated main changes.

With separate approval, back up the current raw draft and public snapshot, verify no pending/concurrent operation, then reorder existing products on one unpublished draft page once. Save with a stable operation ID and independently read back. Confirm restoration to the server-held immediately prior revision; restore once and independently compare the entire raw draft, including omitted fields, values and types, to the backup. New audit/revisions are expected; public snapshot, old layout, other modules and business state must remain unchanged. If no safe draft or a concurrent change exists, stop the write. No product import, new activity, preview publication, activation, coupon operation or checkout. Any unknown outcome is reconciled with its original ID before proceeding.
