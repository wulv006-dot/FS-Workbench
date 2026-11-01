# Materials and scoped investigation: deployment acceptance

Business A is the sole implementation/publishing executor for this package.
Personal is the final reviewer and integrator. This record is separate from the
global plan and does not declare the whole A1/A2 stage complete.

## Initial observation — 2026-11-01 Asia/Shanghai

- Worktree: `E:/T3Code/sandbox/worktrees/FS-Workbench/t3-b5e4fe0a`;
  branch `t3/b5e4fe0a`; origin `https://github.com/wulv006-dot/FS-Workbench`.
- Clean at entry (`7ee41c0a506b75f04d933e8a4aa101c148a81a78`), then fetched and
  fast-forwarded to `fc77dd1b8743c8c54dd6c943fffa0fadfa6f30a2`.
- Read `docs/ops/HOTFIX.md`, `ui-system/README.md` and
  `ui-system/tokens/fs-tokens.css`.
- Default batch SSH to `root@47.85.224.112` failed with
  `Permission denied (publickey,gssapi-keyex,gssapi-with-mic)`; no remote command
  executed. Existing lawful connection details requested from Personal.
- Preview first failed to save its headless browser; one retry succeeded without
  installation or permission/configuration changes.
- Actual route `https://47.85.224.112/dashboard/fs-home/hermes/conversation/`
  redirected to the FS login page in the current default browser profile.
  Same-origin `GET /api/hermes/conversations` returned 401. This establishes only
  the unauthenticated rejection, not authenticated functionality or UI acceptance.
- No production modification, model task, business API call or deployment has
  been performed in this package at this observation.

## Sources and publishing boundary

Existing A sources are the conversation frontend and
`source/{conversation_files,conversation_http,conversation_store,conversation_file_bindings}.py`,
the core `source/conversation_service.py` seam, and the A2 context/tests/document.
B retains file-tool/material-evidence/B2 semantics and model routing. Shared
controller, HTTP host, tool schema/allowlist and publishing assembly require the
actual live paths and Personal's sole-maintainer registration before edits.

Historical targets identify `/opt/fs-hermes-fc`,
`/opt/fs-exact-range-20261001/conversation_http.py` and
`/var/www/dashboard/fs-home/hermes/conversation/`. They are **unverified live
targets**, not an approved manifest. The old conversation HTTP build template has
a 16 KiB Nginx request limit, and the old fixed V2 manifest omits the new file
modules. Neither historical package can simply be replayed.

Use the original publisher's release locks, fresh CAS, admission fence, durable
backup/readback and exact rollback. Active or unresolved tasks must retain their
state. Preserve all databases, products, receipts, UNKNOWN records, automation,
model/provider settings and credentials. Recheck live state before installation.

## Evidence required before final review

1. Fresh active source mapping, exact release manifest/hash, service/image paths,
   dependency availability and unchanged protected files; review/CI/merge SHA.
2. Small marked synthetic CSV and XLSX through the authenticated UI: raw upload,
   explicit binding, actual existing DeepSeek tool pagination, supported
   deterministic edit, immutable derivative with verified download bytes, and
   explicit next-turn follow-up. Keep original request IDs for unknown results.
3. Refresh/recovery, stop convergence and late-result behavior. A stopped local
   tool channel is not proof provider computation or billing stopped.
4. Real host identity/scope/checkpoint for frozen investigation. Missing genuine
   host scope remains unavailable; page/admin access alone does not establish it.
5. Authenticated positive access and actual available negative identities,
   owner/conversation/turn/scope isolation. Missing second identity stays untested;
   no forged authentication headers or new account/role grant.
6. Fresh viewed screenshots/recording with version, time, viewport, theme and
   step: desktop light/dark, 390 px, necessary 200% zoom; names/Chinese/tables,
   keyboard/focus/touch, upload/bind/send/stop/download/follow-up and recovery.
   Include relevant console/network errors and before/after fixes.

Current deployment manifest, authenticated task/file receipts,
provider usage/cost, deployed UI screenshots and final acceptance: **pending**.
No live model or scoped-data success is inferred from previous synthetic tests.

## SSH and source mapping update — 2026-10-31 17:20–17:25 UTC

The documented original identity `wulv_root_ed25519` successfully reached
`play187`; no new credential or SSH configuration was introduced. Read-only
metadata showed the worker, business range and Nginx active/running. The selected
active/unknown conversation and task state counts were empty; this is an initial
observation, not the publisher's complete quiescence check or a release fence.

The live material file/binding/helper/evidence modules are absent. Nine of the
thirteen selected existing source/static files match exact Git bytes:

| Live file | Exact Git source/version |
| --- | --- |
| `/opt/fs-hermes-fc/conversation_service.py` | `fc-pricing-v3-20261026/source/conversation_service.py` at `fc77dd1b` |
| `/opt/fs-exact-range-20261001/conversation_http.py` | `fc-pricing-v3-20261026/source/conversation_http.py` at `fc77dd1b` |
| `/opt/fs-hermes-fc/runs_contract.py` | `fc-pricing-v2-20261022/source/runs_contract.py` at `fc77dd1b` |
| `/opt/fs-hermes-fc/proxy_gateway.py` | `fc-review-channel-20261026/source/proxy_gateway.py` at `86b1f864` |
| `/opt/fs-hermes-fc/hermes_worker.py` | `fc-review-channel-20261026/source/hermes_worker.py` at `fc77dd1b` |
| `/opt/fs-hermes-fc/fs_inprocess.py` | `fc-review-channel-20261026/source/fs_inprocess.py` at `fc77dd1b` |
| `/opt/fs-hermes-fc/conversation_store.py` | `hermes-conversation-20261018/source/conversation_store.py` at `8facf0ac` |
| `/var/www/dashboard/fs-home/hermes/conversation/conversation.js` | this module's frontend at `8facf0ac` |
| `/var/www/dashboard/fs-home/hermes/conversation/conversation.css` | this module's frontend at `8facf0ac` |

Full remote paths, SHA256, Git commit/path/blob identities were sent to Personal.
Unmatched `controller.py`, `fs_evidence.py` and `range_api.py` are to remain
unchanged and protected by their observed hashes. The unmatched 5,776-byte live
conversation `index.html` needs a bounded read to preserve its current navigation
while inserting attachments. Batch SCP was rejected by automatic review as an
insufficiently authorized production-source export. No copy ran; no equivalent
transfer is permitted pending explicit approval and normal tool review. The
remaining requested export is only this HTML file into the worktree's ignored
`.agent_runtime/runtime-20261101/live/frontend/`, excluding secrets and user data.

The actual business process interpreter is `/opt/python39/bin/python3.9`, where
`openpyxl` and `et_xmlfile` are already available. The default `python3` probe's
missing-package result does not describe this service. The worker retains its
read-only `/opt/fs-hermes-fc` → `/opt/pilot` mount and existing profile boundaries.

Both existing conversation API Nginx locations still specify 16 KiB request
bodies. A narrowly scoped upload-limit patch is needed; no other locations or
the existing configuration's 0600 permissions should change. Shared active FC
service/HTTP/protocol paths and the incremental publisher wrapper have been sent
to Personal for sole-A registration before edits. The active FC pricing lane and
its original grants must remain intact. No deployment has occurred.

## Local assembly candidate

Shared ownership was registered by Personal at `b44c2c55`; the original A branch
then fast-forwarded the fixed integration/CI preparation head
`e18a5b71f88c7831d291e155e3b3390d637354fc`. The complete candidate is handed to
Personal by its fixed commit; it is not ready for production until integration,
latest-SHA review, required CI and merge are complete.

- The exact live FC v3 service/HTTP sources now consume optional `file_ids`,
  original attachment-aware request identity and A file bindings. Ordinary
  conversation dispatch attaches B's helper and static prompt. Pricing lanes
  keep their original stores/queues/grants; explicit file attachments there are
  rejected before reserving a turn. The active FC v2 protocol adds file tools;
  the 26-version proxy already contains the required B checks and is reused.
- `deploy/runtime_prepare.py` packs fixed Git bytes, independent of Windows
  working-copy conversion, and emits a payload manifest/hash. On-host prepare
  verifies that approved payload, exact existing/absent boundaries, original
  protected consumers and fresh hashes, then writes a **new private stage**.
  It changes no active target. Nginx is generated only by changing the two exact
  existing body-limit directives; all other bytes remain unchanged.
- `deploy/runtime_release.py` adapts the original frozen publisher without
  changing its file. Apply/rollback retain its locks, admission/provider fences,
  target CAS, private backup, durable journal and rollback primitives. Additional
  checks cover ordinary/pricing conversation UNKNOWN, task/tracking/learning
  state, current ownership/modes, current worker image and composed imports.
  The existing FC v3 `release_readiness.py` is packed unchanged and hash-pinned
  for bounded cold-start readback; no FC business helper in it is invoked.
- The original validator's `imageId` is a historical compatibility marker.
  `workerImageId` separately records/checks the actual running container image;
  neither packing nor publishing changes the image or its mounts.

Prepared command sequence (only after the final candidate is reviewed/merged;
use the resulting full SHA and fresh hashes, never replay an old stage):

```text
python -B deploy/runtime_prepare.py pack --repo <repo> --output <new-private-bundle> --source-commit <merged-full-SHA>
python3 -B runtime_prepare.py prepare --payload <bundle>/payload --output <new-private-stage> --source-commit <merged-full-SHA> --approved-payload-sha256 <pack-receipt-SHA> --release-ready
python3 -B <stage>/runtime_release.py inspect
python3 -B <stage>/runtime_release.py apply --approved-manifest-sha <fresh-manifest-SHA> --release-id <new-nav-UTC-ID>
```

Actual destination/source manifest, complete hashes, backup and execution
receipts will be recorded only after they exist. This sequence is not evidence
of installation. Fresh baseline must be within one hour at validation; all
locks/CAS are checked again by apply. Rollback uses the same stage's original
publisher and approved journal, preserving data and refusing unexpected drift.

Local checks at the `e18a5b71` integration base with the current A edits:

| Evidence | Result / boundary |
| --- | --- |
| Original `pr_fast.units` conversation tests entry | 30 passed, 0 skipped; includes four actual-version synthetic service/HTTP/proxy/file-loop cases |
| Original `pr_fast.units` deploy entry: `test_http`, `test_release`, `test_runtime_materials` | 16 passed, 0 skipped; new six checks use the existing external-network/process prohibition |
| Original FC v3 pricing route and isolated queue checks | Two selected checks passed; no live pricing task or business write |
| `knowledge_closeout.py plan` | Exit 1; old knowledge-layering tests still fail (`native_plugin_exact_registration_delta_required`, 30 errors/91 tests); no closeout completion claimed |

The pack unit injects only Git's byte-return boundary to comply with the original
offline runner; it never enables subprocesses there. Windows temp ownership/mode
and directory-fsync limitations are explicit in the fixture. Linux permissions,
directory durability, actual service import/readiness, real rollback and real
model/UI acceptance remain pending. No unchanged old test suite was rerun just
to imply new runtime evidence.

## Authorized HTML copy and authenticated entry

The user explicitly authorized **only** the named live conversation HTML copy.
Normal tool review allowed that bounded copy; the earlier 13-file refusal was
not retried or bypassed. The original remains exclusively at ignored path
`.agent_runtime/runtime-20261101/live/frontend/index.html`, verified as 5,776
bytes with SHA256
`3d79a5642f1517a8c1e414702c2b7491dc0ff4ed079c7d09895a3b1251045a24`.
`git check-ignore -v` confirms `.agent_runtime/` exclusion. The first copy attempt
failed because a local directory-creation parameter was unsupported; correcting
that parameter succeeded without changing identity or scope.

The maintained frontend candidate preserves the active navigation (including
marketing/activity entries), CSP, theme/token references and all other HTML
bytes, adding only the existing 661-byte attachment composer block. Removing
that block reproduces the live original byte-for-byte. Candidate HTML SHA256:
`6ee4a6f718e1759235648190f02c5d1c79332afa830baaa7893017048d70f604`.
The raw original is not a tracked source or release payload.

The user subsequently reported normal login complete. Read-only checks on the
existing user page returned `/__auth/verify` 200 with admin role and
`/api/hermes/conversations` 200 with the expected list shape. No cookie, password,
historical conversation body or production conversation screenshot was read or
exported, and no model task was submitted. The user page is kept open.

After the HTML change, the original Node DOM/fetch entry, local Chromium material
workflow and original no-attachment/stop browser regression all passed. The
browser fixture includes existing repository navigation assets and synthetic
authentication/data; this is not a second production identity or production
authentication test. New viewed local screenshots (1280 px light/dark and 390 px
dark) are under `C:/Users/ADMINI~1/AppData/Local/Temp/fs-materials-ui-uzab_mmk/`.
The local XLSX download was saved and compared byte-for-byte to its synthetic
source. These images/results are candidate checks, not deployed-version evidence.
Actual deployment screenshots, real DeepSeek pagination/revision/follow-up,
provider receipt/cost, stop convergence, second-identity negatives and 200% real
browser zoom remain pending after the integrated merge.

## First real publication and scoped worker repair

PR715 merged as `4077536449a3dcaa8871623989a15be3ead1552b`. The A branch
fast-forwarded cleanly and packed fresh Git bytes:

- Payload descriptor: `910b31d1989cf28c77bdf1fa033fceccfce65689988874dde596ff22d43f756a`.
- Stage: `/var/tmp/fs-hermes-materials-40775364-20261031T182821Z/stage`.
- Baseline: `2026-10-31T18:29:47.445727+00:00`.
- Manifest: `2e250d648631b09c911d909f3db0fb0216d96e06667b8a141e36504eb1c5505c`;
  13 targets, 49 protected files; source/protected CAS, modes and composed
  definitions import passed real `inspect` without active-file changes.
- Actual image: `sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`.

Real `apply` failed: `Hermes worker health failed after 60s`. The original
publisher restored all 13 target before-hashes (the four new code files were
removed by its journal rollback), and all 49 protected hashes matched. Backup:
`/var/backups/fs-navigation-20261006/nav-20261031T182821Z`. The journal is
`rolled-back`, SHA256
`813a72a21961c12bf981c8a0c095e11f38eacca4d92a08b16ffa2a540317ca06`.
The candidate Nginx configuration was never reloaded. No failed stage was replayed.

Both the candidate and restored old worker then failed in the same official
import chain: `make_adapter` → `run_agent.py:96` →
`hermes_cli.env_loader.load_hermes_dotenv` → `_load_dotenv_with_fallback` →
`PermissionError` for `/profile/.env`. Only filtered exception class/frame/path
metadata was inspected; the credential file's contents and metadata were not
read, and no credential, permission or account setting was changed.

Because that failed worker restart prevented the original publisher from
restarting the business HTTP process, A reacquired the original release/live/
admission/provider fences, verified the rollback journal and every before/protected
hash, and called the original DEEP restart. Original range health passed. This
restored HTTP service, **not Hermes**; the worker remained failed. Databases,
UNKNOWN receipts, old tasks and business automation were preserved. No real
model task or acceptance conversation had been created.

Personal registered the necessary single worker initialization seam to A at
`c6d4b8252bdc58e97feaec97cbf95a2d55f08ab8`. The repair is confined to
`fc-review-channel-20261026/source/hermes_worker.py::make_adapter` and its
FS-process-only official loader callback. It returns the official empty loaded-
paths receipt before importing config/agent modules. It does not patch `Path`,
the general dotenv library, filesystem permissions or Desktop/other processes;
unrelated initialization exceptions still propagate. Original FS runtime-config,
loopback provider, listener key, task token, model choice, tool registration and
Runs lifecycle remain unchanged.

Non-sensitive AST inspection ran in an ephemeral, read-only, network-disabled
container of the **existing image**, with no profile or secrets mounted:

- `hermes_cli/env_loader.py` SHA256
  `da921984d4cd690bbb9813c6431ecc88b18b46307800d155c86e25c8e45ccee1`.
- `run_agent.py` SHA256
  `9fca746dde685859ed084d6f7651a94d8849e8944a145de77f8a177c839cb5ac`.
- Public loader signature: keyword-only `hermes_home=None`, `project_env=None`,
  `load_external_secrets=True`, returning `list[Path]`. The external-secret
  switch does not disable profile `.env` loading; no profile-load skip parameter
  was found. `run_agent.py:96` calls it at import with a home and project path.
  The source hashes/signatures are the observed runtime basis; the worker's
  declared API PIN is not used to infer an unverified upstream checkout version.

The next candidate adds the exact worker file to the existing package target
set (14 targets, no new writer). A new merged-SHA payload/manifest/stage and
normal review/CI are required; this record does not authorize replay of the
failed 13-file stage. Real worker startup and the material/UI/model acceptance
remain unverified until that controlled publication succeeds.

The scoped repair's original offline runner passed conversation 32, deploy 16
and channel 12 tests with zero skips. The two added worker cases reproduce the
old refusal, execute the actual adapter constructor with injected official import
boundaries, check original config/loopback/token/model/tool/Run contracts, and
verify unrelated initialization errors propagate. They do not prove a real
container startup, provider call, production authentication or material workflow.

## Failed-worker recovery preflight (after PR716)

PR716 merged as `ac58cf7f854fb4e9548db47228a110e725f99d81`. A fast-forwarded
cleanly and generated a new LF Git pack, descriptor SHA256
`78aa52177a57d3fd33dd7fe728e2d77996b4be9403fde5b9a4eabb7ba1f2e1fe`.
The new private directory is
`/var/tmp/fs-hermes-materials-ac58cf7f-20261031T185510Z`. Real `prepare` stopped
before stage creation or active-file writes: `docker inspect fs-hermes-fc`
returned `Error: No such object: fs-hermes-fc`. This is **not** a new worker
startup failure: the merged worker repair has not been installed.

Read-only observation confirmed the original unit uses `--rm`, `Restart=no`
and the complete fixed image ID
`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`.
The stopped worker's container was removed; that exact image is still locally
present, as verified by `docker image inspect` without a pull. The effective
unit has no pending daemon reload and exactly its existing isolation drop-in:

- `/etc/systemd/system/fs-hermes-fc.service` SHA256
  `94b9cf19547ad0a4b68307ea35d4f5317fca0136048b90d78d5f9cea1dbaf011`.
- `/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf` SHA256
  `2a4eeada8c0acd27db04aa14838af7cc5c7fe3355677581d53f1f3509c74321a`.

The recovery candidate retains the frozen publisher's exact bytes, all 14
targets, 48 protected files and four new modules. Only pre-install observation
can accept an explicitly missing container: a successful empty exact-name
container listing, the two exact root-owned safe unit hashes, current
inactive/failed state, exact effective fragment/drop-in paths, no daemon reload,
and the actual locally installed fixed image ID must all agree. Other Docker
errors, active/activating-without-container, unit drift, additional drop-ins or
image drift fail closed. Existing containers always supply their actual image.

The manifest now separates `runtimeBefore` (the observed baseline, including
the failed/inactive worker) from `runtimeRequired` (all three services active
after publication), and records `workerImageSource` as `container` or
`configured_unit_and_local_image`. The latter is **not** running-container
evidence. Before restart, the adapter passes the explicitly recorded baseline
states to the original guards; it does not pretend the worker is active or omit
worker protection. State/source drift is rejected during inspect and every
installation guard. On entering restart, that recovery allowance ends. Success
requires the real container image, original bounded health probe and original
guards with all services actually active before Nginx reload. Restart errors
still propagate into the original journal rollback; the previously documented
old-HTTP recovery procedure remains available if the old worker cannot restart.

The unchanged offline runner command passed 19 tests, zero skips:

```
python -B -c "from tools.pr_fast import units; units('releases/fs-dashboard/hermes-conversation-20261018/deploy',['test_http','test_release','test_runtime_materials'])"
```

The added contracts cover real-container versus strictly missing-container
observation and the original inspect/apply/journal lifecycle with injected host
process boundaries: failed baseline CAS, active success, startup error, missing
container after health, stopped service after health, and byte-exact rollback.
They retain the original runner's subprocess/network denial. During development,
one pre-existing HTTP socket assertion encountered Windows `WinError 10054`;
the final complete invocation passed without changing HTTP code. A temporary
test-fixture reuse error was corrected before that final run. Linux permissions,
actual recovered worker startup, production material/model flow and deployed
visual acceptance remain unverified. No old stage or descriptor was replayed,
no container was fabricated and no config/permission/credential was changed.

