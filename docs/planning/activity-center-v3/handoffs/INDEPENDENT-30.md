# G2 independent closeout 30

The main-site pricing, ordinary-benefit compatibility and order/refund contract is deferred until the user's technical discussion on 2026-10-26. No further cart, coupon or payment experiments are needed to repeat the already observed ordinary cart flow.

## Independent work selected

Seasonal already submits its original selection through `runtime-bridge.js` and the shared standalone adapter. The runtime actually rejects not-started and expired/inactive campaigns. The bridge previously collapsed those known conditions into a generic verification error. This candidate adds precise messages for those two states while preserving unknown-operation priority. It does not choose an effective window, activate an offer, or change any purchase guard.

## Existing work reused rather than rebuilt

- FC and Seasonal page selection, published configuration, original-operation lookup and integration-test-only prepare flows already exist.
- Seasonal themes, fixed area, local demo draw/keep/refresh and demo invitation receipts already exist. Their probabilities, credits and dates remain demonstrations; they are not server-issued entitlements.
- `native-fc-contract.mjs` already projects a trusted saved FC intent to historical native fields. Activity and operation context remains separate. It has no network transport and does not establish current checkout compatibility.
- Product identity projection, benefit binding, paid-order analysis and explicit unknown allocation already exist. No new order scan or fabricated accounting mapping is required for this change.

## Stop conditions and handoff

The next real implementation dependency is the main site's authoritative activity layer, its allowed ordinary-benefit combinations, and order application/readback fields. Admin management access and a successful native cart smoke test do not establish those contracts. Seasonal identity/referral/reward execution also needs a real service contract; do not invent a service behind the existing demo.

The current candidate has one runtime payload: `app/seasonal/runtime-bridge.js`. Its direct synthetic test lives at `seasonal-source/tests/runtime-bridge.test.cjs`. This handoff is documentation only. No runtime publication or business mutation is authorized by this candidate. A later release must use the existing publisher and recalculate only affected manifest/version targets from the then-current source map and CAS; their hashes/counts are not frozen before that preflight.

Acceptance for this independent change: known not-started/expired responses display their precise reason on the existing verification actions; unknown operations still require original-ID reconciliation; live purchase/reward capabilities and all demo business parameters remain unchanged. Local synthetic results and CI/Q are recorded in the task receipt, not represented as production acceptance.
