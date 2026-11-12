# FC27 history-window recovery — 2026-11-12

Owner: DSH lead; branch `dsh/fc27-pricing-recovery-20261112`.
Baseline main: `8f2a6dee85dd9113cbc5674ae0237569103c13a2`.

## Evidence and minimal correction

187 read-only SSH inspection found the 16:35 cycle failing before live coupon
traces with `pricing_v3_business_history_source_incomplete`. ES identity coverage
was false with 2390 missing identities for 11-05..11-11 and 2859 for 11-03..11-10.
The selected latest ALL manifest covered 11-01..11-12. Passing its original query
to `archived_dataset` incorrectly applied today's 600-second TTL to closed history.
The same verified archive is readable through closed-range projection: original
production reader returned 6803 / 8106 rows respectively, zero parse/failed files.
No refresh or new collection was necessary for this proof.

Only `coins_evidence.es_metadata` changes: project ALL archive requests to their
selected dates. FC27 exact-export requests retain original bounds because that
reader only supports subrange projection for ALL archives. Live TTL, file/hash
verification, missing/partial coverage, order classification, financial constraints,
writer, original-ID reconciliation and all scheduling remain unchanged.

Production source SHA before change:
`a932baeb3af69e4de6b446d87621b6bff552027d53fcbb26020bfc4925462049`;
it exactly matched the branch baseline source.

## Separate regional/storefront fault

Region 21's original collector passed on PS/XBOX/PC at 17:22:48..50 Shanghai,
with USD, factor 1, verified locale and expected individual SKU identities.
This does not prove the cause of the 15:38 failure, nor full-cycle recovery.
The persisted failed-job summary lacks its public-rule trace. Earlier 429s are
not evidence of an Admin coupon endpoint failure; storefront currently reports ok.
No protections were relaxed and no unknown operation was reissued.

## Verification / delivery status

- Windows Python 3.9: 33 Coins evidence tests passed, including closed ALL range,
  live TTL retained, FC27 exact bounds, missing/partial retained; diff check passed.
- 183 Linux test: pending.
- Reader fix PR #1017 merged as `648af714480268b6f3f4e569afef70e8593f83e2`; PR and main push CI passed.
- Original V2 single-file adapter inspect refused `original_fc_execution_not_quiescent`
  because its legacy guard reports `all_sync_unconfirmed`. No apply occurred.
  Current V3 readiness already supports same-ID Order/Admin-closed evidence without
  changing business reconciliation state. Add the exact existing reader target as
  `fc-history-read-recovery-20261112` to that current adapter, keeping its queue,
  UNKNOWN, release locks, reader admission fence, CAS and rollback checks.
  Only the existing admission-fenced FS reader reload runs; FC sources use fresh
  subprocesses. No FC restart or timer changes are required.
- At 17:36 the current guard reported `job_running`: wait for the natural cycle;
  do not stop it or bypass admission to publish.
- V3 single-reader scope PR #1019 merged as `f368552f898eda3dc42c7f379e39b0ee3849820f`.
  PR CI `43196877894` and exact main push CI `43197249244` passed. Windows Python
  3.9 with Node: all 964 tests passed (18 platform skips), plus 33 reader tests.
  Its 56 release tests passed (one Windows skip). Earlier knowledge transport
  failures were isolated without weakening the actual builder refusal;
  the inventory now includes the already-current email-export ID.
  Transport tests use the last provenance-attested canonical snapshot; a separate
  unmocked CLI regression requires the actual HEAD build to refuse the real
  canonical/runtime mismatch without producing a bundle. No runtime baseline,
  provenance, builder protection or business rule was changed; knowledge publishing
  remains unavailable until its own attested migration. This release is reader-only.
- At 17:43:13..17:44:08 Shanghai a further natural retry failed with the same
  history error; at 17:45:23 the live source still matched the original SHA above.
- Applied the exact main reader bytes with the existing V3 publisher and manifest
  `babe4d4ff50ebe9550fe16e0751a8370a60df9d8c264418ec5b656a8bc35ed4c`.
  Receipt/rollback: `/var/backups/fs-navigation-20261006/nav-20261112T100730Z`;
  status `applied-awaiting-actual-http-role-acceptance`, one target, zero business
  worker/timer actions. Same-ID closed proofs were retained; no price POSTs.
- At 18:08:50 Shanghai the live reader SHA is
  `fc59f87f271f4c02e99d33c570f6e9fe29762bec1d83d198b8b4f7c1a33d7357`.
  Fresh production `_period_population` calls returned complete for both windows,
  missing identity 0, eligible 2159 / 2581. FC API/worker and FS reader/range active.
- Latest pre-release cycle 18:06:28..18:07:17 failed with the original history error.
  First post-release natural cycle `f1bbbb95-4245-52bc-afba-24c6c64381b6` ran
  18:38:49..18:39:28 Shanghai and failed `storefront_incomplete` before reaching
  the business-history consumer. Its competitor snapshot was ready (three valid
  competitors, costs valid, FX valid), but all public storefront rows unavailable.
  Therefore full automatic repricing is NOT recovered; this cycle alone does not
  provide end-to-end acceptance of the history fix. No manual repricing/timer change.
- At 18:41:33 a single request through the existing shared outbound reader, under
  the actual `fc27api` identity, returned None (the configured fallback signal;
  not enough evidence to distinguish upstream status/timeout). At 18:41:46 a single
  read using the existing direct curl route returned HTTP 429. No retries, new
  proxies, identity changes, risk-control bypass or degraded price validation were
  performed. Site/outbound availability remains the live blocker.
- At 18:11 Shanghai the read-only durable queue showed the failed cycle queued
  for `2026-11-12T10:37:17.926173+00:00` (18:37:17 Shanghai), attempt 3, circuit
  retry. An event-driven read-only job observer waits for completion; it neither
  advances the due time nor dispatches an extra cycle.

Publish only this existing reader through the original history reader release
adapter and its CAS/locks/backup/rollback controls, using committed main bytes.
Do not deploy the unrelated full V3 source bundle or use a general SSH hot edit.
