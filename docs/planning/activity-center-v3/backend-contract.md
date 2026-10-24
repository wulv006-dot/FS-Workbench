# Campaign backend foundation v1

Task: `FS-V3-G1-CONTINUE-02`, role B. Source baseline `df93de3d3a55a108f94bb56060457b4ccc9f01ab`.
Implementation: `releases/fs-dashboard/campaign-analytics-20261023/backend/`.
This is a Python 3.9-compatible, standard-library core and management subprocess bridge.
It does not start a service, change shared modules, change the publisher, or enable real mutations.

## Management bridge

Run `python backend/bridge.py` behind the existing FS authentication, role, Origin and CSRF checks.
The bridge itself is not an authentication boundary and must never be exposed as a public endpoint.
One JSON object on stdin (maximum 300000 bytes), one JSON object on stdout:

```json
{"action":"capabilities"}
```

Returns `{"status":"ok","data":{...}}` or `{"status":"error","error":"MACHINE_CODE"}`.
Legacy session stdout/stderr is suppressed. Raw upstream errors, tokens, URLs, stacks and request bodies
are not echoed. Machine errors are intentionally terse. Bridge capabilities remain false: implemented
route code is not proof of an installed, verified production integration.

Actions:

| Action | Input | Output / boundary |
|---|---|---|
| `capabilities` | action only | Preview mode; no session acquisition; all business capabilities false |
| `benefits_read` | concrete `site_id` | Full coupon/discount catalog, management only; native IDs, raw status, raw scope/time fields, coupon title; no discount code, param_code, nested customer or raw response |
| `catalog_read` | `site_id`, `game_id`, `mapping`, `purchases` | Full scoped goods read; matched model details; validated public product projections; unresolved goods IDs when purchase descriptors are absent |

`benefits_read` returns the complete existing catalog and preserves its raw scope representation.
`requested_site_id` is context, not a claim that a list/string/ALL scope was interpreted as eligible.
`status_semantics=unknown`, `verified_for_mutation=false`; it does not claim a coupon is active.
Controller's 2026-10-24 read-only probe established these field names. B did not perform a real backend call.
New frontend enum/route evidence remains with the controller; this commit does not activate it.

## Shared source reuse

`AdminRead.from_shared_session(session_factory=None, token_reader=None)` gets the existing owner token
from `shared_admin`, binds it to the existing Sales `Session`, and uses only `get_admin`.
The installed `/opt/sales-dashboard/collector/p2pah_auth.py` and `/opt/fs-shared-session/shared_admin.py`
are preferred when present; repository copies are the development fallback. Production must run the
existing interpreter with its existing `requests` dependency; this foundation installs nothing.
Factories are injectable for controlled integration/testing.

Allowlisted list resources: `models`, `goods`, `discounts`, `coupons`, `coupon_logs`, `orders`.
Only `model` and `goods` have read-detail routes (`GET .../edit`, with `data.row` validation).
`pages()` validates full pagination, stable total, unique IDs and optional source scope; partial reads
fail closed. `orders(site_id,start,end)` validates returned site and raw paytime range.
`coupon_logs(site_id,order_numbers)` batches 100 order numbers and checks each returned site's/order's scope.
These raw methods are trusted management/collector interfaces, never public response handlers.
No login, credential cache, cookie export or custom Order session is added. Order details may be supplied
from the existing Order consumer after explicit normalized field mapping; no new Order route is guessed.

## Product projection

`project_product(model_row, goods_row, CatalogMapping(...), purchase_descriptor)` returns a whitelist:
`product_ref`, title, platform, quantity, attributes, price, availability, catalog version/capture time,
optional HTTPS image/product URLs, and `authoritative=false`.
Product IDs retain separate site/game/model/goods/optional SKU namespaces. Site `0 ALL` is rejected.
Model/goods relation and platform attribute ID must match; no same-name substitution or fake SKU.

`CatalogMapping` requires:

