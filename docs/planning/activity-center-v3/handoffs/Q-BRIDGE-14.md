# BRIDGE-CONTRACT-14 independent Q

Reviewed code: `762955d5c80f24aea637639771c5b23868e5ebc9`, relative to `6e1515f3e60b9db8e8d82476fc38337ec4e431b1`. This includes bridge change `3a37853` and navigation/main integration `7747ea2403283c8373ae1af52a7a441595bff66d`. Q reviewed fixed Git sources; implementation files were unchanged during the offline checks. STATUS, G1-SCOPE-MATRIX and RELEASE-SCOPE-14 were reviewed as subsequent local documentation, not misidentified as part of the code commit.

## Conclusion and merge applicability

No blocking code finding remains in this reviewed delta. The previously identified partial native payload, HTTP-only success, legacy UNKNOWN false confirmation and repeated restoration risks are addressed within the stated contract. This is a code/offline review, not deployed FS bridge acceptance or permission to write business data.

The code is suitable for the user's conditionally authorized merge after the final PR head has the applicable current-main CI checks passing and contains no unreviewed implementation delta. The default private proof gates and false live capabilities must remain closed. A documentation-only final commit does not substitute its SHA for the tested code SHA; record both. No production write is needed or authorized merely to complete this code merge.

## Verified behavior

- Native requests derive all 28 fields from a trusted server read. Unknown fields/types fail closed; strings, integer zeros, monetary strings and time representations retain their exact types. Edit changes only the authorized text fields. Fresh hashes are checked before dispatch; original and expected rows are persisted privately and bound to the immutable request hash.
- A durable, original-operation/request-hash-matched HTTP 200 response with exact integer code 1 and a matching full readback are required for confirmation. Audit persistence precedes the readback. Code 0, string/bool codes, malformed/oversized bodies, timeouts and missing evidence cannot be promoted by matching current text.
- Existing UNKNOWN without the required snapshot and success audit stays UNKNOWN. The existing operation/object ownership and at-most-one dispatch rules survive reconnection/restart. A concurrent reconcile cannot release the object while a native response is outstanding.
- Restoration references a confirmed text edit with its original snapshot and successful audit. It uses current legitimate nontext values, including later time/status changes, and restores only original title/brief. Changed text, identity/scope or claim/use conditions block restoration. The original edit gets one durable restore owner at dispatch admission; UNKNOWN and confirmed owners remain reserved. Explicit not-started rejection releases only that operation's reservation. Invalid preflight requests do not consume the restore opportunity.
- Database storage checks enforce private POSIX ownership/modes and reject symlinks/hardlinks; snapshots do not enter public operation projections. The new restore action stays inside the existing authenticated admin POST and CSRF boundary and is rejected by the read action dispatcher. It adds no public endpoint or automatic restoration UI.

## Independent verification

Q executed 26 tests in `test_full_preserve_contract.py` and the Node backend action-boundary test: all passed, no skips. Q additionally ran four ephemeral synthetic checks without changing repository tests:

1. Pause a prepared restoration before execute; reconcile fences it as rejected/not_started. Resuming sends no POST and leaves no restore claim; a fresh valid restoration ID can proceed.
2. Simulate process death after successful audit persistence but before GET: restart can confirm the original operation by readback with no redispatch.
3. Simulate process death after the POST applies but before response audit: restart stays UNKNOWN even when the row matches, with no redispatch.
4. Oversized response: UNKNOWN, no post-response GET, no replay.

The controller/B supplied same-code results of backend 135, Node 103, publisher 25, six browser scripts, pr_fast selfcheck and 34-file Python 3.9 syntax checks. Q reused those broader results rather than claiming a second complete run. Local runtime testing is not a substitute for actual production Python 3.9/Node 18 execution.

## Upload and release inventory

Q inspected all 12 new blobs in the code range after excluding the already-reviewed previous candidate and existing main/navigation objects. New fixtures are synthetic; no actual coupon row snapshot, native response body, credentials or customer/order details were found. The prior excluded forensic history was not reintroduced.

The draft `RELEASE-SCOPE-14.json` contains 20 runtime source entries; all 20 SHA-256 values match the exact reviewed Git blobs. Its seven generated/integrated target entries are explicitly an inventory, not a prepared deployment manifest. It correctly has releaseReady=false and claims no current server CAS or generated payload hashes. STATUS/matrix/dependency text retain the distinction between code implementation, native-only evidence and actual FS acceptance.

## Remaining acceptance boundaries

- Client-side fresh GET/hash checks are not upstream atomic conditional writes. The FS ledger coordinates only its own operations. Any future authorized live probe needs an exclusively controlled object and no concurrent native/other-system edits.
- FS bridge deployment, actual Python 3.9/Node 18 behavior, existing ledger permissions/migration readiness, current native schema/shared-session behavior, and FS edit/readback/restore acceptance remain unverified. No actual object proof flags were enabled in this change.
- Coupon create/toggle/grant/revoke and other business actions do not inherit text-edit proof. Product buying contracts, money/time/refund normalization, activity-specific bindings and real attribution remain the documented G1/G2 gaps. G1 is not signed off and G2 is not started.
- A future deployment requires a fresh package, exact generated bytes, current shared-config CAS, backup and role/public-private readback. Preserve the merged navigation isolation fix and unrelated modules; do not reuse the old 57-item package as a new release.

Q performed no SSH, network request, native POST, merge, deployment or policy change in this BRIDGE14 review. Only this local review document was added; Q did not commit it.
