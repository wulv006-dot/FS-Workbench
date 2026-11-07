# Quote expiry and recovery — 2026-11-08

Root cause: private QuoteView instances expire after 180 seconds of inactivity. Earlier views had no on_timeout render, leaving stale controls visible. Restart also removes their in-memory callbacks. Public category entries use persistent custom IDs and remain valid.

Released quote_panel.py only. Backup: /opt/mmoexp-fc-community/backups/quote-expiry-1794073186. SHA256: d1b1e98e2bf6d38dee9e95d200db9733a26e81f1758a79aa5480018b7588786b. Initial ready PID: 9561. Config and panel marker bytes unchanged.

All six categories share the fix: SBC, Packs, Gallery, Evolutions, Boosting and Coins. Each new private panel includes the persistent Refresh quote action. After inactivity, the old price is removed, ordinary controls are disabled, website link and refresh remain available. The compact title is “⏱️ Quote expired”, text “Tap 🔄 Refresh quote below.”, footer “Private”. Superseded views stop their timer so they cannot overwrite a replacement.

Verification: local full suite 178 passed; isolated Linux service-user quote + integration 34 passed. Tests include real Discord ViewStore dispatch fallback after timeout/restart, six-category routing, owner guards, expired token handling, and superseded view behavior. Production SBC live query after release: 81+ TOTW 1-8 Upgrade (Non-repeatable), PS5, $2.05 USD, only the requesting account can see it. Screenshot: visual-qa-20261108/sbc-refresh-live.jpg.

News was checked after the quote service restart: same batch 1, claimed 1, same EA and MMOEXP message IDs, no duplicate posts. All three services active.

Historical private panels created before this release do not acquire the new button. Reopen once from the public category card; no public messages or player history were deleted. Real three-minute inactivity verification passed: the SBC $2.05 price disappeared, the compact expiry title and instruction appeared, old controls became disabled, and Refresh quote remained enabled. Screenshot: visual-qa-20261108/quote-expired.jpg. Clicking Refresh quote after actual expiry successfully opened a new private SBC panel at 01:44, with active product/platform controls and the persistent refresh action. Screenshot: visual-qa-20261108/quote-recovered.jpg.


