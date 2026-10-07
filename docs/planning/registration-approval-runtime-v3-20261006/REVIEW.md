# Runtime v3: REGRT-P2-03 single finding re-review

Local isolated candidate, releaseReady=false. Original v2 remains frozen, verified against frozen-runtime-v2.json; v1 and six v5 vendor sources also remain frozen. No production auth/nginx/FC/account/permission/service/timer/credential/Git/RPG/NBA write. FC remains ahead in the production queue; registration is isolated only. Desktop-only acceptance unchanged.

Independent v2 report supplied by parent at D:/codex/2026-10-05/task-5/registration-runtime-security-review-v2-20261006/independent-review.md statically closes REGRT-P1-01 and REGRT-P2-02 within the supported storage/recovery boundary. It identifies REGRT-P2-03: old _route uses parsed.path.rstrip('/') while bridge recognized only exact /logout, allowing /logout/ to execute historical cookie-clear/FC logout without a ledger entry.

## Minimal executable change

Only portal_bridge.py changes runtime behavior. Its legacy logout check now uses the same rstrip('/') normalization as the real old route, after urlsplit and before delegation. At install, the old Handler._do_logout method is also replaced with the same safe guard, covering any internal old-route/direct-call path. GET/HEAD always redirect to /__auth/access/ confirmation with no cookie clear or false logout success; writes return405 and close the connection. The sole state-changing logout remains POST /access/api/logout with session, Origin and CSRF, atomic session deletion/native denylist and checkpoint update.

Static files and /access/API matching retain exact paths. No decoding/global route normalization, FC business algorithm, read scope, policy, storage semantics or consumer contract is broadened. Existing v2 runtime/storage/checkpoint/consumer/CAS source is byte-identical; qa/archive path changes and new isolated tests/metadata are infrastructure only. portal-bridge-v2-v3.diff is the complete runtime behavior diff.

## Actual-source validation

The original Handler over loopback HTTP with synthetic signed tokens now tests /logout, /logout/, /logout/// and absolute-form http://synthetic.invalid/logout/ with three query forms and GET/HEAD/POST. No legacy response sets a cookie; GET/HEAD location is fixed to confirmation; the native token stays valid before explicit authenticated logout, proving confirmation did not falsely claim revocation. A direct installed _do_logout call also uses the guard.

Case/percent-encoded/unrelated paths, a scheme-relative target normalized by BaseHTTPRequestHandler, and the separate /access/api/logout/ remain404 as in their respective real transport/router path. POST trailing-slash API logout remains404. The actual valid API logout with a next query string performs revocation and does not redirect externally. Following it, the same token fails installed original parser, adapter, actual status and verify; trailing-slash legacy aliases cannot restore it. The native denylist increases exactly once for the successful explicit logout.

Actual source main is also executed in synthetic globals through the CAS hook with a listener sentinel: insecure native configuration and missing registration store both fail before opening a listener. Original config/env/module main is never imported; only reviewed defs/classes run against disposable temp fixtures. POSIX tests for real private UID/modes, permissive file rejection and hard/symbolic-link rejection are prepared; Windows skips these, not claims Linux acceptance.

Final Windows self-validation: 39 methods,37 pass,2 POSIX skips,zero failures/errors; extracted ZIP repeats the same suite. See validation.json, unit-tests.txt and extracted-validation.txt. The expanded alias/method/query matrix lives inside the actual HTTP test, not 39 separate actual-user scenarios. No real account/session/token/cookie was read. Independent REGRT-P2-03 closure remains pending.

After single-finding independent closure, the prepared package can run full qa.py on a separately approved private Linux runner with synthetic htpasswd/tokens and isolated temp storage. This is not production account/permission activation. A private upload/execution must use the approved server access path and formal tool approval; no private Linux upload/run happened in this round. Do not use navigation/FC tests as registration evidence.

Existing release gates remain: effective nginx/all includes/forced trusted headers; complete player/cloud/business readonly query contracts and backend session isolation; every native creator fence; real existing readonly/four-admin acceptance; full exact-source deployed consumer HTTP behavior; fresh current-source/nginx/shared SHA and exclusive window; monotonic DB+witness preservation and formal action-time production approval. No production publisher is shipped.