```json
{
  "verification_ref":"<controller field/enum mapping evidence>",
  "goods_fields":{
    "site_id":"site_id","game_id":"gid","model_id":"mid","goods_id":"id",
    "platform_attribute_id":"aid","price":"price","sale_state":"<verified field>"
  },
  "model_fields":{"model_id":"id","title":"title"},
  "sale_states":[["<exact raw enum>",false]],
  "currency_scales":{"USD":2},
  "currency_code":"USD"
}
```

This is a shape example, not verified sale/currency semantics. A `currency` source field may replace the
explicit `currency_code` constant; if both are provided they must agree. The integrator must verify the
currency and every availability condition (listing, buy status, automatic removal, service state), and
normalize a composite availability field where necessary; listing status alone does not prove buyability.
Unknown source enums, missing fields and wrong types fail closed. No default USD, two-decimal precision,
paid enum, title-to-platform inference or `attr_switch` blanket rejection exists.

`purchases` is keyed by goods ID and each descriptor contains:

```json
{
  "verification_ref":"<actual Admin/public buying mapping evidence>",
  "catalog_version":"<immutable capture version>",
  "captured_at":"2026-10-24T09:00:00+00:00",
  "platform":{"code":"ps","attribute_id":"21587","label":"PlayStation"},
  "quantity":{"unit":"item","minimum":1,"step":1,"group":"1"},
  "attributes":[{"attribute_id":"<real ID>","required":true,
    "values":[{"value_id":"<real option ID>","label":"<label>"}]}]
}
```

Optional SKU ID is mapped only when it really exists. Empty attributes explicitly means the verified
product requires no selectable spec; missing or unknown buying descriptors are unresolved, not guessed.
Quantity values remain integers in the currently supported core; fractional quantities require a separately
verified quantity mapping before use. Price is a display capture, never a final checkout quotation.
Snapshot publication metadata/hash and public route/auth separation belong to C/controller.

## Paid facts and attribution

`OrderMapping(verification_ref, fields, payment_states, currency_scales, mode)` normalizes raw order
facts with `normalize_order()`. The fields map must explicitly name site, order number, payment state,
paid time, actual received amount and currency. Mapping enum comparison is type-sensitive (`1`, `"1"`
and `true` differ). Paid enum mappings have no built-in defaults. Do not reuse the historical discovery's
`pay_status=2` assumption; controller's live source evidence controls the mapping. Currency precision and
source timezone are explicit, with timezone-aware ISO timestamps in normalized facts.
Applied benefits and actual line allocations must come from verified upstream use/readback records;
the normalizer does not turn a coupon catalog entry or percentage into an applied benefit.

`attribute(orders, bindings, refunds=(), mode='production')` consumes:

- `BenefitRef(kind, native_id, batch_id=None)`, kinds coupon/discount/campaign, exact case-sensitive identity.
- `AppliedBenefit(ref, applied_at, rule_version=None)`, actual application timestamp and version if supplied upstream.
- `Binding(activity_id,binding_version,rule_version,site_id,ref,valid_from,valid_to,page_id=None)`.
- `Order(site_id,order_no,payment_state,paid_at,paid,benefits,lines=(),mode='production')` and
  `OrderLine(line_id,benefits,paid=None)`; each `paid` is already actual received money, not gross before discount.
- `Refund(site_id,refund_id,order_no,amount,line_id=None)`, only settled actual refunds, using stable upstream IDs.

Binding windows are half-open `[valid_from,valid_to)` over **actual benefit application time**.
Payment must independently be valid; its timestamp cannot be inferred from coupon use time.
If the backend supplies rule version it must match exactly; otherwise immutable native identity plus the
explicit binding interval resolves the FS version. A binding without batch intentionally covers the whole
template/rule. Do not reuse that native identity for unrelated activities within the binding window.
Historical versions must remain in the binding registry; current coupon enablement does not remove old paid facts.
Any frozen-order/late-payment policy must be normalized from main-site rules, not retroactively guessed here.

Same native identity with overlapping binding windows/batch scope cannot target distinct pages or versions;
the core raises `AMBIGUOUS_BINDING_USE_ACTIVITY_GROUP`. A shared `fc27-season2` reference must use a group
binding (`page_id=null`), not three page claims. Distinct real benefits may hit multiple activities in one order.
No browser visit, customer identity, fulfillment/completed flag or behavioral event is required to count payment.
Preview and integration facts do not enter production totals.

