# Seasonal statistics entry and coverage

The user's Chrome tab was verified at
`https://www.mmoexp.com/events/seasonal/index.html`. Its loaded tracker hash was
`c3406a9598d1202c2ff260bafa9ca5c43118a351c5b2422744b852466a5158a5`.
Read-only runtime status showed preview=true, enabled=false, connected=false,
transmitting=false, no saved event-consent value and no consent-choice element.
The existing formal-route check accepted only the directory URL, although the
index alias served the functional storefront. This is a confirmed collection
gap, independent of whether visitors would have accepted analytics.

The formal tracker now accepts exactly the directory and index.html routes on
the existing www origin/runtime mount. No other host or preview is enabled.
Unknown visitors receive a native accessible dialog, with equally styled Allow
analytics and No thanks buttons. Both choices permit shopping. The existing
same-origin choice is reused; the footer preference button can reopen it, and
storage events stop transmission after another tab withdraws or clears consent.
Without native dialog support the existing visible inline choice remains.
No login/referrer or unknown website-cookie state is treated as analytics grant.

FS separates the unavailable basic request layer from the opt-in behavior layer
and the existing dedicated-code paid-order revenue. Missing base metrics remain
null / not connected, never zero or inferred from PostHog visitors. Behavior UV
is described as session-identifier deduplication, not all visitors or people.

## Missing basic traffic source

Existing origin-log inspection was bounded to2MB, with no trusted real-IP
restoration configured. It cannot cover Cloudflare cache hits or establish real
visitor IPs. No authorized Cloudflare/Worker aggregate connector or export was
available. This change does not collect/store raw IP, add identifiers, change
proxy trust, credentials, permissions, retention or costs.

To complete that layer, the existing edge-data owner must provide an authorized
aggregate for the seasonal document routes: exact UTC interval, page requests,
daily distinct IP and separately computed full-interval distinct IP, together
with cache coverage, sampling and bot/monitor exclusions. Asset/API requests are
excluded; daily distinct counts cannot be summed into interval distinct counts.
No raw IP export is needed. Until supplied, the dashboard explicitly shows that
dependency rather than reporting a complete page-request or IP-visitor total.

## Validation and release boundary

Isolated browsers cover both actual entry paths, no pre-consent requests,
remembered refusal/grant, reopening and withdrawal, paused/configuration changes,
and synthetic native callbacks. All capture/cart responses in those tests are
intercepted fixtures, not production events or purchases. Context tests check
that absent basic traffic metrics remain null.

Production targets are only seasonal/activity-analytics.js, seasonal/event.css,
analytics/dashboard.js and analytics/report-context.mjs. Regenerate only the
affected static hashes against the current manifest, preserving every other
entry. Use the original publisher and shared locks after CI/independent review
and coordinate with the07:20–08:00 UTC capacity window. No registry, campaign,
price-policy, coupon, account or IP-security configuration writes are needed.

At authoring, this statistics change is not deployed. The independent FC price
release nav-20261030T064422Z is already installed; it is not re-applied here.
