# PAGE-CATALOG32 — page-first authoring and bounded Admin discovery

Status: local candidate; not deployed and no production configuration saved by this work.

## User workflow and preserved boundaries

Select one of Weekly Scout, SBC Companions, Player Trio, or Seasonal Vault first. Edit that page's title/SEO, schedule, language/share image, benefit references and product selection. Seasonal has its own theme and fixed/pool placement; it does not use FC player controls. Switching pages retains unsaved edits. Saving a draft is distinct from publishing its preview and from enabling real checkout.

Search the existing site266 catalog within an explicit game using one keyword, goods ID or model ID, optional raw category/platform IDs, and bounded pages. Search does not replace any selection. Detail is reread on the server before import. Model ID remains a model ID; quantity tiers are not SKU IDs. There is no independently verified arbitrary SKU search route. The detail view exposes available specification observations and missing mappings rather than inventing them.

Original accepted products can be reselected, removed and reordered. Existing FC combination editors remain available by selected page. After changing original FC structure, explicitly synchronize that page's original selection, then save/publish; imports and sibling pages remain intact. Published FC structure must carry the actual saved routes/default/order, rather than reverting to original catalog relations.

Imported products are server-owned, sanitized metadata. Unknown title/platform/quantity remains explicit; generic title fallback is an identity label, not a new product name. Operators may assign a display role and SBC core/companion display relation. These are content organization, not proof of native SKU semantics or game chemistry. New imports remain unavailable for purchase and do not acquire invented prices. Seasonal imports without verified price/quantity are catalog previews, excluded from demo discount draws. This work does not claim an arbitrary imported SKU is already a fully priced FC card, purchasable bundle or reward-eligible Seasonal offer.

## Existing production evidence, narrowly checked

Original Windows SSH wrapper was used; no credentials or raw Admin rows were exported. 2026-10-25 08:34:34 UTC, host play187, exit0: existing center HTML has no page selector, discovery JS uses catalog_discover and center publish uses seed-only membership. Seasonal runtime bridge hash still e54db7c0dde2a16d98a61746da17b9f156ed5346c6dee5a54f2b7cc97295c821 (RELEASE31).

2026-10-25 08:38:49 UTC, exit0: two read-only Admin GETs. Existing goods185916875 scoped to site266/game1327 yielded model44921271/platform21587/category9627. One Goods/index page with limit2 and combined quick_search/mid/aid/cid filters returned one row, total1, matching scope and title keyword. This proves that combination only, not every game or an independent SKU endpoint. No cart, orders, coupons or business mutations were performed.

## Compatibility and recovery

Missing page product_keys continues to inherit the accepted seed; explicit [] stays empty. Full-draft CAS preserves sibling pages. Existing imports cannot be altered through ordinary save; authenticated server import owns their data. Import operation IDs bind revision, full draft, page and product reference. Existing operation receipts are resolved before contacting Admin again. Unknown results retain the same operation ID.

Published snapshots retain existing schema1 compatibility with additive optional fields; original records are not rewritten in place. Seasonal browser state for a published catalog is scoped by release, preserving the earlier local demo state. No migration is executed against production by this PR. Before any later deployment, back up current draft/public snapshots and operation records; code rollback must not erase newer drafts or audit records. Do not run the old authoring writer against a newer draft without a reviewed compatibility rollback.

## Release boundary

Exact candidate file hashes and runtime target list are generated after final code/Q. Deployment requires a separate approval and current SOURCE-MAP/CAS preflight. Preserve RELEASE31 mixed-version state and other modules; do not roll the whole main branch to production. Configurations, imports, activation, coupon data, live buying and reward parameters are not included in this code-only authorization.

Main-site activity pricing/ordinary-benefit compatibility and actual order/refund attribution remain the separate Monday technical contract dependency. They do not block page authoring and catalog metadata discovery, and they are not claimed passed here.