## Second real publication: systemd 219 readback compatibility

PR717 merged as `ba972abbba87f4afd9f18374faf6ed6ccff61ec1`. A fast-forwarded
cleanly, generated new LF Git bytes and prepared a new stage:

- Payload descriptor SHA256:
  `07287dcdaf9008df2b87789eaf1c2bfc5c4516223c8e5a0005558e2c0f21a868`.
- Stage: `/var/tmp/fs-hermes-materials-ba972abb-20261031T191240Z/stage`.
- Baseline: `2026-10-31T19:13:06.830141+00:00`; worker really `failed`, image
  source `configured_unit_and_local_image`, exact original fixed image present.
- Manifest SHA256:
  `f5187838dea263cf4951255f4221bb0f80585fadf9b6e7c5293bab4e0fc78d9d`.
- Real inspect passed all 14 target/48 protected CAS checks; worker before-SHA
  was `8c377abb19da520df2f92e02e0523430dd53fc1be2f1eac8c47c3f6de35854e9`.

One controlled apply reached post-restart image observation after the original
health routine returned, then failed because the installed **systemd 219**
rejects `systemctl show --value`. This does not establish successful publication:
the publisher rolled back all 14 targets (including removal of four new files),
and the restored old worker could not start. The Nginx candidate was never
reloaded. Backup: `/var/backups/fs-navigation-20261006/nav-20261031T191240Z`;
journal `rolled-back`, SHA256
`16899358bdd37050f36534f5623b3ad1400f2673ecdaf679f9576558e0fd3a88`.
All before-hashes and all 48 protected hashes were independently verified.
Ignored local copies of the manifest/journal retain these exact hashes; no
production source/configuration or database was exported.

After the apply process exited 1, A reacquired the original release/live/
admission/provider fences, rechecked the rollback and every before/protected
hash, then used the original DEEP restart to restore old HTTP health. No file,
credential or permission change was needed. Current HTTP/Nginx are the old
working version; worker remains failed. No real model or synthetic acceptance
conversation was submitted, and the user page was not operated on.

The compatibility correction only replaces `--value` with the original-style
`-p ActiveState` key/value parser. That exact command was verified read-only on
the real host (`ActiveState=failed`). The live-container contract now explicitly
checks the command and returns the systemd-219-compatible response shape; the
complete original deploy runner passed 19 tests with zero skips. Missing-
container recovery, actual-container postconditions, original guards/rollback,
health, modes and all other protections remain intact. A newly merged SHA and
fresh pack/prepare are still required; neither failed stage will be replayed.
Material/DeepSeek, real download/follow-up and deployed visual acceptance remain
unverified.

## Successful software publication and real synthetic acceptance (1f8ddc57)

Source commit: `1f8ddc57c37e16df7c802de358eefb6585d078ee`. Fresh LF payload descriptor SHA256: `346d3b5659593a5b78a5043fd7c4ec717e0f3824815bef83ba024620bd010014`. Stage: `/var/tmp/fs-hermes-materials-1f8ddc57-20261031T192312Z/stage`; baseline `2026-10-31T19:23:40.580450+00:00`. Manifest SHA256: `b129179049dc9ff4b575075ebd1b47c1f6edf325936ac70b1286ca990bd73a05`.

One apply succeeded as `applied-awaiting-actual-http-role-acceptance`. Backup: `/var/backups/fs-navigation-20261006/nav-20261031T192312Z`; journal SHA256: `c902e8f3d1d613c80f1f0573647dbcf17184466579fdfbc77539d8f8846c24fc`. Independent readback verified all 14 after-hashes, root:root and exact modes (Nginx 0600, others 0644), plus all 48 protected hashes. No DB/UNKNOWN/old-task clearing, account, permission, credential or business change. Earlier failures remain recorded above.

Actual container image: `sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`, Running=true. Worker, range and Nginx were all active/running; original authenticated worker readiness passed during publication, range `/health` returned 200/ok=true, anonymous worker capabilities returned 401. Nginx reloaded only the two approved 16k-to-10m edits. Normal browser auth returned 200, and normal same-origin conversation creation returned 201 with only `conversation_id`.

| Active target | Verified after SHA256 |
|---|---|
| `/opt/fs-hermes-fc/conversation_store.py` | `06fedb9887d4b23a4f0ae347cf91d1b8271f6165e7640ea457ddacd729ce92c9` |
| `/opt/fs-hermes-fc/conversation_files.py` | `b985a1db31c9eb0c9a29dc525345425a01797201b0388626f13699880402949a` |
| `/opt/fs-hermes-fc/conversation_file_bindings.py` | `45e2933dc2fa9a90c77926b952fe97a7c61fe51ce68ced0df64733a4545729c7` |
| `/opt/fs-hermes-fc/conversation_service.py` | `27856bb29b47de56518789da418cb9ebdb0ddf7f65082803ef2b7f47df5841ad` |
| `/opt/fs-hermes-fc/conversation_file_tools.py` | `4bde6f456bea2802c379b88467102cf9517c401ce2531d1238e24929dc38a5a8` |
| `/opt/fs-hermes-fc/material_evidence.py` | `d2e4cd3e3ffdbab6876c4754098ec0a603685f3657f8d732cbf18b9b7b4226b4` |
| `/opt/fs-hermes-fc/runs_contract.py` | `af9239b015f63f0501e5c03972c063a6b506c395130325b24df2497fa2341865` |
| `/opt/fs-hermes-fc/proxy_gateway.py` | `7d9b05ea2c2000680a9e1a7138255a7ac34c76b3f73b13c3f84a8f7641cbbf3d` |
| `/opt/fs-hermes-fc/hermes_worker.py` | `82992ce7c94ba220781afc36be6673bb75059e63a2e3de09e7c99c8098b55415` |
| `/opt/fs-exact-range-20261001/conversation_http.py` | `6a10a4360d3fa090b88994fdd91c56ecb3c18bc25935bd41eb8c6a6675fc3261` |
| `/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf` | `b792f18b8d1b322139f8be96bb5052ff53a79e82dac7a607cbe102e199b06302` |
| `/var/www/dashboard/fs-home/hermes/conversation/index.html` | `6ee4a6f718e1759235648190f02c5d1c79332afa830baaa7893017048d70f604` |
| `/var/www/dashboard/fs-home/hermes/conversation/conversation.js` | `73082f8f663a4ffbb2e0b0b9041343bee4a70285bdcdf84214e31e4ed51d0a50` |
| `/var/www/dashboard/fs-home/hermes/conversation/conversation.css` | `c4a5fd9b937343572465ea477b309f0110b458774b23efcabb4a06d6521c43f7` |

### Synthetic tasks, provider receipts and immutable downloads

Only synthetic conversation `0884f9a7a4ee4b66a220e20651e4e54c` was exercised. Read-only review URL: https://47.85.224.112/dashboard/fs-home/hermes/conversation/?conversation=0884f9a7a4ee4b66a220e20651e4e54c . The original user page was preserved; the A acceptance tabs were closed when those checks finished.

| Turn / task / run | State and observed provider calls | Prompt / completion / total tokens |
|---|---|---|
| `0f708fcf56a0497784d70a3290f7d1bf` / `efae1d897b2d494816ca594eb519b953` / `run_2dd4e5a96cb44a859732e9779fd40e31` | completed; 5 recorded calls | 475029 / 1614 / 476643 |
| `2f5efc7bde8b419786b3649d42b4a542` / `9c511c44d5f9df7a1a87efccb31c7a7a` / `run_c4c684cb55b742f9ac83837dc96f0cb8` | completed; 5 recorded calls | 501953 / 1057 / 503010 |
| `6cfcaf9df1624b61a17e4fce8b1f77ca` / `8dbb2ecf07b4a72976b59f2429592874` / `run_8261315a1a3340708ffdabe7619cb8ff` | completed; 1 recorded calls | 102739 / 3 / 102742 |
| `611dc5c87a5a4ebe9345d73509311ace` / `b85b7c6a8faa990fe992fe5c537a2dcc` / `run_990498b4bfe74715a00fbf30522e18b7` | cancelled; 1 recorded calls | 102770 / 3 / 102773 |

Calls used the existing DeepSeek channel; receipts independently record requested/response model `deepseek-flash`, forwarded_verified=true, actual_backend_version=`unknown`. Invoice amount and `cost_microcny` remain null/unknown (`amount_unknown_no_cny_invoice_or_fx`), never zero or a currency estimate. Five successful provider receipts belong to each material task, not to all acceptance work; each no-attachment/stop task has its own single recorded call. No provider/model/budget or quota setting was changed. Representative first-task provider request IDs: `0d131993-f2d6-405e-bc2a-9cf820109574`, `9edea579-71a2-46b5-9d2b-dd8c92199c1b`, `0ecdbdd3-e2f4-48ee-8739-fef9a8e8590c`, `5270c9b5-5d28-4c26-877a-1400a65419b9`, `75ba19d8-26f2-4bc6-ad35-fcdbd8b25a83`.

| File | Full file ID | Full SHA256 | Bytes / parent / version |
|---|---|---|---|
| CSV input | `3e9a4d1ab98a51735b39de96e4c2dad7` | `167a1ac5f4f95e0e56176bf4e9d7335d34f347c7e04db78d9f5745f01928c444` | 2064 / none / 1 |
| XLSX input | `8591505aec3035dbd7e8647eadd4a20b` | `196b6358b8717d044b80cc8c25b681da922d4829eaac2b4e2ad98ca9601b0f5a` | 5413 / none / 1 |
| XLSX revised once, b=25 | `9c8b6330dd88a522a2c4578e491f9141` | `1b731736326470071e596abf684ef0844add1ca0447b3b83304bd5337c76b390` | 5401 / `8591505aec3035dbd7e8647eadd4a20b` / 2 |
| Explicit follow-up, b=30 | `708c96a51f2b4332d3323bd332dc4f07` | `8bc7f4b7dbab1645d91c10ce7c90ad2d04e4c3530606837396c0b282ec5e1f11` | 5400 / `9c8b6330dd88a522a2c4578e491f9141` / 3 |

