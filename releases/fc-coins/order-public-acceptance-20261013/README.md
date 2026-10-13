# FC Order / public price acceptance hotfix

## Goal and scope
Order B2C and the matching public selling price define coin repricing success. An ALL login failure before any price request must not undo that success. Preserve the real UNKNOWN, identity, policy, concurrency and public price protections.

## Baseline and source
Four exact active sources are mapped in SOURCE-MAP.json. The prior collector / ALL timeout hardening remains in its separate package. Other FC sources remain legacy-unreconciled; this package cannot replace the whole module.

## Acceptance
Only coin_auth_unavailable before any ALL ledger exists may become deferred_before_dispatch. The monitor requires the same original execution, confirmed Order prices and verified public readback. Any ALL ledger, rejected/unknown request, price mismatch, missing proof or policy change remains protected.

## Implementation
The writer preserves the original ALL authentication diagnostic and records zero dispatch; it never fabricates ALL confirmation. The existing monitor treats this proven case as a Chinese nonblocking warning. Player acceptance links to the coin execution; its sale-price verification remains disabled. Repair the changed-platform audit to include only selected platforms.

## Validation
Linux Python 3.9: 22 isolated tests, zero failures or skips, covering writer / proof / monitor consumers and exact four-target publication failures and rollback. Actual original-cycle Order and public reads confirmed; original Player category request accepted with sample count zero. No coin or ALL price POST during recovery. The future natural cycle and actual future auth-failure path remain unobserved.

## Publication
The existing publisher was extended with --order-public and four exact targets. Original queue/price/collector locks, SHA CAS, backup, atomic replacement and rollback remain. No service restart, configuration, strategy, price formula, schedule or permission change. Do not replay a historical manifest against newer runtime sources.

## Handoff and limits
Code and sanitized metadata only; no credentials, run files, backend response bodies, original production ledgers or live price data. This draft is source backfill; it does not merge or deploy a second time. Real unknown writes still require original-ID reconciliation.
