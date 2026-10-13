# FC operating analysis

FC reports previously summarized the requested period without sufficient comparison or order evidence. A single FC report now derives the requested period, preceding equal period, and (for one day) the prior same weekday and 7/30-day baselines from one existing FCDetails capture. Deterministic comparisons and platform/product/payment-band contributions feed a bounded DeepSeek interpretation.

Current problem orders can trigger a read-only Order sample: the existing authenticated browser and collector lock, three pages, twelve details, fixed FC/main-site/problem filters. Raw customer/account/log text is never persisted or projected to the model. Findings contain evidence references, hypotheses, concrete actions, conditions, risks and review metrics. Samples do not establish population causes. Historical current statuses are not historical end-of-day snapshots.

Private business context is scoped to the signed-in owner and effective dates. Remembered observations retain source snapshots and metric facts; old model conclusions do not become verified facts. Notes can be revoked and observation memory can be cleared. The scheduled FC report uses its own observation history, without importing a user's private notes.

## Existing boundaries

- FC first phase; other project summaries and both boss workspaces keep their existing interfaces.
- Existing auth, exact-range collector/cache, provider credentials, cross-process model lock and model-call ledger. No new provider or account.
- FC daily schedule remains 09:15 Asia/Shanghai for yesterday. Natural triggering after this release requires next-day observation.
- One provider call per analysis, at most 3,000 output tokens and 90 seconds. Unknown transport outcomes are retained and never blindly replayed. Missing data/model failures keep explicit gaps and deterministic facts.
- Paid-detail revenue and orders differ from the home dashboard's native summary metric. Main-site and configured owned satellites are separate. Reliable distributor attribution, source-matched costs, traffic and customer cohort dimensions remain gaps where unavailable.

## Validation and release

`python run_tests.py`, `node check_deep_ui.cjs`, then `python -m unittest test_release_workspace` from `frontend/`. The shared-provider-lock test requires Linux/root, and CI runs it in its isolated root-owned test context. Test dependencies are pinned snapshots and are never installed into production.

`deploy/release_navigation.py` extends the existing exact-target publisher to three changed and seven new backend source files. Its existing shared locks, baseline CAS, protected dependency checks and durable backups remain; a provider lock and active-report check prevent restarting current analysis. No credential, auth, timer, provider, boss or collection module is changed.

`frontend/release_workspace.py` narrows the existing native publisher to one immutable Advisor HTML and only the authenticated weekly index alias in the existing formal fragment. All home/navigation/boss routes and bytes remain intact. Inspection is the default. Apply requires the exact ready manifest SHA after CI; deployment acceptance requires real authenticated readback, not the local preview.

Rollback uses the matching publisher's `rollback --backup <recorded-backup> --approved-manifest-sha <recorded-sha>`. Restore the frontend first, then the backend while no report is active. Each rollback checks this release's hashes and refuses peer drift. Immutable history, model journals, reports and memory databases are retained; never restore an old SQLite snapshot or replay a failed provider request.
