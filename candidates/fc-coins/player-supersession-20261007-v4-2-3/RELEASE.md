# FC current-input supersession hotfix v4.2.3

This archive records the exact emergency source supplied for production recovery on 2026-10-07. FC player coin quantities are routinely updated by an existing collection script. Historical failed-plan quantities must not be treated as permanently immutable inputs for a separate new player task.

Only `source/supersede.py` changes relative to the frozen v4.2.2 source. Its current model/public quantity and coefficient agreement checks remain. Historical sample product identity, current confirmed coin basis and independent backend/public readbacks, two stable proof rounds, metadata CAS, durable receipt publication, and existing task idempotency remain. The existing collection script, pricing formula, policies, queue protocol, and business writer code are unchanged. Historical failure fields and original completion facts are preserved; the old plan is never replayed or relabeled confirmed.

Source mapping:

| Item | Previous SHA256 | Archived SHA256 |
|---|---|---|
| supersede.py | 2d0f4188fd74c4b359c9855e3a8e5835cbf528284e252c63cb7032c4884abb8c | 088603ee7ef4430c22e3a9b0e954bfa68c93dc30bf7a27299a3961ca53874816 |
| SOURCE-MANIFEST.json | 42f4151547e2d96a3e7b7331b2bb69a59e9496a03590b29d6d47166ac60fcde4 | d8c60f5b7c4b9a8b7f9b2a6afd3da9167e36ae40cc368d7336d1a27bbff1f9d2 |

The other 24 manifest payload entries have identical hashes and Git blob identity to v4.2.2. The manifest differs by exactly one hash substitution. Original frozen v4.2/v4.2.1/v4.2.2 archives remain intact. This source bundle maps to the existing supersession artifact; it does not require republishing the unchanged business writer modules or creating another artifact directory. Private collector/audit manifest constants and runtime binding are maintained by the production owner, excluded from Git.

Production status was relayed by the coordinating owner: a new ordinary automatic coin cycle and its independent player child both reached confirmed; backend/public sample readbacks matched and the queue was empty with normal waiting schedule. This archive writer did not independently obtain the private final production receipt. It does not claim every player model was individually read back publicly. Final private backup locations, runtime IDs, logs, prices, bindings, and receipts remain with the production owner and the original engineering handoff.

Archive validation: exact single source hunk, old/new SHA256, exact single manifest substitution, immutable dependency blob closure, repository tree/path preservation and merged-file readback. No new QA workflow or historical-suite rerun. Local Python execution and local engineering archive are blocked by the execution helper setup error; no local test pass is claimed.

Follow-up: the user's ordinary-bug target is discovery to live repair within one hour. General fast-repair rules are assigned separately after this incident; no repository-wide governance changes are made here.
