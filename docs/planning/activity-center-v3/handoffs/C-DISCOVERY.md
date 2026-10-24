# C runtime discovery — FS-V3-G1-START-01

Date: 2026-10-24. Read-only discovery, no SSH, no production/API writes, no source edits, no tests executed. Main controller: `/root`.

## Baseline and provenance

- Current project checkout: `D:\codex\2026-10-24\task\fs-campaign-center-v3`, remote main baseline `2c976e7f849b3b7916e006dd6907e633051cb3fb` supplied by controller and inspected locally.
- Applicable rules read: root `AGENTS.md`, `docs/ops/HOTFIX.md`; V3 business reference under `inputs/v3-local-zip-11fa0eb5/references/业务施工方案_执行参考副本.md` and current task's full main-site interface contract.
- Module source: `releases/fs-dashboard/campaign-analytics-20261023/`. The older `fs-report-followup-20261023/worktree` lacks this module and is not an appropriate implementation baseline.
- Existing root `E:\WorkBuddy\大超服务器` and other tasks' repositories were read only. No files there were changed.

## Existing management runtime

All following relative paths are under `releases/fs-dashboard/campaign-analytics-20261023/` unless stated otherwise.

| Source | Existing behavior | G1 implication |
| --- | --- | --- |
| `app/analytics/production-server.mjs` | Loopback server, default 8948. Every request calls existing auth `127.0.0.1:8895/verify?group=dashboard`. Non-GET/HEAD restricted to admin POST with exact Origin, JSON content type and CSRF. | Extend the existing authenticated management server; do not expose 8948 or remove auth for customer pages. |
| Same file | Prefix `/dashboard/analytics/campaigns/`; `/analytics/api/config`, `catalog`, `export`, `report`, `connection`; static content is allowlisted. | Reuse existing route/auth/CSRF contracts for campaign management and existing PostHog connection. |
| Same file | Secret file is separate from exported public state. Generated `analytics-config.js` forces `enabled:false`, and dynamic `catalog.js` uses `previewCatalog`. | Public customer configuration must be a new explicit field projection of an immutable release, never the complete state or raw backend response. |
| `app/analytics/store.mjs:25-34` | Existing registry/layout with `revision`, `operationId`, exact-payload hash, history and recent 100 operations. | Preserve existing state/history. A separate durable operation ledger is needed for checkout/benefit effects; the recent-100 draft editor list cannot provide permanent dedupe. |
| `app/analytics/server.mjs` | Existing PostHog reporting consumer. | Keep behavior analytics separate from paid discount attribution; do not generate purchase facts from clicks. |

Local historical documentation `E:\WorkBuddy\大超服务器\docs\planning\fs-campaign-dashboard-20261023\README.md` records prior deployment at `/opt/fs-campaign-dashboard`, `fs-campaign-dashboard.service`, loopback8948, persistent `/var/lib/fs-campaign-dashboard`; this subtask has not reverified the live machine. The controller must obtain a fresh remote source/SHA/config/port baseline before publishing.

## Original designs and safe reuse

### FC

- Original source: `E:\WorkBuddy\大超服务器\fc27_season2_live_20261022`.
- Three actual pages: `Weekly-Scout.html`, `Sbc-Companions.html`, `Player-Trio.html`, plus the multi-view `index.html`; page fragments, locale controls, assets and fixed player bundles are part of the deliverable.
- Latest developer receipt: `docs/planning/fc27-season2-live-catalog-20261022/PACKAGE-RECEIPT.json`, version `v6-main-site-integration-contract`, 155 entries, SHA256 `6dd453ae486bd6888df47020a6adf8eaf1cd08617380a8a891552badbe82fe7b`.
- Compared nine central files between original FC source and current module `app/`: `activity-core.js`, `activity.js`, `activity-content.js`, `build-seo.mjs`, `host-adapter.js`, `catalog.js`, `catalog.json`, `page-template.html`, `activity.css`. All are text-identical after only CRLF/LF normalization. Raw hashes differ for eight because of line endings; do not misreport this as a functional divergence.
- `app/activity-core.js:23-27` excludes owned SBC core unless `coreMode==='service'`, dedupes selected product keys, retains original product rows.

### Seasonal Vault

