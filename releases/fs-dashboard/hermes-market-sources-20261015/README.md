# Hermes existing market sources

Expose the existing FC27 Coins collectors to both the FS research tool and native Hermes Desktop. Scope stays at PS/XBOX/PC, 100K purchase tier, Lootbar/IGGM/U4GM/U7Buy, platform Order transaction cost, MMOEXP public product and BOC CNY/USD conversion rate.

`fc.query_market_snapshot({"profile":"FC27"})` uses the existing task grant and immutable evidence envelope. The native Desktop client `python3 -B /fs-source/market_snapshot_client.py` uses its existing Desktop identity against a closed loopback read route. Neither entry accepts URLs, paths, new profiles, refresh commands, SQL, code or write operations. No new credential, network permission, timer, collection or price change is introduced. The existing FC-detail OFF switch remains a live barrier.

All four families must belong to the selected collection run; source creation time selects the newest run, without falling back to an older success. Source times, units, file SHA, login state, stale/future status and missing fields remain explicit. Order record IDs and extra private fields are not projected. Unknown fixed/mandatory fees remain null; zero bonus remains valid. The 5% fee is a labelled user-provided analysis assumption, with production pricing policy unchanged.

`available` means existing source observations were readable, while `offer_completeness=partial` still blocks a claim of complete comparable offers or a concrete new price. Delivery method, coupon eligibility, mandatory fees, expiry and BOC publication time may be missing. This source is current market context, never historical paid-order COGS or reference-margin inversion.

The publisher extends the existing release gateway with exactly eight targets, per-file baseline checks, protected consumers, an admission fence, backups and rollback. It restarts only the existing FS worker and FS business process after quiescence. Desktop, collectors, navigation, permissions, pricing policy, scheduling, profile memories and provider settings remain outside this release.

Synthetic verification: `python -B -m unittest discover -s releases/fs-dashboard/hermes-market-sources-20261015 -p 'test_*.py' -v`. The existing isolated PR-fast Linux/Python3.9.18 dispatcher runs the two affected test modules. Runtime receipts and business evidence stay local/server-private; they are not part of this source PR.