Both revised files were clicked in real server-metadata cards and downloaded by the authenticated browser. Their bytes, full hashes and ZIP/XLSX structure were checked with openpyxl: a remained 10, b became 25 then 30, and the second sheet remained `FS synthetic acceptance only`. V2 was explicitly selected with the card button; focus moved to the composer, refresh retained only that v2 selection, and the next turn bound only v2. Revision request IDs were `acceptance_revision_20261101_v2` and `acceptance_revision_20261101_v3`, one revision tool call per material task.

Actual browser downloads (extensionless browser storage files, parsed as XLSX bytes):

- V2: `E:/T3Code/state/userdata/server-browser/downloads/917d10d0a632c01b87c3976923d5c201101f9ef2f9538c7cd5c6a0b4f077d022/2a27ee0d-c48f-42f1-a4c7-d1d88772a85f`.
- V3: `E:/T3Code/state/userdata/server-browser/downloads/917d10d0a632c01b87c3976923d5c201101f9ef2f9538c7cd5c6a0b4f077d022/1ba7fa6f-895f-46ba-b5f7-7535b1892682`.

### Pagination evidence: recorded calls plus same-SHA parse, not archived raw tool receipts

The task ledger records actual read-tool arguments. Conversation events record 8 started/completed tools in material turn 1 and 6 in turn 2, with no tool.failed event. At `2026-10-31T19:50:51.831Z`, authenticated table readbacks independently matched all four immutable file IDs/SHA values: CSV total_rows=206 including header, 205 data rows and amount sum=205; each XLSX sheet0 total_rows=3 and sheet1 total_rows=2. No raw tool result/coverage payload was persisted by this implementation. The table below therefore reconstructs the deterministic page receipts from those exact immutable tables and recorded successful calls; it does **not** claim to be a saved original tool response or ledger.

| Material turn | File ID / sheet | total_rows | offset / limit / returned_rows | next_offset | Page complete / coverage |
|---|---|---|---|---|---|
| 1 | `3e9a4d1ab98a51735b39de96e4c2dad7` / 0 | 206 | 0 / 200 / 200 | 200 | false / selected_sheet [0,200) |
| 1 | `3e9a4d1ab98a51735b39de96e4c2dad7` / 0 | 206 | 200 / 200 / 6 | null | false / selected_sheet [200,206) |
| 1 | `8591505aec3035dbd7e8647eadd4a20b` / 0 | 3 | 0 / 200 / 3 | null | true / selected_sheet [0,3) |
| 1 | `8591505aec3035dbd7e8647eadd4a20b` / 1 | 2 | 0 / 200 / 2 | null | true / selected_sheet [0,2) |
| 1 | `9c8b6330dd88a522a2c4578e491f9141` / 0 | 3 | 0 / 200 / 3 | null | true / selected_sheet [0,3) |
| 1 | `9c8b6330dd88a522a2c4578e491f9141` / 1 | 2 | 0 / 200 / 2 | null | true / selected_sheet [0,2) |
| 2 | `9c8b6330dd88a522a2c4578e491f9141` / 0 | 3 | 0 / 200 / 3 | null | true / selected_sheet [0,3) |
| 2 | `9c8b6330dd88a522a2c4578e491f9141` / 1 | 2 | 0 / 200 / 2 | null | true / selected_sheet [0,2) |
| 2 | `708c96a51f2b4332d3323bd332dc4f07` / 0 | 3 | 0 / 200 / 3 | null | true / selected_sheet [0,3) |
| 2 | `708c96a51f2b4332d3323bd332dc4f07` / 1 | 2 | 0 / 200 / 2 | null | true / selected_sheet [0,2) |

The CSV chain is [0,200) then [200,206), no hole or overlap. The second page is not individually complete because its offset is nonzero; its null next_offset only denotes the last page. For each XLSX, selected-sheet completeness is separate from workbook completeness: both known sheets were read, not just sheet0. These are only the identified immutable synthetic file versions, not live business or full-customer coverage.

### Original IDs, unknown, stop, permissions and browser limitations

- Original CSV upload ID: `upload_cd817ca6c9354bf59440541416d82242`; XLSX: `upload_fe95d726079940adbc3ea930873191cb`. Lookup returned the same CSV ID/SHA. Re-posting the exact first turn request `web_6babbc1cbfda4203911c92f315fd110c` with its original attachment set returned 202 and the original turn; changing only the set returned 422. No extra turn/model task was created by those checks.
- Unknown upload was an explicitly labelled browser response-loss injection after a real 201, not a natural incident or fake server result. Original ID `upload_7004d34f4880458cad06482c49cd2b4f` survived refresh; same filename/size with different SHA was rejected client-side, zero new POSTs. The UI original-ID lookup recovered available file `f60e89f79be5a8123e0974d67e874a49`, without changing the request ID or uploading again.
- Invalid 9-byte XLSX genuinely failed validation. UI retained request `upload_a55b83c6c1524ad4b1cc0a190d4b28b5`, displayed upload failure and original-ID recovery/retry controls.
- Plain Enter inserted a newline without submitting; Ctrl+Enter sent through the original submit path. A keyboard Tab reached the recovery button with a visible 2px theme outline. Follow-up selection focused the composer.
- The first tiny stop attempt completed before the native click and is not a stop success. The separate necessary queued cancellation used the real stop-button handler via a MutationObserver when the button became actionable: stop ID `stop_92140d1e691942af89981c8d665e7e6f`, turn `611dc5c87a5a4ebe9345d73509311ace`, action accepted and state cancelled. At `2026-10-31T19:41:05.835Z`, state was still cancelled, reply empty, with zero started/completed/failed tool events. Its provider receipt still records a completed 3-token response; cancellation did not erase billing or prove provider computation/cost stopped. Running-state interruption remains untested.
- Authenticated own downloads passed; real anonymous download returned 401. A new empty synthetic conversation `a34c969efbd5465eb754ad90025b9ea3` could not download the first conversation file (404). No second real low-privilege identity was available; cross-owner/revocation/expiry and FC/tool/turn denial have local contract evidence, not an equivalent second-identity production claim. No account or authentication header was fabricated. A2 lacks a trusted production host scope and remains unavailable.
- During the instrumented first material task, no uncaught app error was observed and own-conversation requests returned expected 200/202. Later checks included deliberate 422/401/404 and the injected upload response loss. A complete console/HAR was not captured and is not claimed clean.
- Control+Plus did not change measured DPR=2, inner/outer width=1280 or visualViewport.scale=1 in T3 preview; real 200% browser zoom is unverified, not represented by CSS zoom or a narrow-viewport pass.

### Viewed current-deployment screenshots and actual visual failure

All paths below are fresh production `1f8ddc57` screenshots of the synthetic conversation, actually opened with view_image. Non-current sidebar rows were privacy-hidden with verified visibility:hidden without layout changes. An initial injected stylesheet was blocked by CSP; that first screenshot was deleted and is not evidence. No historical conversation body or credential was read.

| Scenario / UTC capture window | CSS viewport / theme | Absolute screenshot |
|---|---|---|
| Long title, expanded attachments, stopped status; 2026-10-31 19:35:44 | 1280x800 / light | `E:/T3Code/state/userdata/browser-artifacts/browser-screenshot-47-85-224-112-mvwswxv6-48da10e6.png` |
| Same current deployment; 2026-10-31 19:35:48 | 1280x800 / dark | `E:/T3Code/state/userdata/browser-artifacts/browser-screenshot-47-85-224-112-mvwsx0qq-09ce01d2.png` |
| Narrow view, long title and version cards; 2026-10-31 19:36 | 390x844 / dark | `E:/T3Code/state/userdata/browser-artifacts/browser-screenshot-47-85-224-112-mvwsxssa-f6fe6c63.png` |
| Genuine failed upload and keyboard focus; 2026-10-31 19:41 | 1280x800 / dark | `E:/T3Code/state/userdata/browser-artifacts/browser-screenshot-47-85-224-112-mvwt3qxq-66a72935.png` |

Visual acceptance failed: the long title squeezed the connection indicator into vertical text, expanded attachments left only a 35px message window for 2498px of content, and the 99-item history sidebar grew to about 15211px. No horizontal overflow was observed in the sampled desktop/narrow views, but that does not cure the reading/scrolling failures.

### Complete follow-up candidate (not yet deployed)

The A CSS/JS correction keeps the existing UI tokens/theme/navigation: clamp the visual title to two lines while retaining full DOM text and native title, keep connection status on one line, bound the history list with independent scrolling, retain at least 160px of message reading space when attachments expand, increase file-action touch targets and use human attachment progress labels. Only a confirmed accepted ordinary turn closes attachments; failed/unknown submission preserves recovery access, original IDs and selections.

Follow-up preparation explicitly uses `--followup`. It validates this exact successful installed manifest and journal plus all 13 original Git LF source hashes at `1f8ddc57` and the pinned Nginx after-hash. It refuses arbitrary reflected live hashes, altered proof/Git baseline, target/protected/image drift, and missing installed modules. The 14-target/48-protected/four-module set is unchanged; the four modules now have real before-hashes and rollback restores them rather than deleting them. Already-10m Nginx bytes remain exact.

For a frontend-only diff with all services already active and an actual container image, materialStaticOnly retains the original writer, journal, backups, locks/fences and every original per-row guard. Identical active targets are hash-checked and left untouched; only changed CSS/JS pass to the original atomic writer. The static postcondition verifies actual container image and active-service guards, without restarting worker/HTTP, reloading Nginx or calling a model. A synthetic failure proves rollback restores the prior frontend while all four installed modules remain. Non-static runtime deltas retain the original restart/readiness path.

Checks passed: original deploy three-module runner 21 tests/zero skips; original Node data-handoff entry including executed DOM/fetch material checks; real Chromium local synthetic interactions, download bytes, 99-history/long-title/expanded messages and themes/narrow viewport. Candidate-only viewed local images are under `C:/Users/ADMINI~1/AppData/Local/Temp/fs-materials-ui-qt3cbjp9/` (`expanded.png`, `mobile-dark.png`); they are not deployed-version evidence. No unrelated Core/channel/knowledge suite was rerun and no shared CI driver changed. A newly reviewed/merged SHA, fresh pack/prepare and deployed visual review are still required.

## Static follow-up actually published and viewed (501f90bf)

