# FC readback reconcile v3 draft repository scope and isolated QA

Preparation only, not a branch/PR/QA/production write authorization. V3 remains frozen for review of only RC03-v2/P1 timing, RC06-v2-A/P1 reused-stage fsync and RC06-v2-B/P2 source-directory fsync. V2 preserved;01/02/04/05 statically closed, final-job publication direction accepted. This new guide is outside its manifest. Proposed repository `wulv006-dot/FS-Workbench`, branch `codex/fc27-player-readonly-reconcile-20261006-v3`, main `5ed20c515dc2523fc9dd532e151a3afac4c43258`, base tree `fb4dfa1c125b1ca5c0736aa9836d0fa7f77dd47d`. Read-only verified main at 2026-10-06 22:47:50 UTC, full323-file tree at 2026-10-06 22:47:51 UTC; candidate destination and proposed branch absent. PR1–5 current changed paths have no candidate destination overlap. Recheck main, exact branch absence, open PR heads/paths and doc destination immediately before any authorized serial write; stale preparation cannot guarantee future absence.

## Exact positive payload

Add15 original-byte candidate files to `candidates/fc-coins/player-readonly-reconcile-20261006-v3/`, plus ONLY this guide to `docs/planning/fc27-player-readonly-reconcile-v3-20261006/README.md` (16 additions total, mode100644). No current323-file replacement, active source map, owner inventory, checker/Actions workflow or runtime adoption change. Candidate manifest SHA256 `faec9cd57bd866d5e433afef17bb61c5d550864a8a70f031e31c7effaa41ff8e`, all14 referenced inputs match. Source adoption stays legacy-unreconciled; commit/tree null until an explicitly authorized write and independent readback. The original E repository has no remote/staging/commit/push operation.

| Candidate destination | Bytes | SHA256 |
|---|---:|---|
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/CANDIDATE-MANIFEST.json | 1831 | faec9cd57bd866d5e433afef17bb61c5d550864a8a70f031e31c7effaa41ff8e |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/FINDINGS.json | 1076 | 93f4395f256b24978a878147314532a1620137cc5306a52a622fd4b425f08a64 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/README.md | 5484 | 9454b07a10494d7aa274091419cc0159800f6cdba3d48287e29199b3be9768f6 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/TEST-RESULTS.json | 1060 | b34222130859047c998273cdcda32d095620e20a3d608ad2d6b30ed25d8e183b |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/TEST-RESULTS.txt | 9729 | 5b58d7860d827677446cac145c365c377483dd0d6a5c5f32d52aaef21012f066 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/player_readonly_reconcile_guard.py | 4408 | 0756d29518adbeb0846431f03ce47933377ad5af2c5867cae7f326be1bb3eec4 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/probe.py | 4865 | 329c3bd28c7222a0a5639106d59bbdb7426a797557c84ef3b607d2daaed059b5 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/reconcile.py | 15445 | f1080c48a8252036eade870695b42c44c6bbe6f4387a563ca1d48f3f2f7421ca |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/runner.py | 8567 | 338601acda231c80deafb13889c8751ed9da93a2596a0a88f5bd5d6a75102a78 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/scope.json | 17899 | dabe12eb976ca86a3e0d4d57eb35a0a4f848697daaf08ec896b4c3604919d585 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/secure_fs.py | 9587 | 970d093c5bbf432777bdbb72d64ccf17cce0a87bd177450ad3a9b54ced7770ff |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/storage.py | 2979 | f66efe42df4c0c5a0fa9f6614a2b9c87bba33717dcc9dcdea484ee7f52c7ee0b |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/test_candidate.py | 26260 | ef7fdc87338fe680f6c99f14163ab71652a8ab6281120e55e588ebaed0a66483 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/test_native_linux.py | 8821 | 76d4946a5c359571864bde95a96e6e18e783ec4d8e6961787f4af56f4ccb56f9 |
| candidates/fc-coins/player-readonly-reconcile-20261006-v3/v2-to-v3.diff | 13487 | 28e8283aa1402f9e7bd2a1cd8f8cf2922f25a3c7c285f5e30dca52aa127a4e6a |

