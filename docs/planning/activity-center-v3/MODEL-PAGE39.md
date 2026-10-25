# MODEL-PAGE39 — page-native model configuration

User correction (2026-10-25): configuration starts with the activity page, then its media slots and business content. Weekly cards are chosen by Admin Player model/version; one selection resolves MMOEXP PS/Xbox/PC goods. SBC cores/companions, the three-player lineup and native fixed bundles retain distinct structures. A generic goods/SKU picker is not the target workflow.

## One editor and one draft

Keep analytics/products.html as the sole editor, existing authentication, revision/CAS, operation receipts, immutable publication and exact-shape history restore. The analytics data page and report contracts are untouched. Replace the overlapping FC platform-product list and preset-only arrangement UI with a single logical-card arrangement. Seasonal keeps its own pool/fixed/theme semantics.

Reuse fc_layout for ordering, SBC relationships and bundle placement. Add server-owned fc_models only when a model is explicitly imported; derive its safe public representation through the same snapshot. Missing old fields retain inheritance and are not silently materialized on page switches or unrelated edits. Model metadata is not client-authoritative.

A model has no proven site_id field. MMOEXP scope must be checked against goods.site_id=266; FC game_id=1327, category and goods.mid must match. Platform aid values observed for FC are PS21587/Xbox21585/PC21589. A missing, ambiguous, offline or unverified platform is not filled from another site/platform. Catalog identity verification is not authoritative quotation or purchase eligibility.

## Media

Page-specific hero desktop/mobile, share and card slots use project-owned immutable image blobs. Existing built-in images remain inherited until explicitly replaced. Upload/preview is authenticated; only published references may be publicly served. No remote-fetch proxy, SVG execution, general filesystem paths or permission changes. Upload does not publish a configuration or change Admin product data. Historic blobs and audits are retained for exact restoration.

## Bounded live evidence

Historical evidence proves all 26 accepted FC model groups have three goods references with one shared model_id per group. New-model version/image fields and model-list English/Chinese search behavior require the bounded read-only probe; do not infer support from a route allowlist. Haaland seed goods170014917 maps to model43167385 in the existing catalog evidence.

## Acceptance boundary

Isolated operator flow: select page → inspect model/version and image → add one logical card → inspect three platform identities → switch platform in preview. Cover correct missing/offline/ambiguous behavior, scope rejection and no invented quantity/price. Media upload → preview → draft save/readback → exact restore must preserve other pages and omitted fields. Public content remains English, including administrator-supplied display text.

No production deployment, live draft save, Admin mutation, rewards, cart/order or payment is authorized by this development task. Main-site activity pricing/ordinary-discount/order-attribution contracts remain a separate dependency. Candidate tests do not claim those integrations work.

2026-10-25 12:03:26Z, original local SSH/Admin channel: model43167385 detail and its site266/gid1327/cid9627 goods page each returned HTTP200/business code1. Exactly three goods were returned: PS170014917, Xbox170026873, PC170014921; all mid43167385. No Admin mutation.

12:06:26Z: model detail plus two model-list GETs returned HTTP200/code1. Player-scoped title LIKE Haal returned exactly three models (44119311 Signature, 44119279 Destined for Glory, 43167385 Gold Non Rare), with scope and title matches checked. Literal Chinese 哈兰德 returned total0. Chinese aliases must be explicit and maintainable, not advertised as native search support. Model pic was empty for all three; version/imagery attribute extraction remains under verification. Private local schema observations are outside Git; no raw backend response is committed.

12:10:40Z: a final single read of known model43167385 verified Version property347 uses default.checked_item=8361 and pvs item8361 name Gold Non Rare. The resolver must use this exact selected-option relationship, not split a title or treat all available versions as selected. No image candidate was found in the inspected _extend; missing imagery stays explicit and can be supplied through the page media slot.

## Candidate interface boundary

- `backend-read / model_search`: one scoped model page, exact model ID or explicit keyword/alias; `site_id=266` is the intended goods scope, not a fabricated model field. Search results must be resolved before import.
- `backend-read / model_resolve`: confirm model identity/category/version and bounded site-scoped goods associations; no price or transaction claim.
- `center/import-model`: original revision/operation ID/full-draft CAS; new model facts obtained server-side, not accepted from the browser.
- `center/assets/upload`: authenticated image-byte upload into project storage; separate from draft save and publication.
- Existing `center`, `center/restore`, `center/publish`: one persistence/history/publication path. No second editor or duplicate save contract.

The new UI must surface old partial-platform masks and preserved legacy imports rather than silently replacing them. An explicit model-wide selection may materialize that card's platform references, with a visible change review; unrelated fields/pages remain unchanged.

## Execution setting observation

At 2026-10-25T12:28:15Z the supported local config read showed global service_tier=default, no active profile and no .codex/config.toml speed override in this task root or worktree. No global setting was changed. Per-request runtime tier and past calls are not exposed by the available task metadata tools; the config observation does not prove a running request changed tiers. Subsequent calls do not explicitly enable Fast; existing reasoning assignments remain unchanged.

## Implementation and validation status

The candidate uses one products editor and the original center store. Runtime additions are model-cards/media-contract/published-media plus analytics/media-store and backend/campaign_backend/models.py; publisher allowlisting includes the new Python dependency. Public scripts do not use the undeployed native-fc-contract.mjs from PR457.

Backend model/search regression and the complete existing backend suite passed locally. Node tests exercise import/CAS/server-owned facts, duplicate references, exact restore, null price/quantity, private uploads and public current-reference enforcement. Local HTTP tests cover existing auth/CSRF, idempotent recovery and media removal. POSIX directory-mode/fsync branches are to be exercised by Linux CI; Windows results are not proof of deployed filesystem permissions.

The browser flow uses the real local management/public HTTP services with isolated synthetic backend data. It is distinct from the observed live read-only Admin queries above. No candidate UI was deployed or connected for a real write. The full workflow and review findings are completed before the final candidate is frozen; CI and final head are reported with the PR.

Known boundaries: literal Chinese model search did not match upstream; the explicit alias table currently contains only 哈兰德→Haaland. Adding aliases requires a reviewed mapping update, not automatic translation. New models without proven imagery display a missing-image state and accept an operator-supplied page/card image. Existing accepted assets are reused only by exact model/goods mapping and labeled historical provenance. Search candidates are not labeled site-verified until resolution confirms MMOEXP goods. Unknown/ambiguous/offline platforms remain unavailable; this work never supplies authoritative prices or opens checkout.

Final local workflow results: 185 backend tests and 25 publisher tests passed; the UI owner reports 36 targeted Node checks and seven browser suites passed. The synthetic operator flow covers Weekly first position, SBC two-companion relationships, independent native bundles, Trio series/slot validation, three-platform reference changes, legacy role preservation and exact restoration. Public image validation includes decoded dimensions, HTTP 200 and byte SHA256 equality. Complete public runtime traversal was exercised for Weekly plus SBC hero delivery; this is not a claim of live acceptance for every page. The existing Q findings on upload recovery, directory persistence and original receipt asset verification were fixed. Final frozen-head review and Linux CI remain separate gates.
