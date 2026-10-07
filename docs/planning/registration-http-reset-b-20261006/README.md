# Registration HTTP B-v4 evidence

This directory accompanies the minimal B-v4 source/test change. The original frozen ZIP and old test records remain historical evidence with their original bytes. The original PR5 Windows39 failure and exact10054 alias/packet attribution limitation are retained.

- Original PR5 source commit: `64028127dddd4b78e8ec1c0531a78c929f35c925`; tree: `6633d00bb96f6dc08ea5a3aaee2da660be1436b8`.
- New portal_bridge.py SHA256: `3b890b5edf873db7f5c73155cbf545d1d848f58d99b9a4f92a86a9eb61af38ed`.
- New test_http_content_length.py SHA256: `94c80e65408e84eac666c9c90ce6d76e088a25d357e18155f9ae632b82a50398`.
- Runtime/test input: [32-payload manifest](runtime-test-manifest.json). All30 other original runtime/test payloads and every original test retain their bytes.

The legacy rejection path now consumes at most4096 body bytes under a monotonic total1s deadline and sends Connection:close. B-CL-01 adds only bounded decimal-header normalization before int(): remove leading zeroes, reject values above4096 by string length/order, then convert at most four digits. The global Python conversion limit and authentication/CSRF/revocation paths remain unchanged. [Old B-v3 real HTTP exception](B-CL-01-v3-real-http-reproduction.json) and [B-v4 total-deadline probe](total-body-deadline-v4.json) preserve actual evidence.

One Windows full run on this new source SHA completed43 methods:41pass,2POSIXskip,0errors/failures,exit0 (old39 plus new4 methods/24 real HTTP boundary cases). [Rawlog](windows43-rawlog.txt) SHA256: `37b8e874511ac6eb02080517859f3ebbef8f7f7cfe2756e4217886b89eb56149`. [Summary](windows43-summary.json) records the unique run; no retry or replacement of the old failure record occurred. Cases include5000 leading zeroes,65518-character reachable header fields,4096/4097,large numbers,duplicate/invalid lengths and rejection before body read.

The [independent limited review](independent-security-review.md) closed B-CL-01 with no new confirmed blocking finding in that scope; [machine-readable audit](independent-security-evidence.json) independently matches the exact source/test hashes,32payloads and Windows43 rawlog. The parent supplied both artifacts and explicit authorization to freeze this branch; this is independent code-review closure and branch-freeze authorization, not Linux43 or production acceptance.

After the new Git commit/tree is frozen and read back, Linux must use this exact32-payload input and execute all43 methods with both POSIX methods actually running. A conventional command is `python -B -m unittest discover -p 'test_*.py' -v` from the runtime directory, in a production-external synthetic isolated runner. The runner, source manifest, command, exit/counts/rawlog and pre/post hashes must be preserved. The separate multiprocess4 harness/result is counted separately. Old Linux39 and private SQLite17 capability results do not substitute. The original byte verifier in docs/planning/registration-github-runtime-v3-20261006 verifies the historical original freeze; it is not an acceptance checker for this modified source tree.

releaseReady=false. No production upload,service switch,account/permission/configuration change,main merge or approval-setting change accompanies this branch freeze. Production integration and compatible revocation-preserving rollback remain separately gated.
