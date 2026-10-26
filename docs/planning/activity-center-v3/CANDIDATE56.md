# Formal activity candidate 56

## Scope and runtime status

This cumulative candidate covers formal FC discount-code wording, four-game Halloween flip cards and approved assets, the existing products editor, draft/publish projection, bounded Admin model/associated-product reads, safe indicative-price projection, and the native same-origin discount-code handoff contract. It does not change the activity analytics data page or other modules. Production remains RELEASE42; merging this candidate is not deployment approval.

The public pages retain fail-closed gates: no configured business pool/probabilities/window means no real reward draw; no verified exact price policy means no invented price; no verified native checkout means no cart write. Synthetic tests do not establish real checkout or code application.

## Evidence reuse

See LOCAL-INTEGRATION53.md, REAL-PROVIDER54.md and PRICE-POOL55.md for tested layers and independent Q findings/fixes. COINS-READONLY56.md adds the actual UK page PS/1000K selection and EUR display, while explicitly leaving serialized cart quantity and Admin price semantics unverified. No private source responses, local session data, credentials or order/customer records are included.

Assets game-1 through game-4 are approved user-provided Halloween reference assets; max-guide is the approved brand mascot. Source material is preserved outside this repository. No runtime configuration is migrated or published by this change.

## Remaining launch dependencies

- Seasonal non-FC fixed models, random pool membership/rules, selected fixed discount tiers, probability/tier binding and effective window need final operating configuration. No equal-probability default is invented.
- FC 10% OFF and Beijing one-year intent are decided; exact creation payload, code names, usage limits and business writes still need the separately reviewed creation plan.
- Coins native serialized quantity and the exact Admin-to-consumer currency/price calculation must be evidenced before enabling that checkout or price policy.
- The reference anchor is US/USD. UK/GBP temporary regional promotion is not the standard base. The trusted projection now requires explicit US/USD and verified absence of regional adjustment; an isolated 1000K price match does not activate a production policy.
- Real code application, cart preservation, successful main-site response and cleanup require a separately approved bounded live test. Orders/payments are not authorized.
- Any release must freeze a module-only payload against RELEASE42, preserve concurrent/shared files, back up targets and perform readback. No whole-main deployment.

CI registration replaces obsolete Seasonal DOM tests whose deleted layout/demo-reward assumptions no longer apply with current four-game browser protection, and includes the readonly provider management regression. Existing draft/CAS, authorization and live gates remain required.
