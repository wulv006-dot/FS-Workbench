# Proposed draft PR scope; no Git mutations performed

Repository supplied in existing project records: wulv006-dot/FS-Workbench. Reference main: **bc3b29531cec2fab3fc090385f3d7d126eb9ada7**. This task has not freshly read remote HEAD or the three existing drafts. That baseline is a preflight reference, not authorization to overwrite current main.

Suggested additions only:

- `candidates/fs-registration-approval/v5/`: unchanged isolated code and synthetic tests.
- `docs/planning/fs-registration-approval-v5/`: exact source/evidence/structure references.
- Package README/INTERFACES/REPOSITORY-PLAN content can be placed in that docs directory for the eventual draft. verify_package.py/package-manifest.json are transport verification, not production publishing tools.

Suggested branch if later approved: `review/fs-registration-approval-v5-20261006`. Suggested title: `Add isolated FS registration approval v5 candidate`. Proposed description: pending self-registration with explicit admin approval to global readonly; native source compatibility, same-name fencing, CSRF/session revocation and strict SQLite acceptance; 79 recorded Windows test passes, 2 Linux skips, 10 browser checks; releaseReady=false and all production migration/permissions pending. Do not create the PR until parent independent cloud tests and exact upload review complete.

Three existing drafts are reported by the coordinating task. Local latest handoff documents identify scopes as docs+NBA, D4 final guard and checker v2 links. No fresh PR numbers/branch heads/merge states are inferred. Before upload, read actual main and all three draft heads/file sets. Do not replay this old baseline as a full snapshot, replace prior payload files, force-push, or overwrite unmerged draft fixes. If scopes/heads differ from these records, stop and reconcile the observed state.

Candidate paths are new and distinct, but contract-level conflicts remain: historical FC-only/three-admin documentation must not override current global identity/four-admin contract; NBA's existing three-admin module guard is not changed here; prior global-auth candidate and navigation draft are not automatically integrated. The checker may reject new paths absent its allowlist, so separately review any checker manifest update against the actual latest checker draft, not an older main copy. No checker/AGENTS/global-policy/workflow update is included in this ZIP.

Only exact package-manifest paths/SHA may become additions in a draft. Recheck whether each proposed path already exists; an unexpected existing file requires current SHA and explicit reviewed delta, never blind replacement. No real account migration, approval permission grant, service restart, package install, Git merge or deploy follows from draft creation. Production source/current roles/Nginx/TLS/storage/migration/rollback gates remain separate.
