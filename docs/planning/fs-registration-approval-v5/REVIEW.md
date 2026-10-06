# v5 schema acceptance: independent review entry

Final self-validation 2026-10-06T04:39:33Z: **79 tests passed, 2 Linux-specific tests skipped, zero failures/errors; 10 real local browser checks passed.** Independent re-review of RA4-B1 remains pending.

Independent code: `registration_approval_candidate_v5_20261006/`. `releaseReady=false`, `uploadApproved=false`. v2/v3/v4 source files remain frozen. RA3-F1/F2/F3 were statically closed by the independent v4 review; this revision addresses RA4-B1 only, with prepared local Linux tests.

## Supported structure and conflict policy

`schema_contract.validate` builds the exact expected schema in an in-memory reference DB and compares read-only schema metadata of the candidate DB. Supported versions: exact original schema2 and exact additive schema3 (`native_revocations`). It inspects every declared column (type, NOT NULL, default, PK order, hidden/generated flag), foreign key target/action/order, unique and primary indexes, indexed column/collation/order, index origin/partial flag, all explicit indexes and their predicates, required triggers and their exact SQL body. Table SQL tokens additionally preserve CHECK constraints, declared type/key clauses, expressions and literals that PRAGMA inspection alone cannot verify. Formatting and unquoted keyword case are normalized; quoted values are preserved.

Policy is strict: **extra triggers, indexes, tables or views are rejected**, even if apparently harmless. Required trigger removal or modification rejects. Implicit SQLite indexes are compared through index metadata; only reserved SQLite internal objects are excluded from the explicit-object list. Unknown existing structure requires an explicitly reviewed migration; there is no drop/rebuild/ALTER/data rewrite/automatic repair.

Validation runs before opening any existing Store for use, before synthetic interrupted-init acceptance, and inside the one permitted schema2→3 additive migration. Registry migrates only version2; version3 restart performs no repeated user_version write. Fresh initialization also checks its resulting structure. A conflict raises `ValueError` with a migration-required diagnostic and grants no session, role or service access.

## Local test evidence

`test_schema.py` covers same-version missing column, wrong type, removed NOT NULL/default/PK/unique/FK/CHECK, missing or modified partial unique index, missing/modified required triggers, an extra trigger, extra index/table/view, incompatible schema2 before migration, normal initialized restart and valid schema2 additive migration with a preserved pending row. Negative reopen cases compare every database byte before/after both Environment and direct Store rejection. A synthetic sentinel row also remains. No production data is read.

Final counts and tested-code SHA are in `evidence/validation.json`; raw unittest output is `evidence/unit-tests.txt`, individual schema negative cases are `evidence/schema-events.json`. `v4-to-v5.diff`, `manifest.json`, `VERIFIED.json` and three frozen baselines identify the exact candidate. `expected-schema.json` is a structure-only in-memory reference, containing no user/session data.

```powershell
# From the v5 source directory; all databases use synthetic temp sandboxes.
python qa.py --browser --output ../docs/planning/registration-approval-candidate-v5-20261006/evidence
python archive.py
```

## Local Linux validation path and current blocker

Read-only host inventory is `local-linux-runtime-check.json`: WSL executable exists, but `--list --verbose` exits1 with installation/help output; docker/podman/qemu/multipass/vagrant commands were not found. No callable configured local Linux runtime was observed. No install, external network, server QA upload or remote fallback occurred. Linux tests are prepared, **not passed**.

`linux_validation.py` refuses Windows execution. In an already configured local Linux runtime with this candidate directory mounted and Python 3.10+ available, run:

```sh
python3 linux_validation.py --output ../docs/planning/registration-approval-candidate-v5-20261006/evidence-linux
```

This runs stdlib-only synthetic core/HTTP/schema/recovery tests plus two real fcntl failure/reacquisition/child-contention tests. It skips the two msvcrt-specific methods and records skips explicitly. Browser checks are omitted unless local Playwright/Chromium are already installed and `--browser` is explicitly requested. Windows QA conversely skips the two Linux-specific methods, without calling them Linux evidence.

Real Nginx/TLS/ACL/directory-fsync and all production consumers, external native account creators, global original-portal logout enforcement and actual migration/restore remain separate acceptance work. No live source SHA is claimed. Production credentials/accounts/permissions/services/RPG/Git and deployments are untouched. Action-time approval is still required for every production safety change; another task's pending server-QA approval is not used here.
