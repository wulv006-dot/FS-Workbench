# Published customer runtime — G1 C implementation

This is a separate loopback Node service. It does not change the existing management server, authentication on 8895/8948, administrator CSRF, PostHog secrets or management state. No production deployment or main-site integration is claimed.

## Startup and publication

`node app/runtime/server.mjs` uses these server-owned environment values:

| Variable | Meaning |
| --- | --- |
| `CAMPAIGN_PUBLIC_RELEASE` | Absolute JSON path of the current sanitized **published** release (for example the management publisher's atomic `center/published/current.json`), never `state.json` or raw Admin output |
| `CAMPAIGN_PUBLIC_MANIFEST` | Absolute JSON path of an exact `{ "relative/file": "sha256" }` static manifest |
| `CAMPAIGN_PUBLIC_ORIGIN` | Exact configured HTTPS origin; HTTP is limited to localhost development |
| `CAMPAIGN_PUBLIC_PREFIX` | Default `/events/`; slash-delimited path prefix |
| `CAMPAIGN_PUBLIC_ROOT` | Default application directory, containing FC pages and `seasonal/` |
| `CAMPAIGN_PUBLIC_PORT` | Default 8949; **controller must verify availability before deployment** |
| `CAMPAIGN_RUNTIME_DATA` | Default `/var/lib/fs-campaign-runtime`; private persistent intents, quotes and operation ledger |
| `CAMPAIGN_PUBLIC_MODE` | `preview` (default), `integration_test`, or unverified `live` |
| `CAMPAIGN_TEST_PRICES` | Optional **server-side** test-only JSON mapping product key to integer USD minor-unit fixture price; used only in `integration_test` |

The runtime pins static manifest hashes and bytes at startup. Static deployments use the existing CAS publisher and a project service restart. Published configuration updates do not require a restart: the CLI rereads `CAMPAIGN_PUBLIC_RELEASE` through a validated `snapshotProvider` for every config/capability/intent/quote/prepare request. The FS publisher stores immutable sanitized versions under `/var/lib/fs-campaign-dashboard/center/published` and atomically replaces `current.json`; draft state is never read. A malformed, missing or unpublished current snapshot fails closed without a stale fallback. Use `snapshot` alone only when a caller deliberately wants a startup-pinned configuration. Do not edit a served artifact in place and call it a release. Original management data/history stay in their existing directory. The new ledger must survive restarts and release rollbacks; never reset it to retry checkout.

`fs-campaign-runtime.service` runs as `www-data`, binds to `127.0.0.1` only and writes only its systemd StateDirectory. An explicit `/etc/fs-campaign-runtime.env` is required. The controller supplies the actual verified origin, release/manifest paths and Nginx location through the original formal process; this change does not modify Nginx or open a port. All pages currently send `X-Robots-Tag: noindex, nofollow`, including an unverified `live` configuration. Formal SEO release remains an integration step.

## Release projection supplied by management

`projectRelease` in `app/runtime/snapshot.mjs` is the only public field projection. The management publisher should map its own model into this input shape. No backend credentials, raw response, cost, admin URLs, user metadata, editable capability flags or arbitrary nested objects survive this projection.

Management can import `createSnapshot(publishedRelease)` to produce the safe persistable JSON shape (including its required published marker), then use its existing atomic publication/history mechanism. `validateSnapshot(input)` returns the validated public projection and rejects drafts. Neither helper promotes a draft or performs a write. `createCommerce(options)` in `commerce.mjs` exposes `config`, `capabilities`, `intent`, `quote`, `prepare`, `lookup` for the controller's server wiring; the public HTTP factory is `createPublicServer(options)` in `server.mjs`. Both factories accept optional synchronous `snapshotProvider: () => publishedSnapshot`. Each operation validates one fresh snapshot before processing; a request never combines fields from two versions.

```json
{
  "schema_version": 1,
  "publication_status": "published",
  "release_id": "release-immutable-id",
  "source_revision": "git-commit",
  "config_hash": "<64 lowercase hex SHA256>",
  "rule_hash": "<64 lowercase hex SHA256>",
  "pages": [{
    "activity_id": "fc27-weekly",
    "page_id": "weekly",
    "rule_version": "rule-v1",
    "benefit_binding_version": "binding-v1",
    "path": "Weekly-Scout.html",
    "title": "Weekly Scout",
    "active": true,
    "ends_at": "2026-12-01T00:00:00.000Z",
    "product_keys": ["product-123"]
  }],
  "products": [{
    "key": "product-123",
    "title": "Display title",
    "product_ref": {"site_id":"266", "game_id":"1327", "model_id":"model-id", "goods_id":"123", "sku_id":"actual-spec-id"},
    "platform": {"code":"ps", "attribute_id":"21587"},
    "quantity": {"unit":"item", "min":"1", "max":"10", "step":"1"},
    "available": true,
    "attributes": [{"attribute_id":"edition", "required":true, "values":["gold"]}],
    "image": "assets/product.webp"
  }]
}
```

IDs are strings from the correct original namespaces. Optional IDs must be omitted when absent, never fabricated. Optional `quantity.group` preserves the main-site purchase group. Quantity values are decimal strings (up to six decimal places); integer arithmetic validates minimum, maximum and step without floating-point drift. `ends_at` and `image` are optional. Product images must be local public asset paths. Activity/page/rule/binding context remains attached to each intent; identical goods/SKU in two activities do not collapse into one context.

Static access is the intersection of an explicit code whitelist and the supplied SHA256 manifest. It admits the existing FC customer pages/scripts, the Seasonal customer files under `seasonal/` and flat image/font assets. It rejects management paths, runtime source, tests, Markdown, source maps, raw catalog JSON, traversal, percent/double decoding and symlink/reparse paths. Every manifest file hash is checked before listening. Original client `catalog.js` / analytics configuration scripts must themselves be reviewed public build artifacts; never include raw Admin responses or the server PostHog secret in those scripts. The API projection does not make an unsafe JavaScript build artifact safe.

## HTTP and client adapter contract

All paths below are relative to `CAMPAIGN_PUBLIC_PREFIX`. JSON POSTs require exact configured `Origin`, `Content-Type: application/json` and must not declare `Sec-Fetch-Site: cross-site`. The runtime never forwards a browser Cookie to Admin or the main site. Errors expose a stable `code`, mode and `live_checkout:false`, without raw backend messages or stacks.

| Method and path | Request/result |
| --- | --- |
| `GET api/campaign/config` | Current sanitized published release plus server mode and `live_checkout:false` |
| `GET api/campaign/capabilities` | Server capabilities and explicit test capability availability |
| `POST api/campaign/intents` | Validated context and selected product keys; returns opaque `intent_id`, server-minted stable `operation_id` and server-resolved original product references |
| `POST api/campaign/quote` | `{ "intent_id":"<original UUID>" }` |
| `POST api/campaign/prepare_checkout` | `{ "operation_id":"<original ID returned by intent>", "intent_id":"<original UUID>", "quote_id":"<original UUID>", "return_route_id":"activity" }` |
| `GET api/campaign/operations/<operation_id>` | Read-only lookup of the **original** operation; does not resubmit checkout |

Intent body:

```json
{
  "activity_id":"fc27-weekly", "page_id":"weekly", "rule_version":"rule-v1",
  "benefit_binding_version":"binding-v1", "currency":"USD",
  "lines":[{
    "line_key":"line-1", "product_key":"product-123",
    "quantity":{"value":"1","unit":"item"},
    "attributes":[{"attribute_id":"edition","value_id":"gold"}]
  }]
}
```

The customer submits selections, not serialized Admin `attr`, prices, privilege flags or main-site URLs. Missing required specifications return `SPEC_REQUIRED`; unknown values return `SPEC_INVALID`; unpublished/out-of-scope/unavailable products cannot become a purchase line. A selected SBC already owned by the customer must be omitted by the original selection logic, not represented by a fabricated SKU. Existing FC/Seasonal selection UX is a separate D/E client task; this C change does not alter those scripts.

For the future main-site adapter, runtime-resolved lines include `product_ref`, `platform`, validated `quantity`, `attributes`, `line_key`, `product_key`, with the frozen activity/page/rule/binding/intent context. Do not reuse FC `new_items` encoding for currency/VC/game coins. Actual main-site quantity and attribute serialization belongs to the verified main-site adapter.

## Truthful modes and idempotency

All real capabilities except public snapshot read are currently `false`, even if JSON input or `CAMPAIGN_PUBLIC_MODE=live` claims otherwise. Capability output explicitly includes `catalog_source:published_snapshot`, `catalog_authoritative:false` and `capabilities.live_catalog_read:false`: `catalog_read:true` means the published snapshot can be read, not that Admin/current backend products or prices have been verified. `preview` and unverified `live` quote/checkout return `MAIN_INTEGRATION_REQUIRED` (503). No environment switch supplies a verified production adapter.

`integration_test` requires the explicit server fixture adapter. Quotes return `status:integration_test_quoted`, `authoritative:false`, `test_only:true`, `live_checkout:false`, no applied activity discount and no claim to main-site prices. They expire in 60 seconds. Fixture price changes return `PRICE_CHANGED`; expiry returns `QUOTE_EXPIRED`. Test checkout results return `integration_test_result` or `unknown`, `test_only:true`, `cart_mutated:false`, `live_checkout:false`, per-line confirmed/rejected/unknown and **no checkout URL**. They cannot be mistaken for a live cart mutation. Main-site stacking, benefit eligibility and actual settlement are unimplemented and remain false.

The server mints and persists the checkout `operation_id`, `release_id`, `config_hash` and `rule_hash` with the intent. The caller retains that ID; replacing it for the same intent returns `REQUEST_CONFLICT`. Quote and prepare validate the current published version; any release/config/rule change returns `RULE_VERSION_CONFLICT` (409), including a POST replay from an old release. The customer must review the updated selection/quote; the server never silently reprices the old intent. Original operation lookup remains available across updates, even if the current snapshot is invalid/unavailable, and never creates another checkout.

Every accepted checkout operation is reserved on disk using exclusive creation and fsync before the adapter runs. While its release remains current, identical POST payload and ID return the saved result or `OPERATION_UNKNOWN`; a changed payload for that ID returns `REQUEST_CONFLICT` (409). A timeout/crash never triggers a second prepare call. Lookup calls only `lookup_checkout_operation` with the original ID and projects only allowed line statuses. Adapter errors, raw messages, tokens and arbitrary URLs are discarded. No pending operation is evicted. Mode-specific storage prevents a test operation from appearing in preview/live; operation records are not release-specific so a later release can still resolve the original ID. An unknown/missing ID never grants permission for a blind POST retry.

Before a real main-site adapter is enabled, the controller must verify exact endpoints, read-only lookup semantics, quote refresh/expiry, original cart preservation, per-line/atomic outcomes, test/live separation, identity flow, allowed checkout origin and server capability evidence. Runtime checkout success must then be based on authoritative main-site evidence. There is intentionally no generic configurable HTTP proxy or credential forwarding implementation here.

## Publisher changes and evidence

`native/release_navigation_base.py` is the exact frozen original copied read-only from the original-task baseline; SHA256 remains `5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357`. The existing guard is unchanged. The original locks, journal, per-file CAS, auth/RBAC hash guards and manifest-bound rollback remain in the frozen publisher.

The adapter adds only two optional exact targets: `fs-campaign-runtime.service` and `runtime.env`; stage both together. Original four required special targets remain required. App asset suffixes now include actual image/font/XML/text build artifacts; app path normalization rejects backslashes, dot traversal and ambiguous separators. Restart remains limited to campaign management/runtime units and Nginx. No unit, environment or Nginx change was applied to a server by this implementation.

Local validation: `node --test app/tests/*.test.* app/runtime/tests/runtime.test.mjs` (55 passing, including 11 runtime tests); `python -m unittest test_publish -v` (6 passing). These cover field projection, draft rejection, mode spoofing, specification/quantity/scope validation, quote expiry/change, concurrent same ID, payload conflict, mixed outcomes, durable unknown result, read-only lookup, cross-mode isolation, static whitelist/hash/symlink/traversal, exact HTTP Origin, immutable static bytes, published snapshot reload/version conflict, continued original lookup and scoped publisher targets/restarts. No live cart, payment, Admin write, DNS, Nginx or production runtime check has been run by C.