- Original independent source: `E:\WorkBuddy\大超服务器\mmoexp_seasonal_events_20261024`, source commit `5bfa19e051808d6b8033f7eb23132405abc853d4` from prior controller verification, V3 manifest agrees.
- Runtime contents: `dist/index.html`, `creative-kit.html`, `event.js`, `event.css`, `vault-core.js`, `campaign-data.js`, `kit.js/css`, `vault-analytics.js`, existing activity analytics bridge/config and assets. Build source `build-seo.cjs`, `prepare-assets.cjs`, tests remain separate.
- `campaign-data.js` holds 18 packages / 6 games with original IDs, platform/server, quantity/bonus and captured USD prices; these are snapshots, not real-time quotes.
- `event.js:8-16`, `vault-core.js:5-37`: draw/refresh/invitation receipts currently use `Math.random`, localStorage and explicit DEMO receipts. Keep the accepted reveal, fixed-store, pool selection, keep/refresh and invitation UX; this is not production entitlement enforcement.
- V3 acceptance explicitly lists real cart/login/payment/referral, activity quote backend, real-time catalog refresh and FS events as unexecuted. Invitation is an original Seasonal feature and must not be silently removed by confusing it with excluded Matchday/竞猜奖励.
- `build-seo.cjs` hardcodes the original private design-preview origin; it generates CollectionPage/ItemList and labels snapshots/simulations. Preserve collection schema and do not output simulated discounts as authoritative Product/Offer.

## Existing live protections and exact callers

| File/function | Current constraint | Minimum complete extension |
| --- | --- | --- |
| `app/host-adapter.js:create`, lines4-5 | Requires exact `https://www.mmoexp.com` and rejects `activityPricing.enabled`. | Keep original adapter. Add separately selected standalone adapter backed by server capability state; absence of main-site quote/cart capability returns `MAIN_INTEGRATION_REQUIRED`. |
| `app/activity.js:freshReview`, lines80+, cart submission lines97+ | Creates `FCActivityHost`, calls `quote`, `batch` and existing display/currency methods. | Switch through an explicit shared adapter factory; keep SBC/trio/weekly selection and truthful preview messaging. Preserve partial/rejected/unknown outcomes. |
| `app/activity-core.js:payload`, line30 | Fixed `attr:''`, FC `new_items` payload. | Add validated purchase attributes supplied by the common product projection; do not reuse FC payload for coins/VC/currency packages. |
| `app/activity-core.js:refreshLine`, line51 | Rejects `has_sku` and nonempty `saleprop`, strict game/title/platform/status validation. | Add explicit known specification mapping, retain product-scope and availability checks, reject unsupported individual specification. |
| `app/activity-core.js:createBatch`, lines63+ | Stops on first rejected/unknown and prevents second run of same in-memory batch. | Reuse honest outcomes; persistent server operation ID/query contract supplies durable retry behavior for standalone handoff. |
| `app/build-seo.mjs:buildOutputs`, lines111+ | Requires www.mmoexp.com origin and `/Fc-27/*.html` paths; syncs body/head/schema/sitemap/registry/promotion-policy. | Add validated deployment origin/path allowlist/config while retaining default main-site contract. Preview must remain noindex; approved origin and route determine canonical, assets, language and sitemap together. |
| `app/activity-content.js:page`, lines25-32 | Canonical/assets derive from config; breadcrumbs still assume `/Fc-27.html`. | Make actual breadcrumb path configurable as part of the same deployment profile, not a second content source. |

The common commerce contract should cover server-authoritative `capabilities`, `quote`, `prepare_checkout`, `lookup_checkout_operation`, product/spec/quantity identities, quote expiry, stable operation ID and explicit unknown/conflict states. Mock responses must be isolated under `integration_test`; missing real integrations must never produce a nominal live checkout URL.

## Publisher / deployment facts and hazards