PR719 merged as `501f90bf16fe114e70fcb05833cb1b2cf478e54c`; A fast-forwarded cleanly and produced a fresh Git LF package. Payload descriptor SHA256: `28dcf2a616839cda805ca6ccd891f0cd48091c49643c2579dd234c1453210c5b`. Fresh stage: `/var/tmp/fs-hermes-materials-501f90bf-20261031T201743Z/stage`; baseline `2026-10-31T20:18:30.255759+00:00`. Manifest SHA256: `6c6c1aceda92eba62cb694f112dc6df93f97dd05fc157c778b51c4ffe8daf920`. The original 1f8 successful b129/c902 proof, Git bytes and Nginx hash matched.

Real inspect passed, then exactly one static apply returned `applied-awaiting-actual-http-role-acceptance`. Backup: `/var/backups/fs-navigation-20261006/nav-20261031T201743Z`; journal SHA256: `9131be81c7c95da5c15a0c6ba49107102517952f009046e524dd813c1732c9b9`. Independent after-readback verified all 14 hashes/modes/root ownership and 48 protected hashes. The only content changes are below; the other 12 after-hashes exactly retain the 1f8 table above. All 12 unchanged targets also retained both inode and mtime_ns, corroborating no runtime/Nginx rewrite. No worker/HTTP restart, Nginx reload, model call, DB/UNKNOWN clearing or business action was performed.

| Changed target | Current verified after SHA256 |
|---|---|
| `/var/www/dashboard/fs-home/hermes/conversation/conversation.js` | `734008e993c00ec105fed5b696ef407005395fabea381466d793162989a53ad4` |
| `/var/www/dashboard/fs-home/hermes/conversation/conversation.css` | `15d84281a43a3f49dd337ec8225135b1da9c08a5414efc6eb38c948999a902b8` |

Before and after service properties matched exactly: worker MainPID=10943, range MainPID=11083, Nginx MainPID=31780; all ActiveState=active/SubState=running. Container ID `fdb100cedd9b2c05dedfb7880282cd1105e322e3315e3585d72d149d8f01c96a`, image `sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`, StartedAt `2026-10-31T19:23:50.179982343Z`, Running=true also matched exactly. Range health returned 200/ok=true. Normal browser auth returned 200. Browser no-store asset fetches returned 200 and the exact two current hashes above; full-title DOM/native-title and loaded CSS measurements independently confirmed the new UI.

### Fresh current-deployment browser observations

Only synthetic conversation `0884f9a7a4ee4b66a220e20651e4e54c` was opened. On 2026-10-31 UTC, 20:19–20:27, actual measurements showed: desktop collapsed message area 288px and expanded 160px (previously 35px); title about 62px/two lines, connection about 24px/nowrap; desktop history 683px with independent scroll. At 390px viewport, page scrollWidth=390, sidebar height=183px, messages=464px, title about 62px and status remained inside the main panel. Scrolling the history 280px left page scrollY=0. Download/follow-up hit areas measured 44px. No horizontal overflow was observed in these cases.

Clicking the actual V3 card selected exactly `708c96a51f2b4332d3323bd332dc4f07` and focused the composer. Plain Enter inserted a newline without sending. Empty Ctrl+Enter correctly failed native required-field validation, producing no turn POST; the nonempty real Ctrl+Enter task evidence from 1f8 and candidate executable state tests are reused, not replaced with another paid task. Keyboard Tab reached the summary and recovery button with a visible 2px theme outline.

One new deliberate 9-byte invalid XLSX produced a real 422; request `upload_685c4a79f8a841739c0e5d8429800fbe` remained failed with visible original-ID recovery/retry controls and the picker stayed expanded. Clicking original-ID lookup then returned the expected 404, retained that same ID and displayed the original-file recovery instruction. It did not invent an available file or a new request. The existing cancelled turn remained `cancelled` with empty reply and the UI still said “已停止；本轮未产生回复。” despite this independent upload error. No new turn/model was submitted: the conversation still had four turns at 20:27:08Z. This known-invalid-file lookup is not relabelled as a natural transport incident.

A real click on the current-deployment V3 download completed at 20:22:32.776Z. The 5400 received bytes again matched SHA256 `8bc7f4b7dbab1645d91c10ce7c90ad2d04e4c3530606837396c0b282ec5e1f11`; openpyxl confirmed a=10/b=30 and the unchanged note sheet. The original two real downloads are also available in the stable shared directory below, independently read and parsed by Personal (not local mock downloads):

- `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Receipts-1f8ddc57-20261031T200731Z/result-v2.xlsx` (5401 bytes, full SHA above).
- `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Receipts-1f8ddc57-20261031T200731Z/result-v3.xlsx` (5400 bytes, full SHA above).

Every image below is fresh production 501f, actually viewed with view_image before handoff. Only non-current sidebar rows were visibility-hidden for privacy, with computed visibility checked and layout preserved. The original artifact PNGs were copied byte-for-byte to this new shared evidence directory after viewing, avoiding browser temporary-download lifetime assumptions. Dates are 2026-10-31 UTC; viewports are CSS pixels (PNG resolution may reflect DPR=2).

| Step | Capture UTC | Viewport / theme | Stable absolute PNG |
|---|---|---|---|
| V3 card and collapsed attachments | 20:21:43 | 1280x800 / light | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/desktop-light-collapsed.png` |
| Expanded attachment picker and long Chinese filename | 20:21:52 | 1280x800 / light | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/desktop-light-expanded.png` |
| V3 download/follow-up actions; expanded attachments | 20:22:02 | 1280x800 / dark | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/desktop-dark-expanded.png` |
| Real invalid upload; keyboard focus on original-ID recovery | 20:23:38 | 1280x800 / dark | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/desktop-dark-error-focus.png` |
| Expanded picker/composer after vertical scroll | 20:23:45 | 390x844 / dark | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/mobile-dark-expanded-error.png` |
| Two-line title, one-line connection, bounded history | 20:24:12 | 390x844 / dark | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/mobile-dark-header.png` |
| V3 card, download/follow-up and collapsed picker | 20:24:44 | 390x844 / dark | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/mobile-dark-card.png` |
| Same narrow card in light theme | 20:25:18 | 390x844 / light | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/mobile-light-card.png` |
| Cancelled turn remains stopped while upload lookup reports 404 | 20:27:08 | 1280x800 / light | `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-UI-501f90bf-20261031T202858Z/desktop-light-stopped-lookup.png` |

Observed diagnostics: from the post-load probe at 20:19 onward, window error/unhandled-rejection buffers remained empty. Own-conversation polling/metadata calls returned 200; auth and both assets returned 200; expected negative tests were the invalid-file 422 and same-ID lookup 404. The latter appeared in resource-error metadata and is accounted for; this is not a claim that an initial-load console or complete HAR was captured. Metadata and network observations contain only the synthetic CID/request/file IDs, no cookie/header/credential or historical body.

Native Control+Plus was attempted again on current 501f at 20:25:29Z. DPR stayed 2, inner/outer width stayed 1280 and visualViewport.scale stayed 1: real 200% browser zoom remains unverified. No CSS zoom or viewport substitution is presented as a pass. Running-state interruption, second-identity production authorization/revocation/expiry, trusted live A2 scope and full-stage acceptance likewise remain outside the evidence; previous contract layers are preserved.

A restored the original light theme and closed only its new synthetic tab at 20:27:30Z. The original user tab was never navigated, captured or closed. A previous preview_status available=false denoted no current selection, not proof that tabs were closed: the following open listed the original tab intact. Personal must still perform its own independent read-only/no-model visual review; A does not mark that review or the entire Hermes/stage 2 complete. The synthetic review URL remains https://47.85.224.112/dashboard/fs-home/hermes/conversation/?conversation=0884f9a7a4ee4b66a220e20651e4e54c .

## 2026-11-01 材料执行装配：本地候选，生产仍501f

本轮只本机实现/合成验证。固定 B 补充为42b6df09cfc0ccbe0743231c79b96cec5edf8bb1；A 完整固定 SHA 随提交回交。不复用旧 descriptor/stage，不上传/安装，不调用真实模型或业务 API，不宣称运行包已验收。

先前用户明确允许的唯一 A 有限现场元信息核验已完成：实际 running container fdb100cedd9b2c05dedfb7880282cd1105e322e3315e3585d72d149d8f01c96a，image sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544，container/image WorkingDir=/opt/hermes。未输出 Env/config/DB/凭据/日志或源码正文。以下 regular 文件与固定 public pin71d34bad1045610252eda02ee79549436896e784 的 raw Git bytes 全等（不是新 resolver 上线证明）：

| /opt/hermes/gateway/platforms/ 文件 | bytes | 完整 SHA256 |
|---|---:|---|
| api_server.py |256424|6a7e6fb0a0d5ea25ddc47d36a64e2c0bc50ded331d49e1c4521d801ca7189043|
| api_server_runs.py |68296|8a7fcfd56183c32a14b41c7c43ce36b21b37bf49f2ed035dafe48899c0e8cbe7|
| api_server_run_idempotency.py |10755|56f7762addc5e610569fd613729f1f0b3d5e99e4b76f56d9cfa509dfeb51636c|

原 publisher 增加显式 --materials-execution pack/prepare 模式，必须 --followup，绑定501f真实成功 proof：backup=/var/backups/fs-navigation-20261006/nav-20261031T201743Z；manifest=6c6c1aceda92eba62cb694f112dc6df93f97dd05fc157c778b51c4ffe8daf920；journal=9131be81c7c95da5c15a0c6ba49107102517952f009046e524dd813c1732c9b9。候选目标为24（旧14+8新模块+fs_inprocess/range_api两个由原保护转为载荷），保护集合46。8新模块为 conversation_goals/conversation_goal_tasks/conversation_material_runs/material_execution/b2_goal_state/b2_goal_host/b1_model_routing/b2_customer_followup。新增前必须不存在；两个已有接点既核旧 proof 保护 SHA 又核501f Git LF before；原4文件均为已有 beforeSHA，失败回退恢复，不删除。Nginx保持已装10m及原0600精确字节。本轮是运行装配变化，不能冒静态-only免重载；后续实际 changed-target/影响、现场新 baseline/manifest/CAS/原锁/围栏/备份/服务/image/健康须合并后另取证。冻结 publisher bytes 未改。

