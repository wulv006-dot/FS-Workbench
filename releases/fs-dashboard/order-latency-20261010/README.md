# Order margin follow-up latency repair — 2026-10-10

PR53 introduced independent Admin/Order shared 120-second caches. On the actual FC27 yesterday page, Order had been captured 2.688 seconds after selection, but the next client request was at 104.86 seconds. A partial HTTP 200 stopped follow-up and interacted with the 60-second UI interval/client cache.

This repair publishes Admin immediately and follows an existing pending source every two seconds within a finite 98/100-second client budget. Partial business responses cache for two seconds; complete results retain the existing client lifetime. At TTL expiry, a successful same-query coherent pair remains visible with explicit stale/update labels and original capture times, for at most 300 seconds since success. Different current-day cutoffs retain the preceding pair until both new sources align. New completed source omissions remain authoritative. Date abort and permission invalidation remain intact. Missing values retain null, genuine zero remains zero. The UI distinguishes queued, reading, deferred, failed, period mismatch, and a completed source that omitted a field.

The backend adds safe source phase and queue/read durations and aligns late Order retry with the cached Admin period. On a new current-day cutoff it renews both sources coherently. Source pools remain one worker each; four waiting selections, six new selections per minute, 120-second cache, 30-second failure cooldown, existing collector lock and timer separation remain. No upstream SQL, undocumented API, profit formula, FC costs, permissions, session, Worker, or scheduler changes.

Bounded source reads for two dates measured Admin 0.446/0.296 seconds and Order 3.385/3.191 seconds. Second Order queue wait was 3.368 seconds behind the first read. Native navigation consumed 2.308/2.154 seconds; DOM aggregation 0.065/0.059 seconds. Collector lock was acquired immediately. Cache hits took under one millisecond without new source reads. These samples do not establish upstream data freshness: sourceDataAsOf remains unknown. Order is the existing all-site aggregate supplement, labelled as a reference for estimated operation; no same-site API is claimed.

## Validation

Local: 23 backend/scope/retention tests, nine publisher fault/CAS tests, front projection/lifecycle checks, finite follow-up/stale-display tests, actual entry-reference checks, Python 3.9 grammar. Synthetic browser tests cover two cold dates, switch-back cache, Admin visible while Order reads, failure versus absent field, permission revocation, and complete home/analytics entry initialization. A first front publication omitted the runtime import; real URL QA detected it, and exact-CAS rollback restored the previous entry. The final package restores that import and includes full-entry regression evidence. Actual production two-date results and a complete automatic refresh after TTL are recorded in evidence/ui-after.json. No customer records or business amounts are archived.

## Publication and recovery

Use the frozen hashes in evidence/backend-frozen.json and evidence/frontend-frozen.json. Existing reviewed publishers retain exact allowlists, root ownership, shared locks, before/after CAS and durable backups. Backend scope is the existing single-file cache-fix contract and restarts only range service. Frontend contains 14 immutable assets and three existing mutable entry targets; ten assets are byte-identical to the preceding release.

Apply backend first, then frontend after its protected summary SHA check. Rollback reverses that order: frontend first, then backend, using exact approved manifest hashes and server-private backups. No database rollback, old immutable asset deletion, timer changes, or session/worker restart. superseded-stage-only records the first package that was only inspected and never applied.

Owner: current delegated upgrade task, protected-release publisher. Original E: checkout and peer worktrees are not edited or committed. Local archive is appended under the project planning directory after acceptance.
