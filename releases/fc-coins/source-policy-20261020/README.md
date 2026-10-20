# FC Coins source rule alignment — 2026-10-20

Status: candidate and offline tests only. Deployment and business readback remain pending.

## Current rule, expressly confirmed by owner at 12:38–12:39 BJT

Lootbar is mandatory. Use valid U4GM and IGGM quotes that are available, averaging gaps over the selected valid references. If neither is available, use valid U7Buy. If none is available, follow Lootbar using the existing own-base / competitor-delivered quantity basis with zero additional discount, regardless of the margin discount band. Keep verified delivery-type cost, profit floor, cent rounding, PS/Xbox shared-market guard and user OFF intent. Unknown cost is never replaced with a guess.

The previous mandatory IGGM check and “no reference means no quote” active behavior are superseded. Historical commits remain audit records only.

## Incident and bounded recovery

At 2026-10-20 12:05:15 BJT the natural cycle passed recovery preflight, then automation_policy.check_write raised KeyError("IGGM") before preview/request dispatch. systemd restarted the worker at 12:05:20. Original run b5ef086d-ec83-40d6-b7a5-9203b99679bd remains interrupted, with unchanged SHA256 0008ed4ce6b9a9a5070b0996e2b045ee4f94b477f22d52904a8633d62e043627. Requests, executions, ALL-sync and Player-sync records for that run were absent; no unresolved execution was found.

Scheduler permits only this exact audited historical digest, plus all existing no-write guards, to reach the next natural collection interval. It never marks the old job successful, clears a lock or replays its writer. A different digest, unknown ledger, write artifact, changed revision, or OFF blocks it. New source failures are typed and follow the natural interval, not a tight retry loop.

## Scope and checks

Three runtime files only: automation_policy.py, fc27_quote_engine.py, automation_tick.py. Before/after hashes are in targets.json. Publisher uses existing queue/price locks, baseline CAS, backup, API/worker restart, health and independent hash/protected-file readback. No persistent publisher privilege or Hermes sudoers installation.

18 focused tests passed, plus 35 existing natural-recovery tests. Tests include all eight reference combinations, precedence, no-reference parity in margin bands, invalid optional sources, missing Lootbar/cost, price tampering, profit floor, OFF, unknown ledger and exact historical audit digest. These are offline results, not a production success claim.

## Acceptance

After merged candidate deployment, read back all three hashes and protected inputs. Recompute a real collected quote with candidate code without writing. Wait for a fresh natural cycle, verify confirmed backend/ALL/public pricing and Player follow-up separately. Retain any interrupted/unknown state and diagnose rather than replay.