合成 publisher 新用例已覆盖24/46/8精确组装、Git+成功 journal 来源、源漂移拒绝、原 inspect/apply 与 restart 失败回退，原首次安装/静态followup/UNKNOWN/CAS回归保持。Windows目录 fsync/mode 仍用原 temp 边界夹具，不称 Linux 发布通过。原 runner deploy 三模块合计22项通过（test_http3/test_release7/test_runtime_materials12）。

本地 Chromium 使用路由合成数据、真实 DOM/事件/loopback 下载，无正常生产登录或模型请求。2026-11-01 本机约08:28 +08生成并实际 view_image 看过以下候选图：桌面1280x800 light/dark、指定修改展开与可见焦点、390x844 dark收起/回答。页面无横溢、历史侧栏独滚、长中文标题两行/connection nowrap；答案中的<script>按原文本原样显示，不执行、不生成任意链接；显式范围和单元格控件由真实事件执行。每2.5秒相同状态 polling 保留原按钮 DOM/焦点。图片及本地 download.xlsx 都是夹具，绝不是先前501f的真实产物或新部署证据。

- C:/Users/Administrator/AppData/Local/Temp/fs-materials-ui-szads3wx/material-desktop-light.png
- C:/Users/Administrator/AppData/Local/Temp/fs-materials-ui-szads3wx/material-desktop-dark.png
- C:/Users/Administrator/AppData/Local/Temp/fs-materials-ui-szads3wx/material-expanded-dark.png
- C:/Users/Administrator/AppData/Local/Temp/fs-materials-ui-szads3wx/material-mobile-collapsed.png

浏览器测试中预期第一次上传响应被夹具丢弃，刷新按原 ID恢复，无新上传；两个原human turn及显式派生选择保留；新增材料任务只走其专用HTTP夹具，未伪造新human turn。未做完整console/HAR留档及实际200% zoom，生产视觉、真实SDK/模型任务/费用、running停止和第二身份权限仍待后续实际验收，不能据本组截图提前通过。

最终 A 本地收口：原 `units(.../tests,['test_conversation_store'])` 实际加载83项、零失败/错误/skip（其中新材料20）；原 deploy显式三模块22项、channel12、原Node入口含DOM/fetch、Chromium操作通过，15个变更Python文件按3.9 AST通过。图片桌面/窄屏代表文件实际写入时间为2026-11-01T00:28:56Z；本轮未重复旧Core198或未改知识套件，先前知识收尾失败不在本包扩修，未冒通过。主控集成后新SHA Linux/独审、真实SDK/模型/生产仍未验。

PR723派审前两项P2已在A原分支收口：runtime缓存短锁+并发/live回归；UI单选修订并显示目标名+反序DOM/fetch回归。新增两项Python测试通过，原Node入口通过；真实temp SQLite且无模型/业务API。旧51af方法只在内存回退的两项测试均明确因构造2个runtime失败，修复版为1个。新本地Chromium `C:/Users/Administrator/AppData/Local/Temp/fs-materials-ui-3k9h9zql/material-expanded-dark.png` 已实际view，看到“修改目标：核对结果.xlsx”及原主题焦点；仍是candidate-only非生产验收。B源码、发布器及其他51af已验输入未改，不重跑Core198/旧20。PR723由Personal集成/新SHA独审与LinuxCI，A不新建PR/Agent或部署。

## 5f99 最终合并版：零模型实际SDK构造通过，发布前原锁阻塞（2026-11-01）

本轮部署 sourceCommit 固定 `5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f`，A先 clean/ff main；不用Personal后续状态记录作部署来源。新 Git LF pack 为23源载荷+原publisher四文件，descriptor SHA256 `041ccf76093a0f337fbb75ef90a09ae91d5d004f56cdade2a98d330c92c48310`；新tar 593920bytes/SHA256 `97e6eea4df2a0e6d649e5fce091dd50859ec9090eab2d0943a7bcfb8856f15c8`。通过正常工具审核上传至全新 `/var/tmp/fs-materials-5f99-20261101T013900Z`，未重用旧stage。

实际固定容器仍 fdb100cedd9b2c05dedfb7880282cd1105e322e3315e3585d72d149d8f01c96a/image sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544。三SDK文件 regular/size/fullSHA再次全等上节固定pin。零模型探针在这个现有容器的原 `.venv/bin/python` 独立进程构造真实官方 AIAgent/registry，加载精确Git候选模块定义，并指向已核原FS挂载 `/opt/pilot/runtime-config.yaml`；不修改任何活动源或配置。实际工具恰为三个文件wire工具，实际上下文1048576，skip_context_files/skip_background_review=True、load_soul_identity=False、memory_enabled=False且两个memory对象None；实际system包含冻结指令，15个proof字段形状兼容。Socket全部阻断，实际网络尝试0、未执行conversation/tool/model，session_db=None，未构造正式APIServerAdapter或读写其持久账本。合成输入没有经过官方POST admission；探针不是accepted-input/正式执行回执，更不是实际SDK运行任务完成。

探针设置的初始失败保留：系统python缺dotenv；改用原venv后，误用host配置路径时构造得到SDK默认meta-tools与null context，proof拒绝。仅查询现有FS挂载元信息并在探针进程指向正确原路径后通过；没有安装依赖、变更配置/权限或放宽proof，不把这些探针设置错误算作生产SDK故障。具体最小字段回执见下列共享JSON，不含配置/凭据/源码正文。

新现场baselineObservedAt=`2026-11-01T01:33:26.578106+00:00`；新stage=`/var/tmp/fs-materials-5f99-20261101T013900Z/stage`，manifest SHA256=`4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881`。501f installed proof与Git before全部匹配；24目标/46保护/8新增，19目标有字节变化，Nginx旧10m/0600精确字节不变。三服务runtimeBefore全active，workerImageSource=实际container。原publisher inspect通过sourceCAS/protectedCAS，原publisher仍retired，未写活动文件。

唯一一次 apply attempt `nav-20261101T013519Z` 在冻结原publisher live_lock取得 `/var/www/dashboard/fs-home/transactions/collector.lock` 时抛BlockingIOError(errno11)中止。尚未进入admission/provider围栏或备份创建，backup `/var/backups/fs-navigation-20261006/nav-20261101T013519Z` 及journal均不存在，不能称安装失败后回退、不能称新worker启动失败。只读核实持锁pid18397/comm python3/cgroup fs-transaction-collect.service，Type=oneshot；该任务09:32:54 CST自然启动，至01:39:05Z仍activating/start。没有取消任务、强杀、清UNKNOWN、抢锁或重复apply。

阻塞后逐项读回：24 currentSHA全等manifest beforeSHA（8新模块仍缺失）；46保护全匹配，目标owner/mode保持。worker/range/nginx均active，PID仍10943/11083/31780；容器ID/image/StartedAt仍原值，range /health=200且ok=true，匿名worker /v1/capabilities=401。故当前生产仍501f，5f99尚未软件发布。新manifest、stage和失败attempt均保留；后续只能在自然空闲且重新核实际基线后沿原publisher继续，不能靠取消collector获得空闲。

可供主控独立读取的稳定共享metadata（没有源正文/DB/凭据）：
- `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Deploy-5f99-20261101T013800Z/sdk-probe-5f99-result.json`
- `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Deploy-5f99-20261101T013800Z/sdk-probe-5f99-attempts.json`
- `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Deploy-5f99-20261101T013800Z/merged-5f99f5b3-blocked-metadata.json`

未进入新版本正常FS认证、实际DeepSeek/accepted-context/用量费用、running stop、不可变下载、新部署视觉阶段；这些均未验，不能借旧501f闭环或本次构造探针代替。不使用preview_*验证自己修改、不提取Cookie/凭据、不伪造认证头，原用户tab未操作。没有额外业务/模型/API/IAM写入或新预算；未重跑旧Core/知识套件。Personal最终验收仍待真实后续结果。


## 5f99 实际安装、真实材料 404 与诊断后续候选（2026-11-01）

此前 collector errno11 是第一次 apply 在全部锁前拒绝、0 目标写入的历史回执。collector 自然结束后，同原 ID 在原一小时窗口内重核 24 before/46 保护/8 缺失/原 image/服务/空闲/无 backup+journal，沿原 inspect/锁/准入/CAS 成功 apply；未停止采集、清任务或改 freshness。

当前真实软件 sourceCommit=`5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f`，不是记录 commit a536。payload descriptor SHA=`041ccf76093a0f337fbb75ef90a09ae91d5d004f56cdade2a98d330c92c48310`，成功 manifest SHA=`4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881`；stage=`/var/tmp/fs-materials-5f99-20261101T013900Z/stage`，backup=`/var/backups/fs-navigation-20261006/nav-20261101T013519Z`，journal SHA=`3f6d474d37716610de334f14b9b7a699f879aae170471c065f5007c47e3ab93d`，状态 `applied-awaiting-actual-http-role-acceptance`。24 after SHA/root/mode 与 46 保护匹配，8 新模块已存在；不是后续可再当 absent 安装的文件。

实际运行 container=`9c0225c7ea03f676c10ff9f1b2181fa0c5dda8f472f6e6834ea616ba015b5db7`，image=`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`，StartedAt=`2026-11-01T01:42:47.848543281Z`；worker/range/nginx active，range health 200、匿名 worker 401。原内部 transport 仅 capabilities 200，fs_materials verified_pin/readonly_original_lookup/single_post 为 true；此为软件/内部健康证据，不冒正常 FS 身份或 accepted run。实际 SDK 零模型构造证据复用先前受控结果，不重新调用模型或构造官方 accepted-input 回执。

正常 FS BrowserAct 合成验收 cid=`fa7ea40c42bc4833bdff3788f1d733f9`，CSV fid=`55b55801892a3d83c3fc699f98da4a8a`，2061 bytes、SHA=`31f3057e1b6b72cb930b65fbfd10bd362e4a3e599803c5d5f11af692a76cadd3`。普通会话和文件列表 200、上传 201。唯一材料 POST 的原 request=`material_da2c98dcd8d3464fb4db5f065f0ea110` 返回 404，完整 path 的 cid 一致且无 query。原成功回执丢弃注入 discarded=false，未触发；未发第二 POST、未建 R2/R3，未获得 task/lease/run/proof，费用 unknown，不据 404 断言从未执行/零费用。

