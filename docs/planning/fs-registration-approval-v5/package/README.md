# FS registration/approval v5: standalone draft review package

This ZIP contains unchanged, SHA-frozen candidate code, source-bound tests and nonsecret evidence. No production configuration, group roster, password hash, native signing key, token/cookie or runtime DB is included. The four administrator names in the preserved policy are declared authorization-contract constants, not an exported account roster; all authenticated test inputs are generated in private synthetic temp sandboxes.

Independent v5 review statically closed RA4-B1 with no new P1/P2. Prior RA3-F1/F2/F3 closure remains. Recorded Windows Python3.14 evidence: **79 tests passed, 2 Linux-specific tests skipped, zero failures/errors; 10 real local browser checks passed**. This package does not claim independently rerun Linux or production acceptance. `releaseReady=false`, `uploadApproved=false`; migration/permissions and every production change require separate action-time approval.

## Verify and run without the original machine/repository

Extract into an isolated workspace outside a production checkout. From extracted package root:

```sh
python3 -B verify_package.py
cd candidates/fs-registration-approval/v5
python3 -B qa.py --output /tmp/fs-registration-v5-evidence
```

On Windows use `python` and an explicit temporary evidence path. All tests use relative local imports and caller-owned `fs-registration-*` temp databases. They bind only loopback when executing HTTP integration; no external network, existing user browser, htpasswd file or production service is contacted. Importing code creates no service/DB.

For an already configured Linux environment:

```sh
python3 -B linux_validation.py --output /tmp/fs-registration-v5-linux-evidence
```

Expected suite inventory is 81 methods: two Windows-only msvcrt tests skip on Linux; the two fcntl tests execute. Record actual counts/failures/skips; prepared tests are not a passing result. Windows instead skips two Linux-only tests. Python3.10+ with stdlib SQLite is sufficient for core tests; no pip dependencies. SQLite must support table_xinfo/index_xinfo. APR1/HMAC synthetic authentication is pure Python; no crypt/bcrypt/OpenSSL dependency is needed for these fixtures.

Optional browser QA requires the official `playwright` Python package and its matching Chromium installed in that isolated environment beforehand. Standard preparation, if separately authorized: `python3 -m pip install playwright` and `python3 -m playwright install chromium`. These commands contact package/download services; this task has not run installation or real external QA. Record the installed version. With existing dependencies, add `--browser` to qa.py. Browser sessions use fresh isolated profiles.

The preserved `archive.py` is a producer provenance tool referencing the original project's relative baselines; it is not needed for standalone execution. Use verify_package.py in the extracted ZIP. Its source is unchanged to retain the 22-file freeze. Source interfaces and exact native function dependencies are in INTERFACES.md; repository baseline/draft conflict precautions are in REPOSITORY-PLAN.md.

Do not run preview or tests against production storage, configure real groups/keys, deploy, merge, migrate real accounts, or reuse old FC sessions as part of this review. Original full source SHA are references, not current production SHA. The archive adds isolated candidate/document paths only; it does not replace root AGENTS, global policy or active portal.
