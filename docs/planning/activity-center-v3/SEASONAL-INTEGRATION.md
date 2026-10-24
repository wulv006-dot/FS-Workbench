# Seasonal Vault customer integration — E

Scope: original accepted Seasonal Vault source `5bfa19e051808d6b8033f7eb23132405abc853d4`, copied by the controller into `app/seasonal/`. This change preserves its layouts, assets, four themes, six games, 18 packages / eight goods IDs, store links and DEMO flip/keep/pool/refresh/invitation behavior. No Matchday feature was added. The catalog and original image assets are unchanged.

`runtime-bridge.js` uses D's shared `../standalone-adapter.js`. Runtime enablement comes from the SDK's served path or trusted static prefix attribute; URL query parameters cannot enable transactions. It loads the published `seasonal_theme` once; the original theme selector remains usable. Page/activity IDs are `seasonal-vault` / `mmoexp-seasonal`. Lines submit `seasonal-<original p.id>`, original `source.quantity` and `source.unit`, and no client prices, DEMO discounts, bonus quantities or fabricated specifications. The three PoE bundles have an original empty unit; this remains unresolved rather than being assigned a guessed real purchasing unit.

The bag retains its preview label and original product/cart links. Store verification shows preview/integration errors without claiming a real cart change. Required or invalid specifications fail closed and direct customers to the original store. Unavailable seed products describe pending mapping/availability verification rather than assert they are sold out. A test prepare button appears only after an integration-test quote and an explicit server test capability. Unknown operations retain the SDK's original operation ID and permit read-only lookup; they cannot create another intent or repeat checkout.

The original invitation receipts, share copy and refresh credits remain local DEMO simulations. They do not call an actual referral, identity or reward API. Published seed products are deliberately unavailable until the controller verifies purchase descriptors and the main-site adapter; no real main-site cart, discount, payment or reward has been enabled.

Source tools now target `../app/seasonal` directly instead of a nonexistent sibling `dist`. `build-seo.cjs` defaults to preview output with no canonical origin and retained `noindex,nofollow`. An optional formal build requires an exact HTTPS `CAMPAIGN_PUBLIC_ORIGIN` and a validated slash-delimited `CAMPAIGN_PUBLIC_PREFIX` (default `/events/`), producing `<origin><prefix>seasonal/`. This configuration does not provision a domain or enable indexing. `prepare-assets.cjs` requires an explicit original `SEASONAL_ASSET_SOURCE`; it was not run and accepted assets were not rebuilt.

Local evidence, Windows Node / bundled Playwright Chromium:

- `node --test seasonal-source/tests/*.test.cjs`: 15 passing, including original analytics/catalog/core tests and new URL/bridge failure tests.
- `node seasonal-source/tests/check.cjs`: four themes, six games, 18 unique offers, sprite/assets, six collection-schema entries and preview noindex passed.
- `node seasonal-source/build-seo.cjs --check`: deterministic generated output passed.
- `node seasonal-source/tests/browser-check.cjs`: four theme changes, published initial theme, eight-card reveal, keep, DEMO receipt and refresh; exact base quantity; preview rejection; required specs; original-ID unknown lookup and no resubmit; zero browser page errors. Uses explicit local fixture API responses, not production facts.
- `node --check app/seasonal/event.js` and `git diff --check`: passed.

Remaining integration gates: actual main-site descriptors/spec options and units; authoritative quote and benefit rules; identity/referral adapters; real original-cart preservation and order attribution; controller runtime publication, manifest, origin/prefix, service and formal hosting verification. No SSH, production deployment, DNS, Nginx, real cart mutation or financial acceptance was performed by E.

Modern Web Guidance was searched and `accessible-error-announcement` retrieved. Its input-invalid synchronization does not apply to this addition, which adds buttons and a polite operation-status region rather than editable validation fields. Existing native platform/theme selects remain unchanged.