曾调用原材料 GET，明确该入口可能经 _parts 初始化私有表，不能算纯读探针；已停止此类探针。02:08:29Z 后时点，已知 conversation DB mode=ro 核本合成行存在、已知 tasks DB 三个 namespace 缺失；未测到当时运行对象实际 DB 路径，故不外推因果。实际 8931 监听 PID1616 与 range unit 一致、启动 09:42:51CST，argv range_api SHA=`584cb74985b7f44f8e9d85ac1a4e9681de62af65133fb62b5b65095af94d83f3`。fresh 独立进程选中 range 目录 HTTP（SHA=`3d5f245da179f0a3cb7abbad2fcbf6aa3bbe749f7090c5bd188d8aca11de90cd`、含 materials），不是运行进程内存证明。error=not_found 同时覆盖未命中与 LookupError，shadowing/早期 owner/实际对象路径仍待证；没有先按猜测修固定导入路径。

稳定合成证据目录：`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Deploy-5f99-20261101T013800Z/`，含 browser-material-r1-audit.json、material-r1-early-db-metadata.json、merged-5f99f5b3-applied-metadata.json。主控已独立读取前两份；原请求完整 payload 已保留。只关闭 A 自建 BrowserAct session，用户原页不操作。没有新的生产视觉/DeepSeek/费用/停止或 A2 scope 通过声明。

本次后续候选仅“材料入口受控装配诊断与 404 分层”，合同见 CONVERSATION-GOALS.md。本轮无 SSH、真实 API、模型、浏览器或生产写。新增 `--materials-diagnostics` 模式仍走原 publisher，但严格钉上述 5f99 成功 manifest+journal、Git LF 全 24 before 和原 46 保护；NEW 集合为空，8 模块必须现存。pack/prepare 不把随读当前 hash 反射成合法基线。只允许 HTTP conversation_http.py 与 range_api.py 两目标改变，manifest 明列 materialChangedTargets，其余 22 个目标只 CAS/备份不改写。Nginx 保持原 10m/0600 字节。

操作形状（仅审查/合并后由最终 merge SHA 新 pack，新 baseline/stage；不是本轮执行记录）：

```text
python runtime_prepare.py pack --materials-diagnostics --repo <repo> --source-commit <final-merge-sha> --output <new-bundle>
python runtime_prepare.py prepare --followup --payload <new-bundle>/payload --source-commit <same-sha> --approved-payload-sha256 <new-descriptor-sha> --output <new-stage> --release-ready
```

descriptor 自动携带 material_execution/material_diagnostics 与精确 5f99 installed_baseline；原 inspect/apply、发布锁/准入/provider/CAS/UNKNOWN/journal/backup/回退保持。诊断模式要求真实 active/container，禁止用恢复态 fallback。当且仅当实际修改两个 HTTP 目标时，沿原 fence.stop_then_unlock_database 与原 DEEP_SCOPE restart/readiness 重载 range；worker 不重启，Nginx 不 reload。合成成功/失败回退均实测只写两个目标，其它目标保留字节，8 模块不删。Windows fixture mode 仅临时主机边界归一化；Linux CI 和现场发布仍待验。

范围证据：新增诊断 7 项通过；受影响 FileTests 10 项通过；原 deploy 三模块 23 项通过（含新增 5f99 proof/pack/before/CAS/只写两目标/原 apply/rollback）。原 CI 的 store.load_tests 已加新模块，deploy 原 test_runtime_materials 自动包含新测试，无 tools/pr_fast.py/workflow/依赖变更。未重跑无关 Core/旧 knowledge 套件；旧 knowledge 收尾失败仍保留。本候选须 Personal 集成、最新 SHA 独审/必要 CI/合并后，才新 pack/prepare/apply。发布重启可能改变旧内存状态，不能倒推本次原 404 根因；发布后先取正常鉴权诊断，不盲重发原材料 POST。


## PR724 最终 f79e 诊断发布与正常角色 GET 实测（2026-11-01）

本节是实际执行回执，前节候选/未部署描述仅保留当时时点。原 A 分支 clean 后正常 ff 最终 `f79e29f0d5921b103a218c5e6ed967a754858b9c`，origin/main 同 SHA；仅用该 merge SHA 新 Git LF pack，未重跑已验 Core/SDK/本地套件，也不复用旧 descriptor/stage。payload descriptor SHA=`95589f43b26ec4ed48afdc7e150af6c7a522383cc3aff7fbb3573d8d66832412`；604160-byte tar SHA=`14fbecd85b202f9c50cc538dd8e327d085e9e41d08850738a342870fb234c32b`。上传的是已合并 Git 载荷，无生产源码导出。

新 stage=`/var/tmp/fs-materials-diagnostics-f79e29f0-20261101T024200Z/stage`，baselineObservedAt=`2026-11-01T02:43:02.272873+00:00`；新 manifest SHA=`25cd452cfb25790502cab7a7561187f04da5af6e2096baf9a71fabb11ad199ee`，精确绑定原 5f99 成功 proof。24 个 before 均存在、46 保护、NEW 空，原 image/三服务 active；manifest 变化目标仅 `/opt/fs-exact-range-20261001/conversation_http.py` 和同目录 `range_api.py`。原 inspect 的 sourceCAS/protectedCAS/releaseReady 通过后，沿原锁/准入/provider/CAS 单次 apply 成功。新 backup=`/var/backups/fs-navigation-20261006/nav-20261101T024500Z`，journal SHA=`534a813b17ea54422131403075156ec82fa2696959c575211e29cee3c0c6cdab`，原状态仍为 `applied-awaiting-actual-http-role-acceptance`。没有锁抢占、清 UNKNOWN、重试 apply 或回退。

02:44:58Z 软件读回：24 afterSHA/root/mode 全匹配，46 保护 SHA 和原 mode/uid/gid 保持，22 不变目标 inode/mtime 保持，8 已装模块均保留。range PID1616→18220，active 时间 10:44:23CST；worker PID1434 与 Nginx PID31780 不变。实际 container=`9c0225c7ea03f676c10ff9f1b2181fa0c5dda8f472f6e6834ea616ba015b5db7`、image=`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`、StartedAt=`2026-11-01T01:42:47.848543281Z` 前后完全一致，Running=true。range health200、匿名 worker401；只按原 DEEP/admission 路径重载 range，没有 worker restart 或 Nginx reload。

A 自建 BrowserAct session `fs_hermes_a_f79e_diag_20261101`，只开同 origin `/robots.txt` 安全空页，不打开会话 UI/自动轮询、用户历史或用户原 tab。02:46:10.623Z 沿已有正常 FS 登录态 GET 原合成 cid `fa7ea40c42bc4833bdff3788f1d733f9` 的 `/runtime-diagnostics`，无 query、无改认证头，200/application-json/no-redirect，`X-FS-Material-Adapter=materials_runtime_diagnostics_v1`。

实际诊断：

- module_path 与 handle_code_filename 均为 `/opt/fs-exact-range-20261001/conversation_http.py`；
- loaded_code_sha256=`c48a9563baf14869acd2e68811fbf4448086ee52a9c0072458af01cee46be742`，format=`python_marshal_code_v1`；
- disk_file_sha256=`97f8d6982beeba363885bc9fb4f354b4907dc6f492a40d545ef2f5af652a82a4`，与本次实际目标 afterSHA 匹配，明确不当作内存 hash；
- materials_branch_present、materials_bound、materials_store_matches、materials_tasks_matches、store_path_matches_expected、tasks_path_matches_expected 均为 true，adapter_version 为当前固定版本。

诊断前 02:45:58.593962Z / 后 02:46:33.727256Z，只用原两 DB mode=ro/query_only 核限定元信息：inode/size/mtime、白名单表存在性/数量完全相等。合成 conversation 行1/turn0；goal/mutation/outbox/identity/selections/material_runs 均仍不存在；原 tasks 仅数量元信息346→346，不读原 task/客户/会话正文。没有整 DB 导出或 hash，不把元信息对照冒充全库逐字节审计。未调用 _parts/queue/material detail/result，没有私有表初始化。

02:47:09.870Z 同自建会话正常 `credentials:omit` 匿名 GET 同诊断路径为401/text-html/no-redirect、无适配器头；不读 HTML 正文或凭据。实际 network summary 只有两次诊断 GET（200/401），0 POST。随后只关闭 A 自建 session，用户原页未动，没有 Profile/Cookie 提取/转移或伪造 X-Auth。

稳定共享收据目录：`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Diagnostics-f79e29f0-20261101T024200Z/`。`receipt-index.json` SHA=`1d40e02f6f1d2c7d6a5fca040a1cdcac451027058612f40a4b5c1d8617ee134a`；其中登记 before/apply/after 软件元数据、DB before/after、正常/匿名诊断和实际 network summary 共8文件的 bytes/full SHA。只含授权元信息，没有源码/配置/凭据/DB正文。收据已主动回送 Personal，最终认可仍由主控独立审核。

本阶段 0 新材料 POST、0 模型、0 SDK 重复构造、0 新合成会话/附件；原 request=`material_da2c98dcd8d3464fb4db5f065f0ea110` 保留，原捕获 posts=1/discarded=false/费用unknown，不建 R2/R3。此次只证明**重载后的当前装配与诊断边界**，不能倒推先前404或shadowing根因，也不证明从未执行。当前真实软件版本为 f79e；原材料执行/单POST恢复/回答/下载/运行中停止/第二真实身份与撤权/A2scope/视觉等均未在本阶段新增验收，保持旧证据分层。主控核明诊断后另决定必要修复或原ID受控恢复边界；本记录提交不重pack/重部署，不宣称材料整包、Hermes或阶段2整体通过。


## 原ID准备查询、SQLite事实与 f79 单模块兼容候选（2026-11-01）