- `publish.py` is an adapter over the existing journalled CAS publisher, scope `fs-campaign-dashboard-20261023`; target allowlist only `app/*` with approved text/image extensions plus four exact special targets (Nginx fragment, navigation JSON, module-registry JSON, systemd unit). It protects existing auth/RBAC bytes and only restarts the campaign service/reloads Nginx.
- **Current repository import compatibility issue:** module `publish.py` pins base SHA256 `5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357`; `native/release_navigation_base.py` is absent. Its fallback `../menu-cache-20261015/native/release_navigation.py` currently hashes `bc62f36ea3b8ed55095ff48c26a69b07c51bfa6b03bccc3ccf69f90c21f650bd`, so using that fallback would fail the explicit hash guard. This is hash evidence, not a claimed test run.
- Existing original-task frozen file `E:\WorkBuddy\大超服务器\fs_campaign_dashboard_20261023\baseline\release_navigation_base.py` was read and has exactly the required `5548d9...` bytes. Controller can preserve that pinned original as a new project-scoped package input if this publisher is reused; do not weaken/remove its hash assertion or change the old task's source.
- Frozen base acquires both `/var/lock/fs-navigation-release.lock` and `/var/lock/fs-dashboard-release.lock`, checks ownership/type, keeps durable manifest/journal/backups and per-file CAS. Scope rollback binds to original approved manifest and must preserve runtime data.
- Later navigation migration uses `navigation/release_ui.py`, reusing `/opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_ui_finish.py` on the server. Its `prepare_release.py` is a historical one-shot migration with `already prepared` assertions. Current navigation already contains the activities section, so do not rerun it blindly.
- The existing publisher does not yet admit a standalone public service/root/unit. Add an exact project-specific allowlist/adapter around existing publisher mechanics; do not enlarge it to arbitrary paths or silently upload into protected targets.
- Controller alone should inspect actual available loopback port, current Nginx include context and existing publisher, then stage fresh current before-SHAs. Never replay the original empty-target stage manifest.

## Recommended minimal implementation / ownership

1. **Controller + C:** retain existing management service, add a small separate loopback public runtime serving only immutable built content, explicit public-config projection and commerce endpoints. It must not serve `analytics/*`, internal docs, tests, state, ledgers, raw backend responses or secrets. Static paths are allowlisted and symlink/traversal checked.
2. **C:** add common standalone commerce adapter/SDK and server capability enforcement. Preserve existing main-site host adapter unchanged. Add integration-test adapter with deterministic fixtures and persistent original-operation lookup; real mode fails closed until main endpoints verified.
3. **B + controller:** extend existing management state via compatible migration for page/rule/benefit binding/catalog/release metadata; leave original registry/history/PostHog secret intact. Runtime publication consumes a frozen revision and records release/source/config/rule hashes.
4. **D/E after shared contract:** connect original FC and Seasonal UI to the shared projection/commerce adapter, retain all accepted views/interaction. Seasonal entitlement/draw state cannot become authoritative merely by moving JS to187; server ledger/main identity dependencies must be explicit.
5. **C/D/E:** configurable deployment profiles rebuild all page body/head/schema/canonical/sitemap/assets together. A controlled internal 187 preview can satisfy G1 while T01 formal DNS remains pending; this must not remove existing IP/auth policy or claim a public customer domain is ready.
6. **Controller publication:** source commit + PR/CI + Q review + fresh CAS manifest + original locks/backups + local SSH inspect/apply/readback. Restart only the project module(s); keep auto-pricing/collection/auth services unchanged.

## Related validation commands and unverified items

Run only after implementation is assigned, with exact candidate/version:

```powershell
node --test app/tests/*.test.*
node app/build-seo.mjs --check
python -m unittest test_publish -v
```

The publisher test import currently needs the verified pinned base packaged as described above. For Seasonal source: `node --test tests/vault-core.test.cjs tests/analytics-bridge.test.cjs tests/catalog.test.cjs`, `node tests/check.cjs`, `node build-seo.cjs --check` (all names found in original acceptance/history; not executed here).

Add direct tests for public/management separation, traversal and symlink rejection, no secret fields, quote expiry/price changes, original-ID unknown lookup/conflict, same SKU with different activity contexts, preview/test/live partition, and generated-origin/asset/SEO consistency. Browser checks should reuse accepted design baselines and cover both original full page sets.

Unverified by this subtask: live187 file SHAs/services/ports, current Nginx/public entry, current publisher bytes/server dependencies, Admin operations, DNS/main-site endpoints, real discount/cart/payment/referral/attribution. No production claim or rollout was made. No blockers prevent delivering this discovery; subsequent C work awaits controller's fixed shared contract and exclusive file assignment.

## Model-switch checkpoint

Controller requested a safe P0 stop before implementation. Discovery is complete; no C implementation was started. This spawn requested no model/effort override and inherited parent settings. Available read-only agent inventory reports only names and running state. Tool discovery exposed no current-agent model/effort inspection endpoint; runtime model and reasoning effort therefore remain unverified, and no model identity is inferred or asserted. Await controller's explicit subsequent assignment.
