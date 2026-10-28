# Halloween checkout recovery — 2026-10-28

Owner: Codex. Scope: seasonal campaign runtime, its price producer and campaign configuration. Independent FC/D4 repricing is outside this change. No purchase order or payment may be submitted.

## Takeover

- Previous Codex task `主控 FS 双活动上线` (`01a16d0c-2eb6-77bd-883f-4b1fc5a07010`) is idle and explicitly stopped. Its last release was `nav-20261027T013850Z`; the existing native handoff and original 15 UID0 discount codes must be preserved.
- WorkBuddy task `万圣节页面优化与商品配置修复` ends with the requested handoff, PR615. Its checkout claims describe visible cards/prices, not an actual D4 cart/Apply acceptance.
- Original WorkBuddy checkout at `.agent_runtime/seasonal-media-20261028/wt` was clean, branch `buddy/diablo-docs-20261028`, head `d1f03cd9`. Do not overwrite it or the dirty outer workspace. This recovery uses an isolated branch.

## Independently observed before changes

At 15:32 UTC, both campaign services were active. Public configuration was still `campaign-preview-10`, SHA256 `de0696806d3f4d8bec16cb1604d2a19299f0ce3bdf912dc4c07c479fb16ffbfd`; center revision11 pointed to `campaign-preview-11`. Public Halloween already contained D4, the requested 500000M and five item models, with end `2026-11-08T23:59:59-05:00`. There was no pending center transaction. Preserve all FC page configuration when reconciling the pointers.

The price file was `unavailable`, zero products/contracts, at 15:29 and 15:33 UTC. D4 fixed reveal and option dialog worked, but displayed no reference price. Native main-site `/Diablo-4/Gold.html` identifies server attribute15943 as **Season 15 Softcore**, not the placeholder Standard; Eternal Softcore is11916. These are separate servers.

Exact Admin GET lookups through the current HMAC channel returned zero rows for HWD408/HWD410/HWD415. The same reader returned the existing HWFC10 record6029, with UID0/site266/game1327/pay90. Therefore D4's configured strings are not yet redeemable codes. No codes have been created by this recovery at this checkpoint.

## Source fixes

- Accept historical WoW `quantity_tiers` within its existing legacy roster, including validation of distinct amounts and units. No implicit draft migration is introduced.
- Refresh reference prices one configured interval before expiry. Keep unexpired prices visible during the next batch, and publish successful models when another model's observation fails. Each price keeps its original expiry; no TTL is extended.
- Retain the actual previous observation when using the existing freshness fallback, rather than replacing it with a failed/null observation.
- Public overlay drops expired prices per combination, while retaining validation of release, identities, choices, currency and quantity.
- Editor GET/HEAD starts a refresh without waiting for the multi-minute Admin batch. Mutation/publish behavior remains awaited.
- The open page's last-reference cache only bridges a same-publication refresh until the original expiry. Release/hash changes clear it, and an expiry timer removes the visible reference at its deadline. Existing independently verified native-cart fallback remains unchanged; a stale cached price cannot itself enable Buy Now. The browser regression covers same-context reuse, expiry without a fresh feed, and independent release/hash changes.

## Pending production work and acceptance

This checkpoint is source work only. Required CI and independent review must complete before this module is deployed or activity configuration is written. Use the existing publisher/locks/CAS/backups and current direct HMAC POST channel. Do not replay old launch65 scripts or create duplicates of existing codes.

Next: reconcile D4 three tier codes and native form serialization; correct verified server labels in the original catalog; publish current draft through the existing center with an operation receipt, preserving FC choices; then verify a clean isolated visitor session through game/reveal/options/native add/cart automatic Apply and payable amount to the payment-information screen. Do not submit an order or payment. Unknown writes require original-operation reconciliation.

FC model43042209 is excluded before drawing when it lacks a valid price/binding; the old handoff's `1/44` claim is incorrect. Its pack quantity must be verified against the native store before adding any price entry.

## Requested D4 artwork increment

The card background is the user's unmodified `Desktop/FC素材/D4/游戏卡片背景.png`, copied as `app/seasonal/assets/game-diablo-background.png`. The separate transparent wordmark derives from the official MMOEXP homepage card image `https://assets.mmoexp.com/images/202609/6dd0c1101c6e6e84bd6aa18bf50c428f181aa233.png` using the built-in ImageGen extraction tool; the original source remains recorded, and this is not a claim of pixel-exact cropping.

The page reads the existing static game-art configuration for the D4 background/logo, uses one unchanged `.game-shade` per game card, and keeps the logo decorative. Desktop and390px mobile screenshots were inspected; mobile has no horizontal overflow. Versioned script/style references prevent an existing month-long browser cache from retaining the previous card. The existing Halloween browser regression also checks the asset URLs and equal single-mask styling. The deployment candidate must update the existing live static manifest, preserving all unrelated entries, before restarting the runtime. No production artwork is changed by this commit.