主控独立核收 f79 的8份发布/正常角色诊断收据，只认可软件发布+当前受控诊断。随后明确允许一次带私有 schema 初始化副作用的原ID GET，原材料POST仍禁止。02:53:17.831Z 正常已有 FS 身份从自建安全 /robots.txt 页面 GET `/api/hermes/conversations/fa7ea40c42bc4833bdff3788f1d733f9/materials/material_da2c98dcd8d3464fb4db5f065f0ea110`（无query），返回404、error=not_found/source=material_http/stage=lookup、当前适配器头。网络仅1GET/0POST；前02:52:12.954952Z与后02:53:40.086936Z两库限定元信息完全相等，tasks346不变，全部 private namespace仍缺失。因此 authoritative not_found=false，原request行数不可权威判定，不把不存在的表补成0行。未/result、第二GET、重发、手写SQL或执行模型，session已关。首次会话名大写被CLI210107拒绝发生于创建会话/HTTP之前，已更正最初误标的transport unknown，本次实际服务端请求仍只有1次。

上述5文件收据目录 `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-OriginalQuery-f79e-20261101T025212Z/`，index SHA=`70a1a2d3b9ef56fe8c0c2a0dff2713d1512bb8a23f1724466ded1ab45dc7c6af`，主控已逐项核size/SHA。获准的下一次最小只读 SQLite 元信息收据为 `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-SQLite-IndexMetadata-f79e-20261101/sqlite-index-metadata.json`，1551 bytes/SHA=`a1ec21733df838a5dc83ffb7e663a78266458ee95d42b80f8052c02dc169ca1a`，亦已独立核收。range PID18220实际 exe=/opt/python39/bin/python3.9，同exe fresh探针 Python3.9.18/SQLite3.7.17；index_list仅seq/name/unique，3个索引都unique=1且缺partial，原约束列集合为owner+fingerprint、run_id、id。只输出版本/列结构/约束列集合；不输出索引名/SQL/业务行/Env/凭据，DB inode/size/mtime稳定，没有构造生产服务。不是进程内存或真实旧constructor执行证据。

现场缺字段事实与本机真实temp链的内存对照吻合，已确认当前索引元信息兼容缺陷；完整源修复见 CONVERSATION-GOALS.md。本轮代码包只改 runtime/conversation_goal_tasks.py 的索引证明与元信息错误关闭；不修改B/Core/UI/controller/pilot/原tasks表/SDK/worker/proxy。新增发布模式 `--goal-task-index-compat` 明确独立于仅允许HTTP目标的 diagnostics 模式，descriptor=goal_task_index_compat、manifest=goalTaskIndexCompat，诊断标记不再启用。

该模式严格钉最终 f79e29f0d5921b103a218c5e6ed967a754858b9c、manifest25cd452cfb25790502cab7a7561187f04da5af6e2096baf9a71fabb11ad199ee、journal534a813b17ea54422131403075156ec82fa2696959c575211e29cee3c0c6cdab、backup `/var/backups/fs-navigation-20261006/nav-20261101T024500Z`。24现存/46保护/NEW空，8模块保留；仅允许 `/opt/fs-hermes-fc/conversation_goal_tasks.py` 改变，materialChangedTargets精确列实际变动，其余23只CAS/备份不改写。原锁/准入/provider/UNKNOWN/image/active/原writer/journal/rollback保持，禁止旧5f99/501f proof、旧stage或动态反射当前hash成合法baseline。只沿原fence+DEEP/readiness重载range，不restartworker/reloadNginx。新合成发布用例实际验证pack模式/完整before、旧proof拒绝、额外HTTP改动拒绝、成功/失败回退只写一个目标、其余23inode/mtime保持和所有8模块不删。

合并后的操作形状（尚未执行）：

```text
python runtime_prepare.py pack --goal-task-index-compat --repo <repo> --source-commit <final-merge-sha> --output <new-bundle>
python runtime_prepare.py prepare --followup --payload <new-bundle>/payload --source-commit <same-sha> --approved-payload-sha256 <new-descriptor-sha> --output <new-stage> --release-ready
```

Linux CI之后仍须按已授权未来发布阶段，在独立目录只用最终Git LF文件/同已核exe运行隔离temp DB测试，不import活动生产模块、不触真实库、不联网、不装/升级SQLite。最小正向旧引擎用例为 `test_conversation_goal_tasks.GoalTaskTests.test_legacy_auto_constraints_keep_original_id_fingerprint_and_revocation`；原TaskStore来自同Git的 `hermes-fc-pilot-20261013/pilot.py`，临时目录镜像其原路径和A source/tests。要复验HTTP旧/新对照，再包含最终Git的conversation_material_runs.py、两HTTP及test_conversation_runtime_diagnostics.py，运行该模块的 `test_real_http_old_index_loop_fails_then_legacy_proof_initializes_empty_original_lookup`。只选这些可在旧引擎运行的用例，不把现代partial索引对抗DDL强行放到不支持partial的引擎、不skip冒绿。所有源码仅来自最终Git，不读/导出服务器活动源。隔离测试用 -I -B、只显式加入该独立目录中的测试/source/pilot路径，先核相关模块 __file__ 均落在该目录，禁止把 /opt 活动源码加入 sys.path；socket调用在测试中拒绝，不为此放宽原runner。

本地真实temp索引/HTTP35项、原deploy三模块24项已通过0failure/error/skip；Windows临时mode仍只沿原夹具边界归一化，实际旧SQLite及Linux权限未冒通过。当前生产继续f79、原POST禁令不变；本包未SSH/生产API/浏览器/模型/部署，也未重跑无关Core/SDK/视觉/旧知识套件。新head必须Personal一个集成PR/最新SHA独审/必要CI/合并，再新最终Git LF pack/隔离旧引擎验证/prepare/apply。发布后仍先只一次原ID GET核完整初始化及原ID查回，之后交主控决定恢复提交，不擅启R2/R3或以新ID绕UNKNOWN。


## PR725 最终1b20原生通过、单次发布锁拒绝（2026-11-01）

原A worktree clean后正常ff最终 `1b20b91f2e7e023d90a0197053916ba9a59978e6`，未用主控后续记录作source。新私有隔离stage=`/var/tmp/fs-native-task-index-1b20b91f-20261101T033100Z`，9个最小source/test/pilot文件均为该SHA原始Git LF，逐文件hash前后保持；应用源未改写。执行harness单独记录、非Git应用源码，其SHA=`69dc2f858fc9011d8f1e6f5c9d2853060ccc9a925ead4f6880474d62ee9309dd`，225280-byte隔离tar SHA=`d555409a98c071b1711d741fcf13b89df5b059ced78df4164c208673b084b64b`。用已核range实际exe `/opt/python39/bin/python3.9`、-I -B，03:33:34.559757Z实际Python3.9.18/SQLite3.7.17原生7项通过0failure/error/skip：6项原账本constructor/原ID/full fingerprint/重连/strict True/IO后撤权/admission，以及1项覆盖通用和FC3两HTTP处理函数的完整空schema→原ID404 lookup测试。HTTP IO为内存handler夹具，不是真实socket/API请求。

原生阶段不改PRAGMA返回、不进入Row代理；Connection路径守卫返回真实SQLite Connection/Cursor/Row，只允许隔离目录内合成临时DB/内存。88次连接均受此守卫约束，相关模块__file__全在独立stage，网络/额外子进程尝试均0，没有活动生产源码import或原生产DB访问；临时DB完整清理。两个真实HTTP适配器均见原生seq/name/unique三列，修复constructor完整初始化私有表、identity1元数据、tasks/outbox/selection/run/goal/mutation意图均0，原ID确无row后正常404/lookup。这不是用现代Row代理冒旧SQLite，也不是正常FS角色验收。

原生通过后才新Git LF pack：payload descriptor SHA=`b46b941b065a120a361c21412432f09fa374944ad044056122551896ec44c453`，614400-byte发布tar SHA=`539b9326ec5da5b4c967a278d5fc1acfcbc1ec4d8be2ebc3243def13200898e6`；显式goal-task-index-compat/followup，新stage=`/var/tmp/fs-goal-index-1b20b91f-20261101T033400Z/stage`。baselineObservedAt=`2026-11-01T03:34:30.838092+00:00`，manifest SHA=`c149b7173db4a496332b2dafce02ae198b84e2c5e0b23f32f6f5d004ad5655d3`，严格绑定f79成功proof；24现存/46保护/NEW空、active/真实container检查通过，变化仅runtime/conversation_goal_tasks.py。原inspect sourceCAS/protectedCAS/releaseReady通过，无活动写。

唯一apply ID=`nav-20261101T033600Z` 返回exit1/BlockingIOError。过滤回执仅保留异常类及stderr长度1219 bytes，未保留具体errno/栈定位；不为补错误栈重跑apply，也不把同期collector锁观察冒充精确异常栈。03:36:43.930342Z限定只读对账：拟backup=`/var/backups/fs-navigation-20261006/nav-20261101T033600Z`和journal均不存在；24目标仍匹配全部before SHA/root/mode且inode/mtime全未变，46保护SHA/mode/owner未变，range18220/worker1434/nginx31780及container/image/StartedAt与before完整一致。同期collector.lock持锁python3 PID15925，oneshot unit MainPID同15925、activating/start、开始11:32:54CST。没有抢锁/stop/restart/kill/timer或配置权限变更。

据原publisher全部锁先于backup/journal/目标写的结构和此次读回，本次分类为**发布锁拒绝、尚无活动目标写入**，不是1b20安装后失败。准确生产仍为 `f79e29f0d5921b103a218c5e6ed967a754858b9c`；1b20只在独立合成环境证明原生兼容。严格按本阶段“失败即停”：没有第二apply/inspect，没有BrowserAct会话、真实材料GET/result/POST/模型/R2/R3，也没有原ID状态清理或手写SQL促通。原request=`material_da2c98dcd8d3464fb4db5f065f0ea110`、旧posts=1/discarded=false/费用unknown/旧404根因unknown保持。

稳定共享目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Native-1b20b91f-BlockedPublish-20261101T033600Z/`，receipt-index SHA=`4151b80cb2211cfafb80fa1ebfd4187c37923bd36f7daa01b88f7d120ac4ad31`。index列5份证据的bytes/fullSHA：原生结果、9源Git SHA表、发布before、过滤失败回执、失败后完整approved manifest+24/46及锁/服务元信息；无源码/配置/凭据/DB正文导出。收据已主动回送主控；本附录为记录性提交，不重pack/部署/旧测试。后续是否可在锁自然释放且原ID/新鲜度/CAS仍可核时有据续发，由主控明确；A当前停止，不盲重apply或先做材料GET，不声称真实功能恢复。
