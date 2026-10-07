# FC v4.2.1: real artifact manifest contract repair

Module: fc-coins. Owner: 吴律. Source-only candidate; production window belongs to the coordinating recovery task.

## Exact scope

This independent candidate copies the 26-file source artifact from frozen v4.2 commit b18b9e901e6265b3661559356e8de4ab9c301a8e. Only source/launch.py changes executable behavior; SOURCE-MANIFEST.json updates that one payload SHA. The other 24 payload files, including all five deployed business sources, are byte-identical. Original v4.2's 37 inputs and original QA workflow remain untouched.

The old launcher required exactly version/files, while its real frozen manifest also declares operation/business_replay. The correction requires the exact four fields, version integer 4, files dictionary, the single approved operation string, and business_replay exactly false. No fallback schema or arbitrary extra fields are accepted. Existing SHA, source closure, trust metadata, binding, adoption freshness, and transactional guards remain.

Source manifest SHA256: 8f97e23b3a63480fd8fd142ab977a85558203a7c7400739cb31186120b50c90f
Launcher SHA256: 874c0f6efba568a4068bb3fe9a4e3bde97189efe0ece166ed2b0aed1f72fc4d3
Historical v4.2 manifest SHA256: 540e45f50ec2357943fb5ffa5ffbeda349fe47546241198212b99a7c56ef147f

## Targeted native QA

tests/test_actual_artifact_contract.py contains 11 methods and 15 negative schema subcases. It reads the actual 26-file frozen package, reproduces the original failure with the real original inline launcher, starts the corrected real inline launcher with -I -S -B, and verifies SHA/closure/type/semantic rejections. No fabricated positive runtime binding is used.

The successful corrected entry test intentionally ends at FileNotFoundError for an absent private binding, after real bundle validation. It proves the repaired package entry, not runtime preflight readiness. The private auditor likewise refuses the absent binding and generates nothing. Tests require Ubuntu22.04/x64/Python3.9.18/root; no skips qualify as passing. They do not rerun historical57/41 or business tests.

Execution is PENDING until an actual authorized QA run is read back. Static construction or empty checks are not passing evidence.

## Actual private contract audit before production preflight

private_contract_audit.py is a reviewed external read-only controller, not part of the 26-file artifact. Execute with the actual server interpreter, -I -S -B, the new installed artifact root, and a freshly approved private binding path plus its actual SHA256. It verifies the real source manifest, actual metadata, exact bundle, binding's 38 fields, source/CAS closures, adoption receipts, interpreter, and fixed scalar contract.

It prints only status/counts/hashes or a bounded reason. It does not create a binding, renew timestamps, acquire locks, import runner/probe, make HTTP requests, write metadata, or claim the two real proof rounds. The normal full launcher preflight still must succeed using actual runtime state and readbacks before apply.

The collector and release controller are private server artifacts outside Git. Their exact bytes/pins, any hardcoded old manifest/root, current policy/job state and real private binding must be checked separately by the production owner; unavailable private evidence is not replaced with fixtures.

## Publication and recovery contract

Keep original frozen artifacts and private receipts. Construct a new artifact root and regenerate release metadata, collector source/root pins where present, and the separately approved runtime binding against this new manifest. Do not edit production business files for this launcher-only repair. Do not monkeypatch the inline entry or strip manifest fields.

Existing pricing, revisions, OFF intent, queues, ledger truth, readback rules and business writes are unchanged. Source commit, QA, merge, production preflight/apply and natural Player acceptance are separate events. No secrets, actual business state, server runtime configuration or receipts belong in this candidate.
