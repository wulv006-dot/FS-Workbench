# FC v4.2.2: nonroot stdin delivery repair

Module fc-coins; owner 吴律. Minimal runner-only payload repair. Production remains owned by the coordinating Chrome task.

Confirmed source of failure: the existing fixed image runs as fc27chrome, UID/GID11027 with groups11027/11028; root:root0600 input mounted at /run/reconcile-input.json is rejected with EACCES errno13 before HTTP. This evidence was relayed by the coordinator; no secret contents were read. Existing ledger/config group read contracts remain unchanged.

Source changes versus frozen v4.2.1: runner.py only, plus its digest in SOURCE-MANIFEST.json. The other24 payloads, including repaired launch.py and all business sources, remain byte-identical. Original v4.2/v4.2.1 inputs and QA workflows are preserved.

The root producer holds an already validated private binding and reviewed candidate bytes, serializes immutable bytes, enforces32MB before dispatch, and sends only through subprocess.run(input=raw). Docker adds -i with no TTY or inherited terminal. Bootstrap reads at most32MB+1, verifies length and the original SHA pin before JSON/candidate execution, and retains all candidate hash/closure/provenance checks. Input.json is no longer created or mounted. Existing ledger staging and secret readonly mounts, image/user, group11028, capabilities, security option, network and cleanup remain.

New source manifest SHA256: 42f4151547e2d96a3e7b7331b2bb69a59e9496a03590b29d6d47166ac60fcde4
New runner SHA256: c896137f14cea2bbdfc4f50d3b091090962f3664de8e39274f221f9f9a3bbaee
Launcher SHA256 unchanged: 874c0f6efba568a4068bb3fe9a4e3bde97189efe0ece166ed2b0aed1f72fc4d3
Prior source manifest SHA256: 8f97e23b3a63480fd8fd142ab977a85558203a7c7400739cb31186120b50c90f

stdin_transport_qa.py is one bounded10-check script. It uses the actual frozen manifest, real runner bootstrap and real probe/loader bytes. Native mode runs child processes under UID/GID11027 and groups11027/11028. Optional --image sha256:<existing-fixed-image-id> tests the same transport in the existing fc27chrome image using --pull=never and the original readonly/cap-drop/security/group/network contract. No root override, new account or persistent security change.

Checks: actual manifest/producer contract; recipient identity; old root0600 denial; stdin reaching the real private-proof guard; wrong/truncated/oversized input; candidate hash/closure rejection; original ledger/secret metadata read contract. A deliberately absent private proof scope stops before credentials/source/network reads. This is transport acceptance, not successful price proof or runtime preflight. Native config metadata is an explicit dummy model; Docker mode only stats/access-checks the existing secret mount, never reads contents.

GitHub QA is native UID11027 transport only. The private fixed production image is not copied/pulled into GitHub. Fixed-image acceptance must be recorded by the production owner on its existing authorized route; no historical server QA archive is resent. Do not count native mode as fixed-image completion.

Runtime tests are PENDING until actual logs are read back. Do not rerun historical57/41/11. Production needs backups, exact runner/manifest publication, private collector manifest pin update, new fresh binding, fixed-image transport acceptance and full two-round preflight before metadata apply. No price/queue/ledger replay, lock clearing, permission or credential changes.
