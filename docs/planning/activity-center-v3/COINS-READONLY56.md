# Coins readonly selection 56

Observed on PC-20260909OJLI, 2026-10-26 11:45 UTC, in the user's normal Chrome session at https://www.mmoexp.com/uk/Fc-27/Coins.html.

- Normal navigation succeeded, without a challenge. Selected PlayStation 4|5 and the displayed 1000K tier only.
- Quantity input `#inputNum.goldnum` has value `1000`, label `Enter Custom Amount (K)`, and `data-min=10`.
- Visible total: 1000 K, free bonus 50 K, receive 1050 K, EUR 70.37, discount -0%. This is an observed consumer display, not an activity-code quote or order result.
- Public inline configuration specifies site 266, game 1327, currency EUR, rate 0.8909, locale prefix `/uk`.
- Relevant loaded script URL: `/mmoexp-v250528/js/goods/mlb26-landing.min.js?1792999550`.
- The supported browser debugger reported that raw CDP was unavailable while resolving a paused document response. No alternate HTTP retrieval or restricted request was attempted.

The UI input proves the displayed K denomination only. It does not establish the Buy Now serialized quantity/group/attributes. EUR display and the public conversion rate do not establish the currency or calculation semantics of the earlier Admin `more.price[9]=86.8` observation. Neither value is wired as a verified live price policy.

No Claim, Buy Now, Apply, Checkout, login, cart edit, order, coupon creation, or production deployment was performed. Existing cart contents were not read or modified. The remaining source-level quantity and Admin-to-consumer price mapping need the loaded handler source or a precise technical confirmation; no real add-to-cart test is required merely to prove the visible selection.

The cumulative local candidate has separate user authorization to commit, push and open a PR. That authorization does not cover deployment or business writes. Production remains RELEASE42.

## US/USD baseline correction

The user subsequently specified US/USD as the standard comparison and identified a temporary UK/GBP regional promotion. UK observations above are regional samples only, never the standard base-price anchor.

The current normal browser page was independently read at `https://www.mmoexp.com/Fc-27/Coins.html?cy=USD`: header US / USD; public inline valuta USD, rate 1, locale prefix empty. Selected server element has class `area current`, code `ps`, game 1327, attribute 21587. Quantity is 1000 K, bonus 50 K, total USD 86.80, displayed discount -0%. This matches the earlier Admin tier value 86.8 for this one PS/1000K sample; it does not establish all currencies/models or future regional discount semantics.

Two attempts to open the region selector timed out at the browser Runtime.evaluate layer; readback subsequently showed the US/USD URL and values above. No fabricated URL navigation or request replay was used. The transition itself is not claimed as a successfully captured menu-selection sequence. Only its actual resulting page state is evidenced.

No Claim/Buy Now/Apply was clicked. The consumer cart serialization remains unverified. Future UK checkout must follow the main site's actual regional and code-application response; an extra activity discount must not be silently stacked onto a regional promotional price.
