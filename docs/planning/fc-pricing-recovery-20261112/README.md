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
- Restricted original publisher / source readback / natural cycle: pending.
- No production code modification, service restart or manual repricing performed.

Publish only this existing reader through the original history reader release
adapter and its CAS/locks/backup/rollback controls, using committed main bytes.
Do not deploy the unrelated full V3 source bundle or use a general SSH hot edit.