Exact16-file source paths/bytes/mode/SHA256/Git blobSHA1 are in the local proposed-git-files.json. This guide's own hash is listed there, not recursively embedded here. Do not recursively add the engineering archive or preparation directory.

## Dependency and data closure

Synthetic tests import only the candidate `reconcile`, `runner`, `secure_fs`, original pure guard, and Python standard library; `Storage`/probe custom runtime code is included for reviewed execution but not imported/executed through production main in tests. All8 Python files and scope/tests/manifest/results/diff/docs are in the15-file closure. No external fixture or third-party pip install is needed to run synthetic63/native13 tests. Test models1001–1005/products100000-series and all prices are generated .2/.3 synthetic values. No production session, runtime JSON, queue, price/quote, readback response or receipt is read by tests.

Fixed original Player `6aa0476a-a3bd-5ca6-b162-5695e3ed3396` and Coins `0b26528c-2964-4c49-823e-570254e5642a` in scope/tests are necessary identity/path/CAS boundaries, not replay instructions. Five real sample model IDs and30 linked product IDs, six fixed coin SKU identities, eight file SHA,12 source SHA, fixed revisions/quantity/gift vectors, exact trusted owner/mode/inode/lock metadata, host Python and immutable image/module identities remain necessary nonsecret contract bindings in scope. They contain no real market/model prices, credentials, raw ledger content or runtime proof records. Root's exact payload approval must expressly include those necessary bindings; removing/changing them requires a new candidate/review, not silently redacting frozen bytes.

Production reader dependencies are different from the isolated test closure:12 existing APP helpers and their source origins are bound by scope; Docker image `sha256:42d53d8c606491685f8a87db7bf6b0d1010c855464c37b8e37e7bbd45dd1dcda` freezes container Python3.10.12, session helper and requests/urllib3/playwright/certifi dependencies. HostPython3.9.18 full version/executable SHA and loaded custom module origins are pinned. These are prerequisites to later approved real readback, not source/vendor binaries or credentials shipped in this draft. No image install/build/transport or private-env copy is authorized. Hoststdlib files are not individually enumerated; reviewer/nativeQA must assess this runtime boundary.

Strictly excluded: preparation-evidence, real before/after/proofs/transaction files and raw jobs/audits/ALL/quotes/models/products/public rows/upstream/cost/order data, env/config secrets/API headers/session/cookies/keys/passwords, server bundles/backups, full HANDOFF/AGENTS copies, other PRs/RPG and current production business source edits. Narrative status in frozen README is a factual engineering limitation; it is not an uploaded raw production evidence payload. Heuristic credential scan is supplementary and cannot prove absolute absence of secrets.

## Python3.9 compatibility and isolated native QA command

Current local result:63 synthetic passed,0fail/error;13 native Linux tests SKIPPED on Windows/Python3.14.7. All8 Python files parsed Python3.9 grammar and compiled on Windows; this is not Python3.9 execution or Linux verification. Production host pin requires exact Python3.9.18 full version/binary SHA; substituting another Python3.9 patch version, Python3.10/3.12, or a rebuilt binary cannot satisfy production runner's exact scope. Synthetic/native test modules are designed for Python>=3.9 standard library; real target3.9.18 run remains required. Linux `O_DIRECTORY/O_NOFOLLOW`, descriptor-relative open/stat/replace, flock, ownership and directory fsync are mandatory for native primitives; native tests additionally require existing uid0/gid0 rights for temporary synthetic owner cases. There is no Windows fallback, dependency install, permanent permission change or runtime main call in QA below.

After root approves a named production-external Linux environment, legal input path and use of existing root/Python3.9, run from an isolated copy of exactly the frozen candidate closure. The following are prepared commands, NOT executed here. Replace the one path with the approved private QA candidate path; do not use the production artifact path.

