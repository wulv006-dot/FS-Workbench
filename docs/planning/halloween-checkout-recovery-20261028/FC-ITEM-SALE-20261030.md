# FC item sale reference prices

The seasonal FC item policy used raw `unit_price` even when the native item
already had a product discount. Read-only Admin observations and the native
Packs page on 2026-10-30 confirm Barcelona PS goods185753051, area21587,
quantity1, US/USD: unit105.38, payable percentage70, raw sale73.766, displayed
sale73.77. HWFC15 applies to that sale amount:62.70 before native payment fees.
PC goods185753123 is a separate quote:135.98 ->95.19 ->80.91. Historical
screenshots129.22 and99.43/69.60 cannot be assigned an exact SKU/time from the
available evidence and are not mixed into this calculation.

The explicit `native_discounted_item_display_total` semantics now also supports
game1327. It validates the product percentage, applies it once, then preserves
the native two-decimal `Number.toFixed(2)` contract. Legacy semantics, D4,
currency/quantity/specification guards and per-observation expiry are unchanged.
The raw `price` field is not treated as a second discountable unit amount.

The bounded43-model/129-SKU read was complete:18 SKUs from6 bundles had a70%
payable percentage;111 had100%. ModelIDs44839991,44839993,44839989,44839987,
44656527 and44656303 are covered by the18-SKU regression fixture.

Production activation requires a separate, scoped private-policy migration of
the existing43 site266/game1327 one-item `unit_price` entries to the explicit
discounted semantics, preserving their verified SKU lists/order, quantities,
currency, TTL and every unrelated policy field. This PR never writes Admin
product prices or coupon rules. Use the original publisher, shared release
lock, source/policy CAS, atomic backup and readback. Restart only the owning
campaign dashboard producer and let its policy-generation guard regenerate
reference prices; an initial missing-price interval is possible.

Before any version publication, compare draft/current/published and do not
publish an unrelated pending draft. A new supported release identifier clears
the already-open page's last-price fallback; otherwise report its actual TTL
boundary. Never restore an expired cache to simulate a fresh quote. Rollback
only this module and this migration's own policy fields under CAS, preserve
all business state, and regenerate prices. Returning to the former policy
means this price correction is not active and must be reported as such.

At authoring, only isolated tests and read-only observations have been performed.
CI, independent review, deployment and public readback remain separate evidence.