Output contains one row per matched activity/order plus per-currency global/activity totals:

- Linked whole-order paid, refunded and net minor units are separate from allocated activity-line amounts.
- Basket scope `all/mixed/unknown` is separate from allocation `available/missing`.
- Missing line amounts remain null. An order-level benefit without line attribution cannot prove basket scope.
- Missing refund line assignment keeps activity net/refund allocation null while preserving linked payment/refund.
- Incomplete totals are null; `known_allocated_*` separately exposes sums of verified coverage with missing-order counts.
- Stable `(site,order_no)`, `(site,refund_id)` and line IDs deduplicate exact repeated facts. Conflicting copies fail;
  collectors must first select a consistent authoritative snapshot, not pass two changing versions as two facts.
- Global order/line totals deduplicate across activities. Never sum activity totals into a global financial total.
- Refunds cannot exceed original order/known line paid; original payment facts are retained. Unknown/orphan refund
  orders or lines fail rather than being silently dropped.
- Currency buckets remain separate; Admin converted USD and Order CNY cost are never combined. Profit computation
  is intentionally absent until a verified cost/currency/allocation contract exists.

`Money(currency,scale,minor)` uses nonnegative signed-64-bit minor units. `Money.parse()` accepts exact decimal
strings/integers only, validates configured currency/scale (0..6), rejects floats, excess precision and nonfinite
values, and never rounds through a binary float or Decimal context. Refund amounts are positive separate facts.

## Durable mutation ledger

`OperationLedger(path)` uses a dedicated persistent SQLite database, synchronous FULL, separate from the
100-item draft operation history. Provision its parent as a trusted private service directory (0700 on Linux),
keep the DB with the module's durable data/backups, and never delete/recreate it to clear an unknown action.
No automatic retention pruning is implemented. No credentials or raw customer payload belongs in this ledger.

`prepare(operation_id,payload)` persists canonical JSON, SHA256, timestamps and pending status. Payload should
contain action, exact target, before/after values and stable business references. The same ID with different
canonical content raises `REQUEST_CONFLICT`. IDs must be generated/stored before an operator can resubmit.

`execute(operation_id,payload,adapter)` atomically commits dispatched=true and unknown **before** calling
`adapter.dispatch_once` exactly once. A timeout, crash, malformed response or DB failure after the claim cannot
authorize a second dispatch. Concurrent workers and restarts return the existing operation. Only an adapter's
validated confirmed/rejected result changes that terminal status; confirmed requires an upstream reference.
Exceptions/raw responses are not stored or exposed. Adapter replies allow only state/upstream_ref/reason_code.

`reconcile(operation_id,adapter)` calls only `readback(original_id,original_payload)`. Missing/failed/ambiguous
readback remains unknown. It cannot reset the dispatch flag, retry or replace the operation ID. Even proven
rejection is terminal in this core; any future explicitly authorized new operation belongs to the controller's
verified workflow. The core intentionally has no blind retry, automatic ID replacement or reset API.

The supplied `MutationAdapter` has `enabled=false`. It calls no route, including `sales_auth.post_admin`.
Exact creation/edit/toggle/grant request and reconciliation mappings require a separate reviewed adapter.
Grant job polling by a returned job ID alone cannot resolve a timeout before the job ID was received; that
gap is not solved by guessing a batch lookup or enabling the write capability.

## Verification and limits

Run from `backend/`: `python -m unittest discover -s tests -v`.
Tests cover financial attribution/missing allocation, exact bindings, mode separation, money precision,
currency buckets, global dedup/refunds, pagination/scope failures, safe projections/CLI, canonical conflicts,
concurrent claim, crash/restart unknown, durable retention and reconciliation without retry.

B executed local tests on PC-20260909OJLI only. No production Admin/Order access, mutation, deployment or
real financial acceptance was performed by B. Production Python3.9 imports/runtime, actual field mappings,
service wiring, trusted publication snapshots and G2 transactions remain controller/integration checks.