```sh
cd /approved/isolated-qa/candidates/fc-coins/player-readonly-reconcile-20261006-v3
python3.9 -B -c 'import sys,os; print(sys.version); assert os.name == "posix" and os.geteuid() == 0 and os.getegid() == 0'
python3.9 -B -c 'import hashlib,json,pathlib; r=pathlib.Path("."); p=r/"CANDIDATE-MANIFEST.json"; assert hashlib.sha256(p.read_bytes()).hexdigest()=="faec9cd57bd866d5e433afef17bb61c5d550864a8a70f031e31c7effaa41ff8e"; m=json.loads(p.read_text()); assert all(hashlib.sha256((r/n).read_bytes()).hexdigest()==h for n,h in m["files"].items()); print("frozen14 inputs verified")'
qa_work_dir="$(mktemp -d /tmp/fc27-readback-v3-isolated-XXXXXX)"
TMPDIR="$qa_work_dir" python3.9 -B -m unittest -v test_candidate test_native_linux
```

The command must report76 run/0fail/0error/0skip for the current suite; every skip/failure is unresolved, never counted as native pass. Tests create only temporary synthetic trees, do not read production paths/import production API/start runner/connect/authenticate or access credentials. Keep isolated outputs as separately approved QA evidence; they are not part of this original candidate manifest. Do not delete failure evidence automatically, install WSL/Docker, upload a renamed/encoded old canceled QA ZIP, or use production as the isolated test environment.

Original ten native tests exercise parent symlink, parent replacement, tx symlink, untrusted owner, hardlink, file symlink, replaced held lock inode, real private file/dir fsync, stale checkpoint after staging fsync, and target directory fsync failure after rename. They are executable primitive checks, not a complete production consumer/concurrency/image/network or power-loss harness. Real fsync calls and injected errors do NOT establish survival after power loss; storage/hardware semantics and crash-recovery consumer behavior require separately scoped QA. Final publication uncertainty stays metadata_may_be_committed_needs_readback; no automatic rollback/replay or claim that the gate remains blocked after visible job rename.


V3 adds three actual SecureFS native cases: twice-failed staging file fsync then successful reuse, twice-failed tx-directory fsync then successful reuse, and source-directory fsync failure after rename followed by exact Storage.sync_visible retry of both directories. All13 native cases remain NOT_RUN here. Five added synthetic cases cover slow context60/160 deadlines and ledger durability retry/failure. Scope/runner/probe/guard are unchanged v2 bytes; no new production feature or consumer change.

## Precisely missing approvals

1. Independent v3 review acceptance of only the three v2 residual fixes; the final-job publication direction is already accepted. Review approval does not authorize a Git mutation.
2. Root exact Git write approval for this private repository/main/tree, named new branch,15 frozen candidate files manifest `faec9cd57bd866d5e433afef17bb61c5d550864a8a70f031e31c7effaa41ff8e` plus this single guide's exact hash from proposed-git-files.json, and creating a candidate commit/draft PR. Scope is16 additions only; no merge/production/Actions/permissions. Root coordinates one serial write window. Current latest instruction explicitly allows only preparation/read-only and prohibits remote writes, so general automatic FC repair authorization cannot substitute this confirmation. The user need only approve this concrete packet, not repeat approved local/diagnostic work.
3. Separate approved production-external Linux environment identifier, private QA directory/input transfer method and use of existing uid0/gid0/Python3.9.18; no environment currently available/selected. Git draft approval alone does not approve QA transfer or production use. Legacy canceled/refused QA ZIP server path remains prohibited.
4. After Git freeze/readback and legal QA, exact resulting head/tree owner吴律 confirmation and explicit merge approval under AGENTS standard chain. Before production, separately approve exact source commit/artifact SHA/fresh runtime CAS/transport/execution window. Neither owner repository-admin status nor an older governance/registration PR approval supplies this batch's approval.

Historical authority for this 2026-10-06 candidate: the then-applicable AGENTS.md required exact main/PR/owner/source/scope, independent candidate→commit/tree/test-input freeze→isolated QA→exactSHA owner/merge approval→separate source/artifact/runtime approval. The root request for that candidate imposed the immediate remote-write restriction. Source-adoption and old E no-remote/no-push restrictions applied to that candidate. If review changes its code/input, preserve frozen v3 and freeze a new candidate and new exact payload. Keep the reviewed hash intact. See [HOTFIX](../../ops/HOTFIX.md) for the current repository procedure.

Ready to hand back: this16-file draft packet is prepared, no branch/commit/PR/QA/production mutation performed. No further natural-cycle polling in this scope.
