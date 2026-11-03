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


### 同发布ID有据续发授权后的等待回执（03:40:22Z）

主控已独立核收上述native7/5文件及0目标写入证据，明确仅对本次原ID/原manifest写前拒绝给有据续发条件。A先按约只读一次collector自然状态：`2026-11-01T03:40:22.829070+00:00`，collector.lock仍由python3 PID15925持WRITE锁，unit Type=oneshot/MainPID15925/activating/start、开始11:32:54CST。故本次停在等待，续试apply=0，材料GET/POST/model=0；未继续其它现场探针、复核DB、重跑native/Core/SDK、轮询或新增定时，也未stop/kill/改timer/抢锁。backup/journal此步未重核，只保留03:36:43Z已核不存在的历史时点，不冒当前完整fresh/CAS条件已重新通过。

当前1b20仍未安装，生产版本最近已核为f79。原ID `nav-20261101T033600Z`、manifest `c149b7173db4a496332b2dafce02ae198b84e2c5e0b23f32f6f5d004ad5655d3`和旧锁忙收据均保留；后续在自然释放并获继续唤醒后才按授权重核fresh/CAS/receipt/quiescent，当前不盲重发。新等待收据目录 `C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-1b20b91f-CollectorWait-20261101T034022Z/`，含collector-check及独立receipt-index，不覆盖已独立核收的上一份index。该追加只作记录，不触发布，不宣称材料原ID查询或功能验收通过。

## PR725 最终1b20成功发布与完整schema原ID查询收口（2026-11-01）

本节更新上述历史等待状态，不改写旧失败回执。06:18:39Z单次只读观察collector无持锁者、inactive/dead；原 `nav-20261101T033600Z` backup/journal仍不存在，24 before及46保护匹配。Nginx目标SHA/大小/0600/root未变，但inode/mtime已变，旧03:34基线亦已超过一小时，因此没有复用旧manifest直接apply，也没有推断旧具体失败栈或元数据变化原因。

生产已发布sourceCommit为 **`1b20b91f2e7e023d90a0197053916ba9a59978e6`**，不是A记录head、Personal导航或其它模块main。复用已核native7与固定payload SHA=`b46b941b065a120a361c21412432f09fa374944ad044056122551896ec44c453`；新stage=`/var/tmp/fs-goal-index-1b20b91f-fresh-20261101T062133Z/stage`，fresh baseline=`2026-11-01T06:21:48.558756+00:00`，manifest SHA=`16615694e66cda7dcfffa4ba55381d21071b51cf45b3597be303f5ba2af4f235`。goal-task-index-compat/followup模式仍精确绑定上述f79成功proof，24现存/46保护/NEW空/8模块保留；Nginx当前inode/mtime纳入新基线但不改写它。原inspect/CAS/锁/准入/provider围栏通过后，仅一次新ID apply成功：release=`nav-20261101T062133Z`，backup=`/var/backups/fs-navigation-20261006/nav-20261101T062133Z`，journal SHA=`912511fd8fc877d9155ca6fec30ec8bdf9ff5bd94b94d6443d4f764e529c2446`，原journal状态保留 `applied-awaiting-actual-http-role-acceptance`。旧ID无backup/journal，不改旧stage或时间戳。

06:23:32Z实际读回24 afterSHA/root/mode与46保护SHA/mode/owner全部匹配。唯一字节变化为 `/opt/fs-hermes-fc/conversation_goal_tasks.py`，afterSHA=`8160a92c01e09a621cacad8112599f74b33c1fb1a82fb4db3c87e2cbfac40152`；另23目标相对fresh before的inode/mtime全部保持，包括Nginx。仅range沿原fence+DEEP/readiness重载，PID18220→14050、health200/ok=true；worker PID1434、Nginx PID31780不变，三服务active。实际container=`9c0225c7ea03f676c10ff9f1b2181fa0c5dda8f472f6e6834ea616ba015b5db7`、image=`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`、Running=true、StartedAt=`2026-11-01T01:42:47.848543281Z`前后保持；没有worker restart或Nginx reload。

正常FS身份、自建BrowserAct安全页于06:25:06.195–06:25:06.481Z只执行一次 GET `/api/hermes/conversations/fa7ea40c42bc4833bdff3788f1d733f9/materials/material_da2c98dcd8d3464fb4db5f065f0ea110`，无query，响应404/error=not_found/source=material_http/stage=lookup，适配器 `materials_runtime_diagnostics_v1`；网络捕获恰1GET。此GET已明确接受构造初始化私有表的副作用，不称纯只读。前后仅原两库mode=ro必要元信息：6个private表由缺失变完整，identity元数据1；outbox/selection/material_runs全表及原request计数0，goal/mutation仅原合成cid计数0，turn0，原tasks346→346。DB大小/mtime有预期DDL变化，不误记DB完全不变。自建session已关闭，用户原页未动，没有提取或转移Cookie/Profile、伪造认证头。

稳定收据目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-1b20b91f-FreshPublish-20261101T062133Z/`；`index.json` SHA=`eeeea9ba5d2689a6e9e9881299c320b377bc45278216eb96b7d2c3fba79297c2`，列12文件bytes/fullSHA，`summary.json` SHA=`5f9073077bd2dc1163f06aa2da8765a72b771b806f58fdf3207a9e7b4d1c7b00`。Personal已逐项独立核收，并用固定1b20 Git原字节复核GoalTasks SHA，认可范围仅为**固定1b20软件发布通过、完整private schema初始化后的原ID状态查询语义通过**。当前权威账本查无原ID持久执行意图，不证明任意官方run不存在，不把queued或404当执行完成。

原cid/request/payload继续保留，历史POST posts=1/discarded=false、旧费用unknown、旧POST404因果unknown。该发布及查询阶段0材料POST/0模型/0result/无R2/R3，未重复native/Core/SDK/视觉测试；材料POST禁令未解除，不因outbox查无自动恢复提交，也不再材料GET/result或现场探针。当前没有本材料短任务的真实task/lease/run、accepted-context、模型回答/用量、产物或视觉执行验收；不宣称材料整包、Hermes或阶段1/2整体完成。锁恢复和软件发布任务已收口，本条仅复用既有收据追加模块记录，不重部署、不改变权限、业务数据或主方案。

## 新合成材料付费验收：首任务失败后停止（2026-11-01）

用户后续明确允许现有DeepSeek/general lane必要付费测试，最多4个顺序合成任务；封存旧cid/request的POST禁令不变。主控撤回其额外添加的余额/累计CNY限额证明前置，不修改实际gateway或账户限制。复用预检收据index `c470025af9b3328fb650bf462675d8728e7b4d606f03f064f43cba04c839ff33`：12相关活动文件SHA/mode/root匹配已核1b20，原image不变、三服务active；当前worker/range PID3801/3960、container `f55ce950dac596fefad1a60b1747b87e5ed850ecb8f0e1d3799f78f7a1c5ac1a`，StartedAt=`2026-11-01T07:27:37.419713349Z`，不冒与更早进程相同或猜测变化原因。未重新部署、构造SDK、读取Env/凭据或运行旧测试。原policy仍为 `no-pilot-quotas-deepseek-direct-stream-tokens-only-v2`、DeepSeek/deepseek-flash、unknown费用允许、材料transport_retries=0；没有新增或绕过额度保护。

新建专用合成cid=`558e974b536e4bbfaceb6d018c0273e3`，正常UI上传并明确勾选CSV fid=`3720ce0a28a00de73da47b7ce4eebce9`。本机合成CSV为1441 bytes/SHA=`19de343b0a1a3b082da38520f8efc1152676e4a6cdf9cb48209821772dd4648e`，205数据行+表头，预期amount合计21115仅为夹具期望，不冒模型已算对。UI首次导航遗漏 `/dashboard/fs-home` 的404属于验收操作路径错误，已按既有正式路由校正；另一次本地context编码失败发生于任何该步浏览器请求前，仅修正临时UTF8记录读取，不改应用或重发请求。

唯一材料POST原request=`material_3d7065f9afb44f70ab1142090bc827d4`，08:58:51.456Z实际接收202后才在浏览器明确注入丢弃，discarded=true。UI保留原body/附件集合，后续原ID GET200查回同task=`10f54f0b5b650a26bdf30a47b3a596be`、lease=`340528653a2261335ebe63524c3b30f0`、session=`mg_d283591a1d161fb3dcd3b35b5abe6c3a6fa6926b735e90d6ef3bf5595433d4c1`、run=`run_2fa6490e5755454892c6f897bb0222f5`。客户端network与显式审计均只有1次材料POST，没有重POST；持久mapping attempted=1、official body SHA=`09d09ddc7a8386b4f531a0a0528879bb3d2aa5283daf92d8a7bc7353378fa4db`。未独立捕获官方POST网络次数，不用attempt字段冒完整官方网络审计。

实际正常状态接口及只读新任务映射均为failed/FAILED，coverage和generated为空，runtime_error=null。返回并持久化的上下文proof核原session/run，input_verified/prompt_present/native_memory_skipped=true，工具精确三文件wire名；payload SHA=`ba35d91d1be0d5a853126229bff912b152fa6e94655fdb743ea3d15dca2e78a9`、实际system_prompt SHA=`08c777eefdd6561abe2b678c12f7e6db6af853011992cae18f36304553925f79`。这证明实际接收/映射/上下文回执，不证明模型成功阅读或回答。限定mode=ro查询原daily消费账本中该task的reservation/receipt为0条；TaskStore tokens/rounds计数0不是提供方usage为0的证明。实际response_model/tokens/供应商调用数/人民币费用仍unknown，不宣称零费用。当前证据只能把边界收窄至已接收run失败且未见该task的gateway消费回执，具体SDK/gateway失败类别仍未确认，不能据此猜配置、余额或源码根因。

首任务失败即停止其余XLSX修订、派生追问和running-stop，不创建第二模型任务、不清状态或换ID。尝试点击“查看回答”的工具请求在CreateProcess前被自动审批拒绝，理由是当前失败后仅允许状态/调用/用量对账，不能打开result通道；未执行该点击或result GET，未用直接HTTP/其它工具/数据库读取结果绕过。故当前没有可据以实施的准确源码修复候选；进一步定位须主控明确限定这个已失败run的错误类别读取边界，不在生产临时修补。

稳定共享目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Materials-Execution-20261101T085429Z/`，index SHA=`21a2edea8a183b57c45dbf26aeb95174ddc5505bf913f8323b66425305fa5def`，列17文件bytes/fullSHA；summary SHA=`6eff41d4ff0c252c56c52078c5406d6ba1c0cc80df6bcca17555e2994a0b7a63`。桌面light失败态截图 `task1-failed-desktop.png` 已实际view，1904×985/DPR1，109558 bytes/SHA=`2a1cfe5f66d695ddcaf9b914b1878fba472f2182ee44379e1ea7e3d1756f9dc1`；只显示本合成任务，历史列表标签清除/visibility隐藏并恢复占位高度，不作完整布局验收。未验dark/390px/200%缩放/键盘、分页覆盖、不可变产物下载、权限对抗和running-stop；第二真实身份/撤权/A2scope亦未验。只关闭A自建BrowserAct session，用户原页未动。旧cid/request/payload封存、旧POST1/discarded=false/旧费用及404因果unknown保持；本记录不作部署源、不宣称阶段1材料执行通过。

## materials可信边界诊断增强候选：仅本地开发（2026-11-01）

用户明确授权最小worker诊断增强，迁移暂停后已指令继续。本轮A worktree/origin/原分支复核干净，base=`2b5f5a67bec04eb37af2ea0c575c3871c170260e`；不fetch/merge主控新main或导航。只改 `fc-review-channel-20261026/source/hermes_worker.py`、本模块 `tests/test_conversation_file_loop.py` 原worker adapter测试及本附录，不改SDK/B/Core/controller/proxy/HTTP/UI/publisher/CI或配置。候选未部署、未重启、未读取生产状态/error正文、未执行浏览器或模型任务；两个既有请求均封存，历史1b20软件发布、原202恢复证据及费用/根因unknown保持。

新增可选 `runtime.fs_material_diagnostic` 为固定四字段JSON，例如 `{"version":"materials_diagnostic_v1","phase":"agent_worker","exception_class":"PermissionError","reason":"unknown"}`。phase仅 `admission_wait/executor/agent_create/agent_ready/agent_worker/agent_returned`，表示可信函数边界，不冒提供方已经调用或具体报错栈行。异常按真实type身份与固定白名单匹配：ValueError/TypeError/AttributeError/KeyError/RuntimeError/OSError/PermissionError/TimeoutError/ConnectionError/ImportError/asyncio.CancelledError；自定义类或同名子类为other_exception，未观察到对象为unknown。不读异常str/repr/traceback；即使自定义异常的类hash、str或repr会抛错，诊断也不调用它们。failed结果只允许turn_exit_reason或reason的固定max_iterations/interrupted/cancelled枚举，其余unknown，不从错误文本猜分类。不记录请求、回答、推理、token、路径或URL。

固定公开SDK pin仍为 `71d34bad1045610252eda02ee79549436896e784`，api_server_runs.py SHA=`8a7fcfd56183c32a14b41c7c43ce36b21b37bf49f2ed035dafe48899c0e8cbe7`，原三文件pin校验和SDK字节未变。hook依据：该文件 `_execute_run` 960-967在事件循环调用 `_create_agent` 后进入worker；`_run_agent_sync(self,run,agent,approval_notify,*,_api_server)` 781-847包含会话绑定、agent.run_conversation及原finally清理，返回原(result,usage,runtime)元组。FS仅在现有async admission wrapper设置每run ContextVar，在现有agent构造边界和这个sync函数前后观察；不复制executor、另建runner、全局异常解析器或改变原catch/status逻辑。原异常同对象抛回，原返回值同对象返回；官方catch后只剩字符串且不经过这些边界的错误仍为executor/unknown，不补造旧失败run的子类。

只有FS材料mg会话进入临时诊断表，FC/human不追加诊断；wrapper在重复make_adapter时不重复安装。每adapter短RLock只保护小型内存记录，ContextVar隔离并发run；所有终态及executor退出均清理，迟到worker不能重建记录。终态已持久的固定白名单快照可在SDK迟到的上下文状态更新中保留，不保留临时异常对象或输入。原admitted-input终态清理、停止、三工具及上下文proof、CAS/单POST/原ID恢复、原loopback/provider装配不变。旧record无诊断则继续缺省unknown，现有最小材料resolver不因此新增HTTP字段。

TDD先运行新增用例观察当前缺诊断：原两个worker测试通过，新用例因无字段/记录失败；随后完成RED→GREEN。追加对抗证明了终态带context重发不能丢快照、未知异常metaclass hash不能覆盖原异常，再最小修正。最终原pr-fast.units入口 `test_conversation_file_loop` 15项（11 adapter/4已有file loop）和原channel消费者 `test_channel` 12项均0failure/error/skip；原store.load_tests已加载整个file_loop模块，不需CI接线或旧Core/native/发布全套。两个改动Python文件按3.9语法核对，diff --check及三路径范围核对通过。没有安装依赖或放宽原外网/Popen围栏。

另在本地固定公开源码中AST提取原 `_execute_run`、`_run_agent_sync`、`terminal_run_status` 真正函数体（保留源码行号、先核完整pin SHA），用原units围栏和依赖夹具执行5项对照：构造异常、agent调用前注入异常、agent返回failed、成功、取消。5项通过，确认阶段/白名单类、实际原finally/checkin/终态清理和同异常传播；回答/推理/secret哨兵不进入诊断。最初夹具缺少SDK事件回调导致5项失败，补齐夹具后通过，未为此改SDK或生产逻辑。这是**函数提取+代理依赖的本地契约证据**，不是实际SDK进程、真实provider或原run失败复现；完整SDK/当前Linux CI/生产装入与付费复测均待后续独立阶段。本轮只交完整三路径候选供Personal集成/独审，不包含发布授权。


## 已装1b20的worker诊断窄增量：本地发布装配候选（2026-11-01）

用户明确“允许复测，测试ok后部署”；本轮只完成第一阶段本地装配候选，部署及真实付费复测等Personal对最终合并SHA另行交接。原A worktree/origin/分支复核干净，fetch确认main仍为指定 `35a839b9efb7e85a5fd20b59a39d670245cd7808` 后正常ff；不合主控后续记录、不碰Personal未提交导航。只改本模块deploy/runtime_prepare.py、runtime_release.py、test_runtime_materials.py及本附录。worker本身复用PR729已审blob，不改SDK/HTTP/B/Core/UI/controller/proxy/IAM/预算或原冻结publisher。

新增显式 `--worker-diagnostics --followup`，descriptor字段worker_diagnostics、manifest字段workerDiagnostics。唯一合法installed baseline为 `1b20b91f2e7e023d90a0197053916ba9a59978e6`，backup=`/var/backups/fs-navigation-20261006/nav-20261101T062133Z`，manifest SHA=`16615694e66cda7dcfffa4ba55381d21071b51cf45b3597be303f5ba2af4f235`，journal SHA=`912511fd8fc877d9155ca6fec30ec8bdf9ff5bd94b94d6443d4f764e529c2446`。同原installed_baseline逐项核成功journal、其manifest和固定Git LF beforeSHA，24现存/46保护/NEW空/8已装模块保留；不拿随读当前SHA充当合法基线。actual changed target必须精确只有 `/opt/fs-hermes-fc/hermes_worker.py`，零delta或附带HTTP/UI/其它目标均拒绝，不能套用旧GoalTasks/diagnostics模式。

本地逐一比较1b20与35a839b9的23个Git源载荷：仅worker从SHA `1016736b159f0612c1a8559ddb148faa0e028717b8d058fac4d9c32028cb6076` 变为已审SHA `78b586984234a11418c7151ec494d8e83fa7b9659d607c201c0435ab2ac0e100`，另22个源原字节相同；第24项Nginx保持成功proof的SHA `b792f18b8d1b322139f8be96bb5052ff53a79e82dac7a607cbe102e199b06302`、0600/root，不重套body-limit补丁。此为本地Git比较，不冒本轮现场已重新核收。

prepare/inspect/apply仍沿原fresh<=1h、完整before/mode/root、installed proof、protected、锁/准入/provider/UNKNOWN/quiescent/DB/journal/backup约束。该模式只接受runtimeBefore三服务active、workerImageSource=container；prepare禁stopped fallback，inspect及每次guard、重启成功后均核实际容器image与active。失败/inactive/镜像或来源漂移/容器缺失均拒绝，不用本机镜像存在替代运行证据。只在原writer实际写worker；另外23目标仍CAS并备份，原atomic适配保留其inode/mtime，原失败回退恢复worker并保留全部8个已有模块。

重启仅调用原HERMES_WORKER_SCOPE及原readiness/capabilities健康合同，同一admission fence和数据库锁保持；原worker启动代码不构造FS TaskStore，未修改host模块，因此本模式不调用stop_then_unlock_database或DEEP，不重载range。Nginx不测试改写、不reload。原冻结writer/locks/fence/provider/rollback字节不变；若真实启动/回退失败仍原异常传播、原journal保留，不作恢复态成功或吞错。正式发布时仍需最终Git LF pack、新stage/fresh现场prepare/manifest、inspect和单次apply，不可用本地候选或旧stage。

TDD先确认缺worker followup红断言，再最小实现；补充零delta拒绝也先红后绿。最终原 `python -B -c "from tools.pr_fast import units; units('releases/fs-dashboard/hermes-conversation-20261018/deploy',['test_http','test_release','test_runtime_materials'])"` 25项0failure/error/skip。新综合用例真实临时文件系统+原validate/inspect/apply/rollback，固定Git/proof fixture，覆盖成功、worker restart异常、restart返回但真实容器读回缺失的失败回退，另23目标inode/mtime保持、24/46集合及8模块不删。负向包含旧proof/Git/journal/protected/before漂移、额外HTTP/零delta、过期基线、混用marker、失败/缺失/不同image或来源的容器。systemctl/docker/原锁边界为合成夹具、Windows目录fsync与mode沿既有测试适配；不是Linux真实锁/服务/SDK/生产验证。原runner外网/Popen围栏未放宽，3个改动Python文件3.9语法及diff --check通过，无需CI驱动新增入口。

本阶段0SSH/生产读取/浏览器/材料POST/result/模型/部署；不重复旧Core/knowledge/native或已验worker输入。生产仍仅历史已核1b20，两个封存请求不访问、不重发；旧record没有诊断继续unknown，旧404与费用及run_2fa6490e5755454892c6f897bb0222f5根因不由新候选倒推。当前仅交完整四路径fixed候选供Personal统一PR/最新SHA独审/必要LinuxCI；原生零模型检查、实际发布/正常FS新意图付费复测及视觉均留第二阶段，未宣称完成。


## PR730最终82edf诊断worker发布与首个新合成复测停止点（2026-11-01）

用户明确允许复测、测试通过后部署，Personal确认PR730最新SHA独审/LinuxCI满足。A原worktree/origin/分支干净，fetch确认main正是最终 `82edf03573c3fed796d7a7ed2784134c5dd1f7ec` 后正常ff；没有以主控后续记录作source。本轮复用PR729/730有效输入，不重跑旧worker/Core/native/knowledge，不改任何源代码、publisher或配置。新Git LF pack显式worker-diagnostics/followup：payload SHA=`3e185b87aa49f453fe77ddfb0abebefadc91e837349a9aab19bebbee0540eeda`，593920-byte tar SHA=`53b1df0716b6c8153e6b3476b5b440973bb6bf402ec82299716d468b86147054`；新stage=`/var/tmp/fs-worker-diag-82edf035-20261101T110803Z/stage`，baseline=`2026-11-01T11:08:57.355629+00:00`，manifest SHA=`a9be5243f473129379e6662854be5236d9c69f08d86f97693d66039be86d5656`。严格绑定上述1b20/nav-20261101T062133Z成功manifest16615694…/journal912511fd…原proof，不复用旧stage或随读hash生成任意合法基线。

11:09:19Z现场24 before/46保护及root/mode匹配、NEW0/8已有模块保留，collector无持锁者、inactive/dead，三服务active、实际container使用固定image。原inspect sourceCAS/protectedCAS/releaseReady通过后，仅一次apply成功：backup=`/var/backups/fs-navigation-20261006/nav-20261101T110803Z`，journal SHA=`46b6f0f1258fb190330544ae0b1538504f0024457d0b2b7336999c42dc3bce67`，状态仍原 `applied-awaiting-actual-http-role-acceptance`。11:10:31Z读回24 afterSHA/root/mode、46保护SHA/root/mode全部匹配；唯一写目标 `/opt/fs-hermes-fc/hermes_worker.py` afterSHA=`78b586984234a11418c7151ec494d8e83fa7b9659d607c201c0435ab2ac0e100`。另外23目标inode/mtime/hash/mode/root全保持，8模块没有删除。原worker scope/readiness只重启worker PID3801→4569，range3960/Nginx31780保持，无range stop/restart或Nginx reload。新container=`4a222e81c35e6ab77a2f5147c340ab2b706750cc14bd54af7179d94152a41831`，image=`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`，Running=true，StartedAt=`2026-11-01T11:10:05.388170417Z`；三服务active、range200/ok=true、匿名worker401。此处只确认软件发布，不把健康或诊断代码装入等同材料执行通过。

通过现有正常FS身份、自建BrowserAct会话新建专用cid=`2222cfa63d154f978b10ac33c31d2426`。原入口启动代码自动选择了最近的旧合成cid，A随即点击新会话，没有主动查询/重发封存material request或打开result；启动前普通detail/files网络没有独立留痕，不声明旧cid零HTTP。未读用户历史正文/回答或凭据，历史列表visibility隐藏且保留布局，原用户页不操作。小CSV“诊断复测82edf_205行_双倍金额.csv”上传1491 bytes/SHA=`c790fcfabf3c7668d2cfb945d12d4ac0bf22fccf0e33f955f44c85d1704855b3`，205数据行+表头，夹具amount预期42230。服务端冻结metadata fid=`4fd8bc6e44f4db093f3cc5def3448665`、v1、parent=null、相同size/SHA，操作read；预期行数/求和不冒模型计算结果。首次offscreen索引点击未选中，滚动后原生selector点击且checked=true/1附件已核，才提交。

11:14:20.456Z正常UI仅一次材料POST，request=`material_7c92cee4a1374575ab018ea786d83ba8`，接收202，没有丢202注入(discarded=false)，没有重POST/换ID。自动正常原ID状态GET共2次，11:14:25.336Z得到failed后停止后续付费。真实task=`04289db4e5d409b1ba56523b434ded03`、lease=`c5c645afc3a9fcfee83e3ad2e574c00f`、session=`mg_9679ba835fc4542a6d74567357e3628bb034ee143aab3b37936d2de8762812e5`、run=`run_13bce8847c1d4b8caf2ca3387b0a36ed`；持久attempted=1、body fingerprint=`d3e142fa6119bacefed63ba74870c2120ed2070e5e5277fb77576c15ab79ae28`。没有独立抓取官方POST网络，attempt字段不冒完整官方网络计数。实际接受context receipt原session/run/payload匹配，payload SHA=`d38c908a4132399e40dcb35effd15b43a8b896ffe10e458637f81ac7e544946d`、input SHA=`58faae779d56e0e7a76a21ba78734dc276354c1a4eb3cf4f97a3e2f34dc1d2e9`、实际完整system SHA=`08c777eefdd6561abe2b678c12f7e6db6af853011992cae18f36304553925f79`；input_verified/prompt_present/native_memory_skipped=true、精确三文件wire工具。coverage=[]/generated=[]，没有实际分页参数或total_rows读回，未证明205数据行或42230，未宣称分析完成。

按本次明确白名单，仅对新run在官方原库mode=ro/query_only SELECT状态及 `runtime.fs_material_diagnostic` 的version/phase/exception_class/reason四列；以新任务持久mapping的run/session/runtime-key/full-body fingerprint核唯一行并绑定task/lease，不构造官方store、不prune/commit、不SELECT整个status_json/error/output/messages/私有推理。实际官方status=failed，受控诊断=`{"version":"materials_diagnostic_v1","phase":"agent_returned","exception_class":"unknown","reason":"unknown"}`，DB stat前后稳定。可确认观察到了agent返回失败结果，不可由phase推断provider已调用或内部具体异常。旧run的缺诊断、旧404或费用不补造。

仅本新task的原TaskStore与daily账本必要只读对账：task FAILED，真实owner/cid/task join、原run/lease匹配，gateway reservation/model_call行0；TaskStore tokens/rounds为0不证明供应商调用/usage为0。原policy=`no-pilot-quotas-deepseek-direct-stream-tokens-only-v2`、现有DeepSeek/general配置deepseek-flash；供应商调用数、response_model、provider tokens、人民币费用和actual_backend_version均unknown，cost_microcny=null，不补0。此包仅启动1个模型任务，XLSX修订、派生追问、running-stop均未开始；不解除到额或真实配置/平台限制，不更换账户/供应商/权限/预算。没有点击失败“查看回答”、没有/result、没有读取错误正文或失败回答，具体根因仍未知，未实施运行修复。

已实际view当前部署的合成失败态桌面浅色1904×985和暗色1904×985图，以及390×844浅色收起/展开图；无横向溢出，短任务失败和长目标在桌面可见。390图仅顶部布局，失败卡在下方未滚入画面，不能声称窄屏失败卡交互完整验收。原生Enter换行、空白CtrlEnter无新POST、Tab到附件summary可见2px焦点；未触发新turn。BrowserAct公开自身CDP通道与已安装Playwright仅控制本自建合成页viewport/截图；首个resize在断开时恢复桌面，已明确更名为resize-reset-desktop拒作窄屏证据，真正390尺寸与截图在连接存续时同步核定，不使用CSSzoom/deviceScaleFactor冒缩放。截图已脱敏历史标签、不移布局；实际原生200%仍未验。浏览器CLI及临时收据脚本曾有UTF8默认解码/转义和可选PIL不可用的本地错误，只修ignored验收记录脚本、改用标准库读PNG尺寸，未导致新模型POST或生产代码修改。主题清理单独自建会话确认light/light后关闭；两个A自建session均已关闭，用户原页不导航/关闭，不提取Cookie/Profile或伪造XAuth。

稳定共享目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-WorkerDiagnostic-Deploy-20261101T110803Z/`，index SHA=`f5527c3c4fb6fc2ba3f46daeeb253e5f045743f513d051d8b540f2dab661597d`，21文件bytes/fullSHA已逐项自核。含pack/prepare/inspect/apply/前后24+46元数据、software-readback-summary、真实新task浏览器POST/状态审计、任务/所选文件metadata、官方四字段、fixture、fresh-visual-checks、截图和summary。有效图为task1-failed-desktop-light.png、task1-failed-desktop-dark.png、task1-failed-390-light.png、task1-failed-390-expanded.png；各时间/视口/主题/bytes/SHA见收据。错误正文、模型回答、推理、认证或生产源码不入收据。此追加只作一次模块记录提交，不作部署source；生产运行source仍唯一82edf。结论为软件发布读回通过、新诊断持久化可核，材料执行未通过；成功分页/修订/下载/派生/stop、第二身份/撤权/A2 scope及完整视觉均未验，交Personal最终独立核收，不继续付费或自行扩诊断权限。


## 材料transport受控单文件装配：A本地候选及B固定组合（2026-11-01）

用户明确批准限定修复与验收：B独占transport业务校验与新测试，A仅补原publisher单文件增量。A开工原HEAD=`f99c9c2a70d16f44f599d9fcf0a00d317a7e63e9`、origin/原分支干净，完整保留此前记录，无reset/clean、main fetch/ff或Personal未提交目录读取。A实际只改本模块deploy/runtime_prepare.py、runtime_release.py、test_runtime_materials.py及本附录；不改冻结base/CI/worker/SDK/HTTP/UI或B源。本轮无SSH/浏览器/生产读取/error/result/模型/部署。

新增显式 `--material-transport --followup`，descriptor为material_transport、manifest为materialTransport，与三种旧controlled模式互斥。唯一已装proof为source=`82edf03573c3fed796d7a7ed2784134c5dd1f7ec`，backup=`/var/backups/fs-navigation-20261006/nav-20261101T110803Z`，manifest SHA=`a9be5243f473129379e6662854be5236d9c69f08d86f97693d66039be86d5656`，journal SHA=`46b6f0f1258fb190330544ae0b1538504f0024457d0b2b7336999c42dc3bce67`。不伪造原proof的第25个target：原manifest仍须恰24个目标，transport仍在其原46保护记录中。promoted_transport_sha核原保护路径集合完整/无重复、transport仅1条且SHA精确 `e677a186a893c346379ba572576afdfbd412612cc5c63146751182558743f843`，再同82edf固定Git LF baseline整体比对；缺行/重复/错误SHA/额外保护/把transport塞入旧targets均拒绝。observe同样将此保护记录作为transport before，不能拿随读磁盘SHA替代授权基线。

新scope沿原SCOPE，25现存/45保护/NEW0，唯一实际变化 `/opt/fs-hermes-fc/transport.py`，源路径 `releases/fs-dashboard/hermes-v2-core-20261020/source/transport.py`。0delta、附带其它目标、保护遗漏/重复、旧proof/Git/journal/transport before漂移、超1h、stopped/假image/缺实际container/模式混用均拒绝；原24目标仍完整CAS与备份而不写，8已有模块保留。原writer/locks/admission/provider/UNKNOWN/quiescent/DB/journal/backup/root/mode及成功active/image/health要求不变，没有新runner或发布链。真正发布只能最终合并SHA新LF包、新fresh baseline/stage，不能拿本地候选或旧stage执行。

transport由原FS host加载：仅复用原fence.stop_then_unlock_database与DEEP/readiness重载range，worker/Nginx不restart/reload；inspect在隔离候选runtime路径import transport定义并核__file__，不构造service或调用模型。每次inspect/guard及成功重载后仍要求真实container、同image与active，无stopped fallback。失败沿原rollback恢复transport原字节，它是existing target不能删除；其它24文件inode/mtime保持。没有放宽FC工具边界、权限、预算或白名单。

TDD先观察缺transport模式红断言，再最小实现。新综合用例保持旧24/46 proof形状，在真实临时文件系统上走原validate/inspect/apply/rollback；覆盖成功、range重载抛错、重载返回而container读回缺失后的回退，核实际调用仅DEEP/fence、24未写metadata及8模块存在。额外将删减/重复保护、额外target、owner/mode/before、过期、混合marker、零delta的manifest自身写为approved后，用新冻结validator核拒绝，避免仅靠manifest对象不等“假测”；重复保护先红后补本mode严格45条再绿。原frozen base字节、旧测试方法与runner围栏不改；OS/服务/锁边界为合成夹具，Windows目录fsync/mode沿原测试适配，不能冒真实Linux/启动验收。

B固定候选 `154280e83de5ce34d37f4846ad281112aa780ac9` 到达后，A按授权只fetch该分支并普通merge，merge=`0d8679a71e7949a88ed30a4b17ace89518cdf831`，无冲突/保留A未提交实现及上次记录；合入的是固定已提交内容，不读其dirty README/AGENTS/主控材料。B实际三路径transport.py/test_material_transport.py/test_core.py与固定候选逐blob无差异。新增 `test_material_transport` 原units独立8项通过0skip，实际fixture用现行26proxy/21runs，真实loopback200/400/403与任务scope守卫；这是本地组合，不是供应商调用。合并后受影响原deploy显式test_http/test_release/test_runtime_materials共26项一次0failure/error/skip；3个A Python文件3.9 AST及diff --check通过，无旧WinError/LF失败冒报、无Core219/native/知识同输入重跑。原CI列表已有test_runtime_materials，B原Core已load新8，无额外驱动缺口。

B修复后transport Git LF预期SHA=`2ef021e7b3bc3efd76632cf1924b538860da5422a08a4a751d2a932ff6f1a23d`。A提交后以固定HEAD生成本机独立pack，逐项核其installed baseline=原proof24个目标SHA+唯一transport保护SHA、25目标/45保护以及唯一transport候选差异，具体source/payload/字节表见本包共享收据；包只在本机，不上传或当作发布。Personal后续统一PR最新SHA独审/LinuxCI/正常合并，再交最终source进行现场prepare/apply与必要新意图复测，本轮不提前实施。

此包只证明本地已匹配协议兼容缺陷得到针对性修复和发布装配可审；未取得历史实际error/body/HTTP状态，不能把旧run首触发分支判为tool_allowlist，也不排除187出站或供应商限制。三个旧材料请求/run全部封存，不读取或重发，旧费用/因果仍unknown；原单次error诊断没有续读授权，本轮亦不续读。生产最近已核仍82edf，未新增业务/账号/权限/配置或模型调用。本节随完整A候选一次提交供主控集成，不是新部署证据。


## PR731最终b362 transport发布通过，首个新合成复测失败停止（2026-11-01）

Personal交接PR731最终source=`b362bd3bfb3fc4eca4bcf1d47cb3f0550c8c6c04`，已核独审及LinuxCI条件。A原worktree/origin/分支干净，fetch确认main恰为该SHA后正常ff，完整保留f99旧记录，不以主控收口head或00acf本机descriptor发布。复用未变的Core219/发布26/新8等证据，不重跑旧全套/原生/知识。已有安全夹具只有SDK构造/函数边界，不足以复用成actual first-request准备；本轮明确未做该项，未新增依赖、模拟门禁或构造正式service，也不因此声称SDK请求字段已验证。

新Git LF pack显式material-transport/followup，payload SHA=`d8dbe2f7505dacaa8ca1afd8fe20dbf5571affdbbd7dbf8cb14c9fe202632c07`，614400-byte tar SHA=`97ae816c414735daef4d7def352be8188b3eb1bdbb0553a08dc7c77c731f9b4c`。12:37:39Z collector自然inactive/dead且无持锁者，没有抢锁/stop/timer修改。新独立stage=`/var/tmp/fs-material-transport-b362bd3b-20261101T123702Z/stage`，baseline=`2026-11-01T12:38:01.422646+00:00`，manifest SHA=`02d2d4623467aaf62f617775a7c47084b6005cf26e8da150025d12be7a052833`；精确钉82edf/backup nav-20261101T110803Z/manifest a9be5243…/journal46b6f0f1…的24目标+46保护原proof及Git before，只提升原transport保护记录为existing target，25现存/45保护/NEW0。原inspect sourceCAS/protectedCAS/active/image/fresh/releaseReady通过后，仅一次原apply成功，backup=`/var/backups/fs-navigation-20261006/nav-20261101T123702Z`，journal SHA=`92b65d1a2d17a8d979b5b1011002c35ff1b80997e51b3e7e8db01cc43699a82d`，原状态 `applied-awaiting-actual-http-role-acceptance`。

12:39:11Z实际25 afterSHA/root/mode、45保护SHA/root/mode全匹配。唯一变化 `/opt/fs-hermes-fc/transport.py`，before=`e677a186a893c346379ba572576afdfbd412612cc5c63146751182558743f843`，after=`2ef021e7b3bc3efd76632cf1924b538860da5422a08a4a751d2a932ff6f1a23d`；原24目标inode/mtime/hash/mode/root全部保持，8已有模块保留。仅原fence+DEEP/readiness重载range PID3960→23289；worker4569/Nginx31780不变，3服务active，range200/ok=true、匿名worker401。真实container=`4a222e81c35e6ab77a2f5147c340ab2b706750cc14bd54af7179d94152a41831`、固定image=`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`、Running=true及StartedAt=`2026-11-01T11:10:05.388170417Z`前后完整一致；worker不restart、Nginx不reload，没有full main覆盖、临时生产patch、DB/UNKNOWN/权限或预算配置清理。

本轮先在自建正常BrowserAct会话打开同源favicon非会话应用页，用与前端相同的credentials:same-origin及X-FS-Advisor-Action动作头新建合成cid，201后才按明确新cid打开会话UI；无X-Auth伪造/凭据提取，不让普通入口自动选择任何封存cid。新cid=`bf4bdc01e8d243e48f86e04db5492dba`；上传“transport修复后验证_205行_金额.csv”，1508 bytes/SHA=`582b30225e1a43c93c74e934c5da3214bef9e1946f926c3cfa8c6f5058d67316`，205数据行+表头、夹具预期amount合计63345。server冻结metadata fid=`18dc275f0c946f074a6f930822f659d9`、v1、parent=null、size/SHA一致。原生checkbox checked=true/1附件确认后，使用明确新的“transport兼容修复后验证”意图做独立read任务，要求sheet0/limit<=200/offset0再200覆盖尾页；这些是本次请求与期望，不是实际阅读结果。

12:41:23.510Z正常UI单次材料POST，request=`material_a2d2c632140d448ba001be249fb5d368`，202接收、discarded=false，不重做丢202故障注入。仅1次正常原ID状态GET于12:41:24.649Z返回failed，files=[]/coverage=[]。task=`c056e24a3d10db4b4dc9417f9684567d`、lease=`b9fa4b33989dfb81af6a2a09b1c9888f`、session=`mg_8f5545e06bbce7cd9b80bc59c1538a0933ff6d7783a7e06a799cf06a92be9830`、run=`run_3ccf0540b59b4759a911664cc22a798a`。持久mapping attempted=1，body fingerprint=`cab1a65592711b9ae356beaec11cb854b51380725036395b2ca8a140f839266c`；这不是官方网络POST次数的独立抓包证明。客户端材料POST=1，另新建会话和上传各自原POST不混为模型重试，没有换ID补发。

实际context receipt绑定原session/run、精确三文件wire工具及input_verified/prompt_present/native_memory_skipped=true；payload SHA=`f672cbd7147bb5c18016b786168339183bbe2ebe298da832c4c48b1d3f71cfc5`、input SHA=`e0a4eba987911f1c96890b627418b0489d7aa793f0c6d0611201214dd889edae`、实际system SHA=`08c777eefdd6561abe2b678c12f7e6db6af853011992cae18f36304553925f79`，与server冻结metadata投影相符。没有真实页参数/total_rows/求和回执，205行和63345均未验，不把accepted proof或HTTP202当材料分析成功。

按本阶段既有范围只读新任务必要映射/用量元数据及官方同一新run的status+runtime.fs_material_diagnostic四字段，mode=ro/query_only；run/session/key/fullbody fingerprint唯一匹配、task/lease绑定成立，官方库stat稳定，不SELECT error/整JSON/output/messages/推理、不构造官方store或HTTP result hydrate。官方failed，诊断为 `{"version":"materials_diagnostic_v1","phase":"agent_returned","exception_class":"unknown","reason":"unknown"}`。只证明已观察agent返回失败字典；具体错误类型、HTTP状态及首触发分支未知，不能猜request_fields、187白名单或供应商策略。未续读上次未完成的error投影，也没有对本新run额外error授权或原文读取。

该task原gateway账本0条、TaskStore tokens/rounds=0，仍不证明供应商调用/usage/费用为0。原DeepSeek/general、配置deepseek-flash、policy=`no-pilot-quotas-deepseek-direct-stream-tokens-only-v2`不变；供应商调用数、response_model、provider tokens、人民币费用和actual_backend_version均unknown，cost_microcny=null。首任务失败立即停止后续：总任务1，XLSX单格修订/immutable下载/派生追问/running-stop均0，没有为外观/定位再发模型，没有改quota、账户、权限、provider或重试。按本次“失败不继续凑视觉”边界，没有fresh截图/浅暗/390/键盘/原生200%或结果卡验收；用户原页不动，历史标签隐藏核效，主题未修改，自建session已关闭。

稳定共享目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialTransport-Deploy-20261101T123702Z/`，index SHA=`0807cd83411860520b123b51193e981e5d326f830a514274758e1443f6174205`，17文件bytes/fullSHA逐项自核，含collector/pack/prepare及原stdout、inspect/apply、25+45前后/软件summary、新cid/fixture/真实客户端审计、绑定映射/四字段/所选metadata和总summary，无生产源码/配置/凭据/DB/error原文导出。三旧请求/run均未访问或重放，其费用和历史因果unknown不变。结论仅【b362 transport单文件软件发布读回通过；新材料真实执行仍失败，根因未知】，不能由本地兼容修复倒推旧run已证根因。本附录仅一次记录提交，不作新部署source；交Personal独立核收后再决定必要下一诊断范围，A当前停止额外现场/付费/GET/源码变更。


## 阶段1材料stream兼容：b362精确单文件增量与真实SDK解析候选（2026-11-02）

本轮只服务阶段1材料失败。原A分支从干净 `bfea871a5cdda9f93a9db207ac9b36cfd2746742` 正常fetch并merge B固定 `730e9d653df8aa7b5ee6f254eccfe1d7fd2d7abc`，merge=`da5a42ebe4787ade5d84cb587b8ebf71f40c915f`，无冲突且保留全部旧记录；不读Personal未提交目录。A实际只改deploy/runtime_prepare.py、runtime_release.py、test_runtime_materials.py与本附录，B transport及测试不并改。最终提交后按主控补充要求，在干净原分支正常合入最新main；具体最终提交、基线和逐路径比较随共享收据回交，不把主控记录head或本地descriptor当部署source。

原publisher新增互斥 `--material-stream --followup`、descriptor `material_stream`、manifest `materialStream`。唯一installed proof为source=`b362bd3bfb3fc4eca4bcf1d47cb3f0550c8c6c04`，backup=`/var/backups/fs-navigation-20261006/nav-20261101T123702Z`，manifest SHA=`02d2d4623467aaf62f617775a7c47084b6005cf26e8da150025d12be7a052833`，journal SHA=`92b65d1a2d17a8d979b5b1011002c35ff1b80997e51b3e7e8db01cc43699a82d`。此为25现存/45保护/NEW0的已装基线，不走旧82edf的24→25保护提升。原proof必须已含唯一transport target，25目标及45保护集合无缺失、重复或额外项，并与固定b362 Git LF整体一致；transport before精确 `2ef021e7b3bc3efd76632cf1924b538860da5422a08a4a751d2a932ff6f1a23d`。B新transport Git LF为 `e682d8659812cf5b3a9cc44f3011a7f3de0a204c830855cbff2a85e1573c3052`。

唯一实际delta为 `/opt/fs-hermes-fc/transport.py`；0delta、附带其它目标、旧82proof/Git/before漂移、集合遗漏/删重、混marker、超过1h、mode/root漂移、inactive或非真实container/image均拒绝。其余24目标完整CAS及备份而不写、inode/mtime保持，8已有模块不删。原冻结publisher、writer、锁/准入/provider/UNKNOWN/quiescent/DB/journal/backup/失败回退保持。仅原fence+DEEP/readiness重载range，worker/Nginx不restart/reload；transport是existing文件，失败恢复旧字节而非删除。未来发布仍须最终已审合并Git LF、新fresh现场baseline/stage/manifest、inspect及一次apply，本候选不上传或发布。

TDD先见缺新模式红断言，再实现。新增综合用例覆盖真实临时文件系统的原validate/inspect/apply及range重载失败、重载后真实container缺失的回退，检查24未写metadata和8模块保留。第一次原deploy三模块27项有3个error：恶意混marker测试在同一模块实例内改变模式globals，泄漏至随后旧82模式用例；补测试进程状态隔离，不改发布保护。修正后同原 `python -B -c "from tools.pr_fast import units; units('releases/fs-dashboard/hermes-conversation-20261018/deploy',['test_http','test_release','test_runtime_materials'])"` 明确27项0failure/error/skip；合入B后新增 `test_material_transport` 原units明确14项全过0skip，不重跑Core225/native/知识。Windows原目录执行，无LF或socket失败被掩盖；服务/锁为合成夹具，Windows mode/fsync沿原测试适配，不冒Linux现场验收。

本机无OpenAI/httpx，不安装。经正常工具审核，只执行一次既有play187固定image `sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544` 的network-none/read-only/tmpfs/no-host-mount隔离容器；无pull/build、生产模块构造或真实配置/凭据/业务库/旧run访问。输入14115bytes/SHA=`dd72cb8a065e41f3ba5dfe61e69c5e8e3f879bed4a6c4c966f56b4b41bdaf029`，仅固定B实际 `_completion_events`、原pilot `encoded`纯函数及合成harness/已审拒绝守卫。SDK本身真实导入且未摘取/替换：OpenAI2.24.0、httpx0.28.1、Python3.14.7，实际_base_client.py SHA=`383b1acf9de56a41533ca7fd1a39836f68a396f212b938a9c75f68a71c895347`精确匹配。

真实OpenAI客户端/迭代器通过MockTransport解析B实际builder字节：UTF8文本+usage、两tool_calls含index0/1及原ID/参数+usage、无usage文本共3项；均正常finish、一次DONE且迭代终止。400/403/503合成JSON分别传播真实BadRequestError/PermissionDeniedError/InternalServerError，不误编码成SSE成功。每项Mock POST恰1且SDK retries=0；成功项builder及合成gateway各1，错误项均0。共6项通过，真实provider/网络transport=0，socket/DB/文件越界=0；SDK可选平台探测有1次进程尝试被原守卫在OS执行前以不可用错误拒绝，实际子进程0。错误JSON是明确合成Mock响应，真实loopback与原guards由B14覆盖，不能把两层混称真实服务或模型成功。保留3份合成SSE原字节供独立复核；该响应是完成单次回执后的缓冲流适配，不是逐token实时生成。

稳定共享收据目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialStream-Candidate-20261101T163251Z/`，index逐文件列bytes/fullSHA，含harness/runner、输入metadata、真实SDK结果及3份SSE、第一次失败/最终发布组合与B14日志、最终Git pack/状态分层说明。无生产源码/配置/DB/错误正文/回答/推理导出。此SDK检查不重跑AIAgent首包、不改变实际stream、worker/proof/discovery或global配置，亦不生成正式execution receipt。

已知未闭环：原未改的合成SDK discovery首包在新transport仍停tool_allowlist/gateway0，只有显式direct三文件schema变体通过，不能宣称原首包全通过或全局关闭发现。历史真实v1 direct3 proof保留，但不能倒推生产配置/历史首失败分支。生产仍按已核b362，历史材料失败/187限制因果/人民币费用unknown，所有封存请求不读、不重发。本轮0付费/新FS任务/部署/重启/浏览器；实际正常入口CSV/XLSX读全算对、确定性修改、不可变下载和派生追问及视觉仍待最新SHA独审/CI/合并后受控验收，不开展阶段2。


## PR735最终9edb包：collector预检锁忙，未进入现场准备（2026-11-02）

Personal交接PR735独审/必要CI通过及最终source=`9edb8827c0bc21fce4173030bd09b7388b19c866`。A原分支干净、origin正确，正常fetch确认main恰为该SHA，再ff到该最终merge；tree=`676de9f628782d1b516ac259f5a1d0814884b7e6`与已审候选一致。复用已核deploy27/B14/真实SDK6，不重复SDK/native/Core/知识，不改任何运行源或配置。

已用最终Git原字节在本机生成全新 `--material-stream --followup` 包，payload descriptor SHA=`956df248d4aa5b5acfe34fb66b2c79ff96ec0bf5940d878279555e1b027dde87`；645120-byte tar SHA=`dac6f974e9331d833d8734bfd4994ef214cf030ad9e8cbbf29afed906cd1b8ff`。精确绑定上一节b362/nav-20261101T123702Z/02d2…/92b65…成功proof；本地Git比较为25现存/45保护/NEW0，唯一transport before2ef021…→after e682d865…，其它24目标字节不变。计划的新release ID=`nav-20261101T165224Z`、新远端目录=`/var/tmp/fs-material-stream-9edb8827-20261101T165224Z`；两者仅在本机context预留，未上传或创建远端stage，未生成现场fresh baseline/manifest/backup/journal，不能把本地pack当软件已安装。

经正常工具审核，只读collector已知锁及服务元信息，于 `2026-11-01T16:52:49.679091+00:00` 观察到collector.lock由PID3139/python3持WRITE锁；fs-transaction-collect.service为Type=oneshot、MainPID=3139、ActiveState=activating、SubState=start、ExecMainStartTimestamp=`Mon 2026-11-02 00:48:59 CST`。这是该时点真实占用，不是未来状态保证，也不是本次apply抛锁异常：本轮没有调用publisher prepare/inspect/apply或实际尝试获取锁，预检即停止。没有轮询、抢锁、stop/kill、改timer、清UNKNOWN、变更权限或服务。

稳定共享目录=`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialStream-Deploy-20261101T165224Z/`，index列pack/collector_preflight/summary三份metadata的完整bytes/SHA。无生产源码/配置/DB或业务内容导出；未新开浏览器session、未调用任何材料GET/POST/result/error或模型，所有封存请求保持、旧费用和因果unknown不变。生产仅沿此前已验b362记录，本次未重新核25/45现场SHA或服务/image，不能补称当前全量读回通过。结论仅【最终9edb本地包就绪；collector预检锁忙，软件尚未安装，真实材料及视觉验收未开始】。按本轮边界回交Personal后停止，后续自然释放需另有据核查，不能自动重复发布；本附录纯记录提交，不作部署source。


## PR735最终9edb发布读回通过，正常新会话验收被工具审核阻断（2026-11-02）

本轮只推进阶段1。17:51:03Z一次collector观察为锁无持有者、inactive/dead、MainPID0，才继续原授权发布；复用最终9edb原GitLF载荷956df248…/645120-byte tar dac6f974…，不夹带其它PR。先核旧计划nav-20261101T165224Z无backup/stage，再使用全新stage=/var/tmp/fs-material-stream-9edb8827-20261101T175040Z/stage、release-id=nav-20261101T175040Z；fresh baseline=2026-11-01T17:51:51.833785+00:00，manifest SHA=74270ff2d91e195a8279572ba48aaa35a4189a75597bceaa9496a4fbe9116088。原b362 proof、25before/45保护/root/mode/active真实固定image及quiescent、原inspect全部通过后，仅一次原apply成功，backup=/var/backups/fs-navigation-20261006/nav-20261101T175040Z，journal SHA=831ca7e02476aa50ef9fb25c2b3cc52c28ad562979fff26a938992746a6fc3e7，状态applied-awaiting-actual-http-role-acceptance。

25 afterSHA/root/mode、45保护及其mode/root匹配；唯一transport2ef021…→e682d865…，其它24目标inode/mtime保持、8已有模块仍在。仅range PID10201→21750；worker10045、Nginx31780不变，三服务active，range200/ok=true、匿名worker401。真实container7af81e7fd24b3d6de9cb0ba37492cb640a712ec4ab3d1f59985d34621b374b4a、image8251bc53…、Running及StartedAt=2026-11-01T14:06:29.450947631Z前后相同。软件已安装，不能与此前预检等待混记；没有第二次apply、SDK/config/权限变更或临时生产patch。

随后仅在自建BrowserAct会话打开同源favicon非应用页，避免自动读取历史cid。创建新验收cid时，harness把X-FS-Advisor-Action误填为1，POST /api/hermes/conversations得到403/same_origin_required，未返cid；当前前端实际使用submit。纠正为页面原submit的尝试被auto-review在进程启动前拒绝，理由为403后改变动作头重试可能绕过同源/授权边界，禁止换手段绕过。故停止，不改入口或认证，不把403猜成账号过期或材料模型错误。已关闭仅自己创建的fs_material_stream_9edb_20261101t1750，用户原页不动；上传0、材料POST0、模型任务0、无旧run/error/result读取，历史费用unknown仍保留。

稳定共享目录C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialStream-Resume-20261101T175040Z/，index1299bytes/SHA675c58337a99d953d9dc91fcc320633b85589a5a113e5dd958b7ba6bef7eafec，8份metadata列完整bytes/SHA。结论仅【9edb软件发布读回通过；新CSV尚未开始，正常角色入口被工具审核阻断】，不是阶段1功能或视觉通过。精确下一许可为按页面原有submit动作头创建单个新合成验收会话并重新正常工具审核，不能凭本记录绕过拒绝。此为本轮一次短附录，不作部署source；未重跑旧27/14/SDK6或推进阶段2。


## c12a当前装配：新CSV一次真实验收failed，后续付费停止（2026-11-02）

本轮只测试，不部署/改源/重跑旧套件。沿用户新增明确许可，在自建正常BrowserAct会话、同源favicon非应用页，以当前前端原有X-FS-Advisor-Action: submit成功创建全新cid=3507b32df6af4abaa0a44698a80a53c8（201）；没有重复先前被拒动作的无授权绕行。当前现场装配由主控核为c12a273387a7811c71b3fbf1c040c8a7b4d1639a、bindings严格True已装、transport仍e682d865…，A不再部署或覆盖其新字节。初次页面路径误少/dashboard/fs-home前缀而404，随本地已知正式路由纠正，未额外建cid或提交任务。

新CSV“阶段1_stream验证_205行_金额.csv”1506bytes/SHA dc04932d205971fc04306481f94063cddc991652286828d688c84e32cc9c40a7，205数据行、amount合计63345仅夹具预期。正常上传201，fid=63fd50825f2b79efe83bf174686f104e，server SHA相同；真实checkbox显式唯一选中、read模式、不启局部范围后，正常UI材料POST恰1次，18:12:52.442Z得到202 queued/discarded=false。request=material_64d15ce3b33f47389140579a83504012，task=eef295043c6ac7525ba8a7d47509c99a，18:12:56.542Z running，18:12:59.076Z failed，coverage=[]/files=[]，未读全或算对、无产物，不把预期数字或HTTP202当成功。

仅本新任务mode=ro/query_only白名单账本及官方status/四字段诊断：lease=0af628e4500553a848155f722a0c26e1，session=mg_29b072d64f442d2c1262ff3336eeab3a11a4acfe34c841c4dbb9a2bb5db39317，run=run_1da8fb2fce024df3bd78fc164d49cd75，body SHA=015216ae1cb5e78a1091a1da5bd5f534bb491b7b8d0271a9215a0c539d82b56b。task/run/lease/session/key/fingerprint唯一匹配、mapping attempted1（非官方网络次数），官方failed、materials_diagnostic_v1/phase agent_returned/exception_class unknown/reason unknown，官方库stat稳定。gateway本task0条、task tokens/rounds0，不能推供应商0调用/0费用；provider调用/tokens/response_model/backendversion均unknown，cost_microcny=null，policy仍no-pilot-quotas-deepseek-direct-stream-tokens-only-v2。没有读取error/完整官方JSON/output/messages/私有推理，未点失败查看回答或/result。

失败后立即停止后续：模型任务共1，XLSX修订/下载/派生追问/stop均0，不重POST或用新ID猜参数；四组旧请求完全未访问。未做截图/外观任务，只关闭自建session fs_material_csv_c12a_20261101t1815，原用户页不动。最小稳定收据C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialCSV-c12a-20261101T181118Z/index.json，1033bytes/SHA60bbda1dcfe93121027c5a8383e4093979d42023c140059a084e363551703163，6文件bytes/fullSHA自核（夹具、context、浏览器本新cid审计、mapping、四字段、summary）。结论仅正常创建/上传/单次材料接收成立，真实材料失败且错误类别仍未知；交主控最小诊断缺口，不作阶段1恢复或进入阶段2/3。此为一次纯模块记录，非部署source。


## c12a材料守卫诊断：A原publisher单文件候选（2026-11-02）

本包只服务阶段1失败定位，不宣称修复执行。A原clean b17分支正常fetch/merge B固定c46bc32e57eb39df63e9b56f7256ed6c3ac3b66c及实际最新main=c12a273387a7811c71b3fbf1c040c8a7b4d1639a，无冲突，旧记录保留；B transport/test与fixed无diff。A仅本模块deploy/runtime_prepare.py、runtime_release.py、test_runtime_materials.py及本附录四路径，不改冻结base/CI/worker/SDK或其它运行源。

新增互斥--material-guard --followup、descriptor material_guard、manifest materialGuard。唯一基线为已装c12a，backup=/var/backups/fs-navigation-20261006/nav-20261101T180448Z，manifest SHA=b0353c2f42e0704b8f20999b0a8da26755d2ae4f0e1752cd32e54a6c9ce1ea49，journal SHA=2832922e69306c879dfcb9698b2a51997a9fdd0bf5ce50286931d406c6cd2dec。25现存/45保护/NEW0/8已有，完整成功proof、固定Git25before及current CAS/root/mode/fresh/原锁/准入/provider/UNKNOWN/quiescent保持。唯一transport before e682d8659812cf5b3a9cc44f3011a7f3de0a204c830855cbff2a85e1573c3052→after a71849b7e5e8f3c5b55967c21d5383e2ff6afa7c7c5e3c6772dc0c80209ba945；当前bindings严格True通过完整c12a Git基线保留，不恢复旧字节。拒绝0delta、混marker、旧proof、额外目标/缺失重复集合、stopped/假image、过期或before/mode/root漂移。只原DEEP/fence/readiness重载range，其余24不写inode/mtime、worker/Nginx不动；失败原journal回退恢复existing transport、8模块保留，不新建publisher。

TDD先缺模式红断言，再复用原成功/回退综合夹具。实现迭代发现并修正模式条件与夹具guard变量遮蔽，最终原deploy显式test_http/test_release/test_runtime_materials一次29项全过0failure/error/skip；真实临时文件系统覆盖inspect/apply及重载抛错、重载后容器缺失回退、24未写metadata/8模块存在及原strict集合拒绝。服务/锁是合成边界，Windows mode/fsync沿原夹具，不冒现场Linux。合并后的B原test_material_transport16项全过0skip；3个A Python3.9 AST/diff check通过。未重跑Core227/SDK/native/知识，无远端/浏览器/生产或付费调用。

另将已核合成实际SDK首包15144bytes/SHA8a9fabf869d4134b0f80af8db14764e49f77d35558629035213910ccf75ce96f原字节，经本机真实loopback及B原Grants/ScopedTools fixture回放：材料400/source fs_material_transport/diagnostic_version material_guard_v1/code tool_allowlist、turn0/gateway0；普通FC与匿名各原拒绝且不披露source/code。3分支一个测试通过，未删字段/关stream/替换tools迎合；不是完整SDK重新执行或生产有效配置/旧run根因证明。B仅exact私有异常类型标识本地guard，外部同名ValueError仍generic，原拒绝和权限不放宽。

最小稳定收据目录C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialGuard-Candidate-20261101T183711Z/，index列红绿/最终29与16日志、本地原包回放及精确Git pack metadata/summary的bytes/fullSHA。仅本机可审候选，生产仍已核c12a，历史HTTP400的producer/具体根因/费用unknown，不重读error/result/旧run或新付费猜参数。后续统一Personal最新SHA独审/CI/合并，才可新现场准备；本轮不部署、不新PR/Agent、不开展阶段2/3。


## PR740最终8e2a发布通过，新CSV失败且单次安全诊断仍仅HTTP400（2026-11-02）

原A clean、origin正确、正常ff最终8e2a456631fc5aa916c1366d087b9adbccb02f91，tree与已审一致。本次00:20:55Z一次collector自然空闲后，复用已核655360-byte最终GitLF载荷28c2a72c…/tar8b72f652…，不重pack或重跑旧套件。旧计划nav-20261101T185110Z无stage/backup，新stage=/var/tmp/fs-material-guard-8e2a4566-20261102T002030Z/stage、fresh=2026-11-02T00:21:31.077781+00:00、manifest SHA=e3a949b35d55aac5048f22094d81bc9f7db7e4f684f7463a83044371f5d4d3a4。完整c12a成功proof/Git/CAS/原guards及inspect通过后，原apply一次成功，backup=/var/backups/fs-navigation-20261006/nav-20261102T002030Z，journal SHA=fc33024f58bb1222e288e6ab1374be16b543f93756f135833238b29be9e22c74，applied-awaiting-actual-http-role-acceptance。25after/root/mode、45保护/mode/root匹配，唯一transport e682→a718，其余24inode/mtime保持、8模块存在；range8860→17437，worker10045/Nginx31780及真实container7af81e7f…/image8251/Running/StartedAt14:06:29.450947631Z保持，3active/range200 ok/匿名worker401。软件通过不是材料通过。

正常原submit动作创建全新cid eceec22304244542b1677f28faa9c793，上传唯一“材料守卫诊断_205行.csv”1506bytes/SHA dc04932d205971fc04306481f94063cddc991652286828d688c84e32cc9c40a7，fid ece05cd318987b4ca085f51f2e3325cf，server SHA一致；显式checkbox唯一选择后，00:23:57.684Z正常UI一次材料POST202 queued/discarded=false，00:23:58.100Z原ID状态failed，coverage/files均空。request=material_3c2129c89733470da866168e0b78cc36，task=85f15b08a7d0c6d1ec97f335ed98833f，lease=3dee5c15e70d8190abb37b46716a8981，run=run_7219aa025c754dbba53849e3f5841011，session=mg_899f9a5765a16d3906143f56be8f99f0656286d0a5fac08afccff9db8fe97a22，body SHA=f43a627503d26be4bc3f2f08dcdff7789c02bfdad15b295625dd2b82e1cc8678。205行/合计63345仍仅夹具预期，实际未验。失败即停后续，任务总1、XLSX/下载/派生/stop0，自建session已关闭、用户原页不动。

按本轮明确许可，仅本新映射唯一核验及官方failed row单次ro/query_only投影session/status/runtime四字段/error，00:26:22Z DBstat稳定；从最终源码提取9个invalid literal，脚本3.9AST与秘密/回答/推理哨兵通过。error只远端内存处理，安全结果HTTP400，但未可靠匹配source=fs_material_transport/version=material_guard_v1/code；runtime仍agent_returned/exception_class unknown/reason unknown。不传原error、不回答/推理/整JSON/日志/配置/凭据或/result、不再逐词查询。故不能判定是本地guard、上游或SDK哪条分支。mapping attempted1非网络抓包数，gateway该task0行/task tokens与rounds0不推供应商0；调用/usage/response_model/backendversion及人民币费用unknown/costnull，原policy不改，所有旧请求封存。

新稳定收据C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-MaterialGuard-Resume-20261102T002030Z/index.json，2254bytes/SHA ba3a9d0b7eb31727acbc24be384e657c5ffbed4b9926376f4c90994367b87faa，14文件bytes/SHA自核，完整软件metadata与新任务审计/映射/单次脱敏诊断均在。本轮无源码临修/额外付费/旧error读取，未做功能失败后的外观或阶段2/3；一次纯模块记录回B终审，不作部署source。结论仅8e2a软件发布读回通过，阶段1真实材料仍失败且producer未证，不能据未匹配新码硬归因或再付费猜参数。


## 已证SDK摘要丢字段机制：8e2a受控基线推进与实际消费者零模型验证（2026-11-02）

本轮仅阶段1诊断机制修正。A原clean baa分支正常merge B固定1edf640c9539e39db416957223a6cd89637bec8e及最新main8e2a，无冲突，原记录保留，不读B dirty目录。只推进现有material-guard/followup唯一transport基线，不另造模式：installed source=8e2a456631fc5aa916c1366d087b9adbccb02f91，backup=/var/backups/fs-navigation-20261006/nav-20261102T002030Z，manifest=e3a949b35d55aac5048f22094d81bc9f7db7e4f684f7463a83044371f5d4d3a4，journal=fc33024f58bb1222e288e6ab1374be16b543f93756f135833238b29be9e22c74；before transport=a71849b7e5e8f3c5b55967c21d5383e2ff6afa7c7c5e3c6772dc0c80209ba945，新B after=6b7a8c96b9eccbe9bd4a7dd7668ee12d346739267c16a29a7b06dc78f47e44e9。25/45/NEW0/8，原proof/Git完整25before、CAS/fresh/root/mode/active实际container/锁/准入/provider/UNKNOWN/backup/journal/rollback全保持。仅DEEP/fence/readiness重载range，strictTrue bindings及其余24不写hash/inode/mtime，worker/Nginx不动。原prepare无需新逻辑，消费release更新pin即生效；历史stage脚本不改。A实际只改runtime_release.py/test_runtime_materials.py/本附录三路径，均在登记四路径内。

测试先新8e2a精确before断言RED，再最小pin变更；原deploy显式三模块最终29项、B新transport17项各全过0failure/error/skip，旧c12a proof/before拒绝及原成功/失败回退/24metadata等继续覆盖。3个publisher Python3.9 AST/diff检查通过，B源码与fixed1edf无diff。原SDK摘要AST加明确依赖fixture的B五项本机复核通过；新增实际FS loopback五分支消费检查也通过（该入口因导入B TestCase附带17项，runner实际18项，日志明确，不冒18个新用例，不再扩跑）。没重跑Core228/native/knowledge或full AIAgent探针。

另仅一次原play187固定8251镜像隔离执行，networknone/read-only/tmpfs/no-host-mount/无pull build install、synthetic HOME/fake token，原socket/process/file/DB守卫不变。输入11703bytes/SHA22e957f8359b8ed0c298b9dc220c8574c07d5eb6b0985a96585af7f8e75b1eb7。先一次固定公开raw下载核pin71d34bad原api_error_summary.py为11931bytes/SHAb31ba3cc4081d8e2e68d599410e5e5cd01204a9bf46dfdedefd64d7e9177f3f9，与image实际regular文件精确相等；OpenAI2.24.0及_base_client SHA383b…5347同原固定版本。image真实导入/opt/hermes/agent/api_error_summary.py，未摘取或改写此实际模块；真实OpenAI客户端经MockTransport产生BadRequestError/PermissionDeniedError，再调用该模块实际ApiErrorSummaryMixin._summarize_api_error，最后固定新classifier（SHA44fced92013604e0e34897ab917c894082f40102928429e96a041d5ac1914eb7）。

实际FS本机loopback生成的两典型request_fields/tool_allowlist静态错误经过真实OpenAI异常→原SDK摘要后，均仍能精确识别source/version/code；未知私有异常、普通FC、匿名共3分支保持generic/无标识且PRIVATE_SENTINEL不泄漏。5项每项Mock POST1、retries0、provider/network0；进程可选平台探测1次被原OS前guard拒绝，实际子进程0。它证明新静态message标签穿过真实摘要消费链，不是正式run或模型成功。没有读取生产库/旧error/日志/Env/profile凭据或构造正式任务，SDK/config/权限未改；未恢复曾被拒的动态str拼接。

最小稳定审件C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-GuardSummary-A-Candidate-20261102T005020Z/，含29/17日志、明确分层的本机与真实SDK消费者证据、固定public-source/raw/hash/helper/harness、最终GitLF唯一transport pack合同。此包仅修已证摘要丢字段机制，不能补run_7219…的producer/材料真实400/187或费用原因，所有历史unknown和封存不变。A本轮无部署/新付费/浏览器/生产error重读，不推进阶段2/3；交Personal最新SHA独审/CI/合并后另沿已授权现场任务验收。


## PR741最终23a发布读回通过，新任务仍精确通用400（2026-11-02）

A原clean分支正常ff23a27325b00f27a5c5696657c7c4141a06135f18，tree45f480be…与reviewed一致；复用29/17/SDK5等有效输入，不重跑。01:04:01Z原collector自然空闲后，以最终GitLF新pack（descriptor47e436748b6d4d0d5b8761b0c4ccf667229492e278eaa37ed413947e8ab5a7a1；655360-byte tar16a76553eef6c886ec4f308a8459ea4663f55e88dd9a665d27b38b019a3e323e）和新stage=/var/tmp/fs-guard-summary-23a27325-20261102T010331Z/stage、release=nav-20261102T010331Z。fresh01:04:37.718023Z、manifest=ae010cb6b11a1a7c7c4ed877ae7534dbfc63b443143955cdd990ed96dfe19cf4，钉原8e2a成功proof，原inspect/CAS/所有围栏通过后唯一apply成功，backup=/var/backups/fs-navigation-20261006/nav-20261102T010331Z、journal=d59396365261e5669b8a1ec4fc9432beea103ca23ed8f664b81b0a6de1fd3431、applied-awaiting-actual-http-role-acceptance。25after/root/mode、45保护/root/mode及其它24inode/mtime匹配，唯一transport a718→6b7a，strictTrue bindings保留；range17437→11747，worker10045/Nginx31780及真实container7af81e7f…/image8251/Running/StartedAt14:06:29.450947631Z同前，3active/range200ok/匿名worker401。无第二apply/生产临修或权限配置改动。

正常原submit创建全新cid286a3c6a1eb242f2a84c099ce1b72fd3（201），CSV1506bytes/SHAdc04932d205971fc04306481f94063cddc991652286828d688c84e32cc9c40a7上传201、fid163e0a5c52d31c12597716568538ca5c匹配，唯一checkbox/read全集后01:07:02.679Z正常UI一次材料POST202 queued、discarded=false，01:07:04.222Z原IDfailed、coverage/files空。request=material_bce42e4ff1fa497ea3185aeac68468b2/task=e20b0b94e805f1c4a84e109339b5b6d4/lease=ab4acbcc282a7c58232a0bc4f804519a/run=run_484bf2f41f184fd68f5b85422db159f6/session=mg_a845f9d3afedb2598cb17462db16b2a150eb9d027a16b3f43601f81f50aa1544/bodysha=30e895dc14e29a32a1bdb02b27222ff0d586e4ee47721f9518481e04120ae28e。205行/63345仍仅夹具预期，实际未通过；失败后任务总1、XLSX/下载/派生/stop0，自建session已关闭。

本新任务一次授权ro/query_only投影官方同failed row的session/status/runtime四字段/error，映射及run/key/fullsha唯一匹配、DBstat稳定，未整JSON/output/messages/推理/配置/凭据/日志/result或旧run。实际INNER5578bytes/SHAa4495efa31bb92afd03f0f6ece627532218c1ff265a6313ff495b693a18fe36f，仅1个classify且AST精确等新helper44fced92013604e0e34897ab917c894082f40102928429e96a041d5ac1914eb7（active AST SHA88c9a4862150ee838786ae0d3e73c210b315f15ff9561847a8637c917ddaf459）；2正4反例/3.9AST通过，无旧def覆盖。结果fixed_producer_verified=false/source/version/code unknown/HTTP400，但generic400_template_exact=true，即整串精确“HTTP 400: invalid or unreconciled request”；runtime仍agent_returned/exception_class unknown/reason unknown。只返回固定模板bool/安全常量摘要，不返回原error。不能由此确定producer或具体guard，也不再重读/改分类器/新付费猜测。

gateway此task0行/tasktokens与rounds0，不推供应商0；供应商调用/usage/response_model/backend/CNY仍unknown/costnull，原policy保持。稳定目录C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-GuardSummary-Deploy-20261102T010331Z/index.json，2587bytes/SHAee0abc4178e53605523b811f65c78266b740899dad17f6fea7aeb23ef2bb85f0，16文件bytes/SHA自核，含软件完整metadata、新任务审计/绑定、实际reader/INNER校验与脱敏诊断。无外观/额外模型/阶段2/3；仅一次附录记录非部署source，交B核收。结论：23a软件发布读回通过，阶段1材料仍失败；可观测结果已明确为通用400模板，真实执行根因仍未证。
## 原生聊天统一候选：后端、隔离工作区与审核消费（2026-11-02，未部署）

本轮按用户纠正后的阶段1方向实现普通 turns：原 input、稳定 cid session 和官方历史直接进入原 Runs，不默认构造 FC book/五字段 spec/GoalState 或独立材料任务。原定价分支保持。附件原字节进入本 cid 工作区，生成文件经受控 fd 相对路径读取发布为不可变文件卡，保留 owner/hash/parent/version 与原鉴权下载；同 cid 自然追问、另一 cid 不自动继承。上传不再强制 CSV/XLSX 解析；显式表格工具仍执行原解析验证。

正常合并 B 的 native scope/预算/审核消费者（至 0cab5195）和 UI 固定 61214995，未修改这些 owner 的源。真实共享 TaskStore 注册的 `_native_active_model_tasks` 只读 native runs/turns 的精确绑定，不递归调用 FC helper；总在途集合沿 B helper 合并原 FC。UNKNOWN 继续原 ID 只读对账，不重 POST；stop 与迟到事件/产物写入由原 conversations DB 事务围栏串行。旧 `CONVERSATION.materials.recover` 保持原样；曾提出的删除被工具审核拒绝，未实施且不再重试，旧映射/回执不迁移、不删除。

owner profile 为 `/var/lib/fs-hermes-fc/native/profiles/<sha256(owner UTF8)>`，workspace 为 native/workspaces/cid。memory/context/background/soul 启用，memory/skills 原工具真实写 pending，host 回读 record canonical digest 登记来源；B 原 Codex 审核消费者与日报同包，pending 不等于批准。实际每日 heartbeat 加载、新候选独立 Codex 审核及 apply 后新会话可见仍待真实验收，不增 timer。控制面仍 9876:9876，仅它取得固定 Docker CLI/socket；官方 DockerEnvironment 的模型文件/terminal/code 面仅挂本 cid workspace。只在原 `_readonly_skill_mount_args` 执行时切换只读空 backend home，constructor/config 与 memory/skills 保持真实 owner home，ContextVar 正常/异常/取消均复位。

本机原 runner 四入口最终 138、原 deploy 三入口 33、B native+material 28、channel12 及原 Node 两入口通过，均零 failure/error/skip。一次测试命令误传模块根而非 tests 目录，4 个导入 error 的日志保留；纠正到原 tests 入口后 138 全过，不修改 runner 围栏。原知识 closeout 的 91/30 error 旧限制保留，不扩修或冒绿。实际 temp Store/TaskStore 测到原 tasks 不新增，丢 202 只查原 key、不第二次 POST，stop 后迟到回复/文件不覆盖；真实两 sheet XLSX 原字节、v2/v3 下载/内容/parent/说明页保持通过。本机结果不冒生产 UI 或模型成功。

固定 8251 镜像隔离 SDK：network none/read-only/tmpfs/无 host mount、synthetic HOME/输入/fake token；官方 SDK 文件 pin 逐项匹配。实际 DockerEnvironment constructor 与原命令生成、terminal/file/code 共用同一 backend、实际 AIAgent→完整 turn→OpenAI2.24.0 序列化→一次 MockTransport 主请求（37253 bytes，SHA58d474332a1e823776b2f8643db4876a7b4f09e9521acbb8fa0c0f2354d893fc）→原 Proxy/Grants/temp SQLite 均到达，provider stub1、真实 provider0。实际 owner SessionDB 回读 user/assistant，另一 owner DB 不同；memory/skills 真实 pending 回读与 host digest 登记通过。Docker daemon 子进程 I/O 为明确 fixture（隔离容器没有 daemon），实际子执行容器尚未启动；probe 用户为镜像非 root 用户，不能冒生产9876证明。原 fd/openat/Linux symlink/FIFO 防护实际执行。官方自动标题另产生带 response_format 的辅助 POST，在触网前被 guard 拒绝，已交 B 独占核对；结果明确 primary passed with blocked auxiliary HTTP，不称整个 SDK/全部后台能力通过。所有 guard 计数与早期夹具失败原收据保留，未改 SDK/stream/准备函数凑绿。

publisher 新增互斥 `--native-chat --followup`，钉已安装 23a 的 manifest ae010cb6…/journal d5939636…/backup nav-20261102T010331Z。33 targets/45 protection/NEW4，包含三旧 root 审核消费者、native_review、native runtime/scope/backend 契约及精确控制面 drop-in；其余原目标按 SHA/mode CAS，未变文件不写 inode/mtime。CLI 固定 root0755/39719840/SHA bfc304d1c5d8694b5c9bacc1c52c2f8d50e65b6f3e29446283a2561e23667be7；daemon socket 的真实 type/uid/gid/mode 在新 prepare 一次观测、manifest 绑定，必要补充组仅控制面，不改 Config.User。原锁/准入/provider/UNKNOWN/fresh/CAS/备份/journal/回退保留；必要 worker 重建及原 DEEP range readiness，Nginx 不 reload。回退先恢复原字节与旧 unit，再检查旧运行边界，不错误要求旧 unit 提供新 CLI。新 owner 数据目录留存，不删除原八模块或数据库。

当前生产仍已核 23a；本轮无发布、真实任务、付费调用、旧 run/error/result 或浏览器操作。新候选需统一最新 SHA 独审/CI 后再沿原 publisher 发布，随后正常入口验 CSV/XLSX、下载追问、刷新/stop/权限与桌面/手机；阶段1未完成，阶段2/3不启动，费用和历史原因 unknown 不补零。

### 同包补齐自动标题 provider 装配（2026-11-02，未部署）

正常 merge B 固定 198024fb0f687ed2f8720937920365476061cbd5；B 四路径未并改。A 仅补原 publisher 三文件和本附录：从已安装 23a 的原 45 保护证明中精确提升已有 `/opt/fs-hermes-fc/direct_provider.py`，Git 来源 core/source/direct_provider.py，before SHA91d301ebe3578d0e6c60c23252510ebb34416a57f9f5dfc4ffd744f5ae0c74fa 同时绑定原成功 journal/manifest 的唯一保护记录与原 Git bytes，不接受缺项、重复、错 hash/旧 source 或当前漂移；不视为新增。集合为 34 targets/44 protected/NEW4，CLI/unit/UID/隔离与原锁、回退均不变，失败恢复 provider 原已装字节。未改旧已生成 stage 或原冻结 writer。

先测旧装配实际 RED=33≠34，再补最小提升；原 deploy 三显式入口最终34项全过、零 failure/error/skip，涵盖完整 proof/Git、现场 provider 漂移拒绝、原 inspect/apply/两类回退与未改文件 metadata。逐 Git 原始字节核 B after：direct_provider.py 17275bytes/SHA4bb723c0d9673bfe1e795bbeaf704cb97df6668d41ffd287c6ed7f18306443b0（320 CRLF）、transport.py 20694/SHAa9e6fb994625ccff66aed81b06e02b14c32171fd98b4693216b2264b49ededb7、proxy_gateway.py 37607/SHAb137b639c8863fcc12f0f5ed87ef5572f6c9860831b389651d0e9a52dfb47e02；pack 保留 Git 原字节，未以工作区换行重写 provider。B 的42项消费者验证按其固定输入证据复用，不冒 A 重跑；原138/SDK/模型未重复。旧 SDK 收据的自动标题拦截仍是旧候选当时的真实结果，新代码尚未做实际 SDK 标题/供应商或生产验收；当前生产仍23a。
### 日报代码只读覆盖装配候选（2026-11-02，未部署）

仅改原 publisher：新版日报部署为 NEW 的 `/opt/fs-hermes-memory-approval/daily_review.py`，用 v2 unit recipe 的唯一只读 bind 保持容器 `/profile/scripts/hermes-memory-review/daily_review.py` 入口和相邻 inspect_runtime 导入；业务源码未变，真实06:10调度加载仍未验。host 原日报转精确保护项，原33c77…56c0d与23a Git bytes共同绑定，原profile9876:9876/0700及旧文件字节/归属/模式/inode/mtime不写；34 targets/45 protected/NEW5，原23a proof、CLI/socket/UID/child隔离/锁/CAS/UNKNOWN/回退不变，不对profile放宽原guard。先以原frozen guards实际重现旧路径RED，再验证新root路径与原容器入口契约；原deploy三入口39项零failure/error/skip，包括原guard父目录检查、旧保护漂移、旧recipe/可写/重复/错source/错target/额外挂载拒绝、根目标已存在拒绝以及成功/两类失败回退。系统UID/mode和Docker读回为明确本机fixture，原日报与inspect_runtime真实模块定义在合成文件布局导入，非真实容器/调度验收；本轮0SSH/生产/模型/浏览器。冻结writer未改，原unit回退恢复后仅移除hash吻合的NEW文件，旧profile/pending/DB保留。统一新SHA独审CI后再发布，不复用旧34/44/NEW4 pack。

### Native admission 共享读取修复候选（2026-11-02，未部署）

89e5 软件与真实隔离 backend 已核收，首个普通 CSV turn 仍为 UNKNOWN。A110 只读快照确认该 admission 为 root:9876/0600，实际 worker 为 9876:9876；native 写入的仅 owner 可读模式与原 root writer/非 root worker 共享目录合同不符。原 worker admission 读取会遭 POSIX DAC 拒绝，middleware 返回403，真实 urllib HTTPError 进入原 UNKNOWN/fence；这是本次可证的首个阻塞，不把官方精确 row0外推为从未提交或零费用。该403是固定原逻辑结合实测权限的本地重现，现场该次响应未留；不追认旧材料400、187或历史费用原因。

仅将 native write_admission 改为原 FC admission 一致的0640：允许既有 worker 组读取，不开放 other，不改 owner、组、目录、token、鉴权、SDK、预算或重试。新增回归使用真实临时 ConversationStore/TaskStore/Workspace、原 Grants、原 atomic 函数体、真实 Request/NoRedirect/序列化及 worker admission；唯一文件读边界明确模拟已测 Linux UID/GID/DAC，Windows不冒原生切UID。旧代码先实际 RED=HTTP403，新代码 GREEN；既有 fake atomic/Grants/202 fixture 保留用于原测试，不能再充当本共享文件接线证据。

额外本地固定公开SDK函数体合同走真实 worker middleware、原 Runs handler 与真实临时 RunIdempotencyStore：旧0600在worker读取拒绝、官方row0；新0640按相同合成原文/CSV元数据通过官方指纹和durable reserve、真实202→bindrun→ready=true。HTTP框架/空初始历史/外部秘密源/OS身份/WAL helper及最终executor为明确依赖fixture，网络与供应商调用0，不冒完整SDK进程或生产材料通过。当前生产仍89e5，原UNKNOWN及所有旧请求封存未改；本轮不发布、不改旧admission权限、不恢复或重POST。后续仅由同包publisher按已装89e5证明及NEW0登记必要增量，独审/CI后再发布与新意图验收，阶段2/3保持暂停。


### Native admission：已安装89e5上的单文件后续候选（2026-11-02）

`--native-admission --followup` / `native_admission` / `nativeAdmission`独立互斥，固定成功89e5 proof：backup `nav-20261102T100758Z`、manifest `642d78db24159c3c79f04ca3f67f4e8cda2abdbcd5680022ba6c9e9f71969084`、journal `34f8e7a3dea5df8f05baf73d9e9bc668a3127444f8915f323cc15dce5e361266`。34现存/45保护/NEW0，只允许`conversation_native.py`由`030e36d5…e795c2`变为`72253b5f…c1a57a`；其余33仅CAS/备份、跳过写入。原recipe v2从89e5 Git旧unit和固定socket GID994重现已安装unit SHA `5f31448a…9955e3`，不再次展开现场unit；backend、rootdaily只读挂载、旧profile/legacydaily及冻结writer保持。只沿原围栏DEEP/readiness重载range，worker/Nginx不重启，回退仅还原该代码目标。

新增本地tempFS用例覆盖完整原validate/inspect/apply/rollback（保留真实原guards）、range与readiness失败、33未写metadata、34/45精确集合、Git/proof/current unit/marker/NEW/零或额外delta/权限漂移拒绝。OS服务、锁、Docker与uid为明确夹具；不冒生产DAC或真实发布通过。原一行0600→0640修复和A111消费链证据复用，旧UNKNOWN不改权限/ready/重发。本次只是可审候选，尚未发布或恢复正常附件聊天；历史材料400、官方调用数和费用仍unknown。


### 指定合成UNKNOWN归档候选（2026-11-02，未生产执行）

用户指定唯一cid `1fbe5a2b7b0b4434af259bbde7c9293b` / turn `d2d00f2c13e749f186bf6e4303514a65` / request `web_c6a3cf2095854f898ed5b10c03b64a01`。新增仅宿主管理维护函数`ConversationStore.archive_synthetic_unknown(owner)`，无对象选择器、HTTP或模型工具；固定owner SHA/session/lease/官方指纹/原合成输入SHA及附件IDs，事务内验证singleton会话、UNKNOWN/run=null/stopped=1/schemas=null、任务绑定和原幂等派生后，只新增`synthetic_turn_archives`审计行。原turn、native binding/body/key/fingerprint、文件、事件和UNKNOWN/费用unknown均保留，不伪造终态；同次维护重放返回相同审计。普通列表及启动active排除，原会话owned入口拒绝新旧request和写入；native reconcile/complete/fence/授权及service recover/monitor早退，不复活或派发。

本候选只在temp执行归档，生产归档0、删除0。新表随Store原初始化装配，非公共迁移/回收站。执行真实维护前必须先安装所有archive-aware消费者并保留兼容回退代码，不能归档后回滚到忽略tombstone的旧Store。publisher仍原阻断COUNT，不以归档或新状态绕过；未来发布若排除该归档，须核完整审计/CAS而非排除任意UNKNOWN。

最新数据发布`nav-20261102T150526Z`（PR757/0ab6b023）已改变range/Nginx生成字节，故原89e5 34/45包不可复用。当前Git交接只有发布ID/8目标743保护陈述；缺该次完整approved-manifest和journal精确SHA/收据位置，以及活动range/Nginx patch生成链、34原目标与新保护交集before映射。待B协调完整证明后再登记唯一后续装配；不得反射磁盘或覆盖live-orders接口。原754的0640修复仍只在Git，尚无已安装证据。阶段1真实附件聊天/归档、供应商终态与费用均未据此宣称通过；新客调查和阶段2/3不在本包。


#### 指定合成残留：最小三文件增量（候选，未生产执行）

已一次只读核实`nav-20261102T150526Z`成功收据：source `943c9f9317af20a7281ac773d0a4573f729a8dd5`，manifest `68e907842a53f744e77a6eb30b7c4b4d207ce922ae6a827542835accd8e3079e`、journal `340c44f080cd8edb96df0b012e66fa67b634ce5a2f49367292ae7838bc9cdfc9`。其8目标/743保护与89e5成功34/45 proof合并，仅接受新8个批准目标覆盖旧值，实际并集779路径；本包只写Store/native/service三宿主源，其余776项只校验保护，NEW0。六个live源码与固定Git匹配，生成的range/Nginx只用成功收据SHA作CAS保护，不写入、不复制、不为其追查额外stage。

`--native-archive --followup`独立互斥，沿原writer/锁/准入/provider/UNKNOWN/quiescent/fresh/CAS/owner/mode/真实容器及原DEEP/readiness，仅重载range，worker/Nginx/timer保持。唯一UNKNOWN例外以候选Store的同一精确CAS函数作ro检查，绑定cid/turn/request/owner SHA/session/lease/input指纹/stopped1/run-null/schemas-null；其它阻断行或任何漂移仍拒绝。代码导入前核候选SHA，不读取token/配置/回答。原冻结writer不改。

安装/读回成功后，同一stage原publisher的`archive-synthetic --release-id … --approved-manifest-sha …`在原全部锁和admission围栏内复核成功journal、三源afterSHA和精确对象CAS，再调用既有最小归档函数；没有HTTP/model工具或任意对象selector。原turn/幂等/文件仍保留，普通聊天/待执行残留退出，回执只记归档1/删除0/未知不变。归档前安装或readiness失败可原回退；审计成功后回退旧盲代码被`archive_rollback_guard`拒绝，应作兼容前修，不能复活残留。

原tempFS原validate/inspect/apply/rollback正反用例含三delta、其它776inode/mtime保持、range/readiness失败恢复、锁内维护幂等、其它UNKNOWN/本对象生命周期/审计/候选源码漂移拒绝及归档后拒盲回退。OS/Docker/systemd边界是明确夹具，非真实生产验收。本轮仅候选，生产安装0/归档0/删除0，不调用模型，不核查费用；不扩成通用清理或账单系统。阶段1后续真实CSV/XLSX仍须在统一独审CI/最终merge后实际验证。


#### ARCHIVE 单一 usage 账本保护修正（候选，未发布）

0cc 最终包现场 prepare 被 `installed_protected_baseline_drift` 拒绝：三目标 before 全匹配，776 保护中仅 `/var/lib/fs-hermes-fc/profile/skills/.usage.json` 与历史 SHA 不同，其余775一致、unknown0；未生成stage/backup/journal，未apply、归档或模型调用。新合同仅在 ARCHIVE followup 对这一本运行账本采 fresh SHA，仍列入原 `unchangedRequired`，强制 regular/单链接/no-follow/root:root/0600；inspect/apply 继续原 SHA/owner/mode CAS，prepare 后变化拒绝。其余775静态历史 SHA、三delta、原writer/锁/回退不变，发布与回退不写账本。回归覆盖原失败、静态漂移、owner/mode/链接、prepare后变更、成功与range/readiness失败回退；Windows权限为明确夹具，Linux使用真实链接。本条不代表已安装、已清理或CSV通过。


#### ARCHIVE 既有控制面 readiness 接线（候选，未发布）

f43 新包 prepare/三目标+776保护 fresh CAS 已过，一次 inspect 在 `native_runtime_readiness` 查 `TARGETS['runtime/native-backend.json']` 时失败；ARCHIVE 的 TARGETS 仅3项，本机实际函数稳定复现 KeyError。就绪函数的 backend 配置及 rootdaily mount 源改从既有固定 `NATIVE_EXTRA_TARGETS` 读取，配置/用户/daemon/mount 验证均保留。新增 ARCHIVE 三目标下直接执行真实函数的正反回归，非整体 Mock readiness。usage fresh CAS 不改；另3项FC保护漂移待成功发布收据衔接，不反射磁盘或复用175044 stage。本条不代表新安装、归档或CSV通过。

补齐 FC 成功保护链：一次只读核实 `nav-20261102T175000Z` 原 manifest `900233dade3ab9a3922a8365345cffebbd8bdfd3cbe9a006081d5d1a6c91ab5a` / journal `5186d93010605186ec81d40e065758252d6cb8c93534edb27c753d11803afefc`，source `6d395242b88ca634c5745181e16f1fec6053c065`，精确3项 written 且无回退，当前 root:root/0644。两份 `sources.py` 的新 SHA 为 `449a53558c6607449abf1b070a11eff20aca58e689e0169331c28c24540ae635`，`server_quote_job.py` 为 `139bd6d239330bad4770148188d31f2fcbdd0e31bc1f668e4056f0489debbee9`；Git 原字节及原 build_stage 的 hermes-copy 复制链匹配。

仅 ARCHIVE 合并这3项已成功静态变更，必须先核固定 proof 原字节、scope/source/精确目标、旧 before 链、写入完成/无回退及 rootmode；不能接纳其它磁盘变化。仍为3 targets/776保护/NEW0，usage 单路径 fresh CAS 不改，FC消费保持原状。新增反例与原 tempFS 安装/失败回退/锁内维护合并检查：48方法全过0skip；原 guards 实际执行，三FC及其余保护字节/inode/mtime保持。权限及 Docker/systemd IO 为显式夹具，未据此宣称真实安装、清理或 CSV 通过；175044旧stage继续废止。

#### PR764 原生能力：已装归档版本的十文件 followup（候选）

`--native-capabilities --followup`沿同一 publisher/ARCHIVE保护及 usage fresh CAS，固定 f1ed / `nav-20261102T183302Z` manifest `88778d338bc0e35cf7cc91d62e245492c6a766f28bceceefe492506bd83b3437`、journal `d047b3d4b3b721de0bc7f12ec41f275ed2e81fc90f63f92a745fd367cdeb0f9f`。仅 Store/native/service/worker/native_chat/transport/direct_provider/proxy_gateway/fs_inprocess/会话HTTP十个现有目标，769保护、NEW0；unit/backend JSON/CLI/原live和FC文件不写，不重新创建目录或展开mount。HTTP after取本模块已审源码，before仍取f1ed原FC活动源码，逐项核成功凭据与Git，不能反射磁盘。全部十项必须确有delta，缺失/额外/零delta/旧proof/混marker拒绝。

原锁/准入/UNKNOWN/quiescent/owner/mode/fresh/镜像/备份恢复保持；仅同fence重启worker并原DEEP重载range，无daemon-reload/Nginx/timer动作。已归档对象沿原精确CAS保留，禁止本followup再次调用archive维护；失败只回退到已知archive-aware f1ed Store before SHA及同批其他九源，原writer仍逐项核备份CAS。tempFS直接测试成功、worker/range/readiness失败回退、769字节/inode/mtime和usage保持、归档后拒盲回退；OS/Docker边界为显式fixture。运行逻辑复用PR764已审及原147回归，不据候选/纯函数声称已部署、联网或CSV/XLSX成功。


#### 停止后的跨turn产物隔离（94b已安装并核收）

真实停止验收的原turn已cancelled且无回复/产物，但旧终端稍后写入共享workspace的文件被下一completed turn收集；停止不等于终端或计费立即结束。本补丁每turn独立执行目录，只由已发布immutable文件恢复同cid上下文；官方run_conversation(task_id=turn_id)、终端环境缓存和cleanup均绑定该turn，session_id继续承载原cid历史。旧执行可以继续写旧挂载，但不会跨轮发布；不删除工作目录或旧证据。真实temp Store/workspace跨turn RED后验证新产物/旧输入/历史版本及自然追问保留。

沿原--native-capabilities --followup推进唯一当前基线：20c/nav011909成功10源proof，精确叠加d135/nav021812成功单HTML proof；10现存/769保护/NEW0，仅conversation_native.py与hermes_worker.py两delta，其余8只CAS备份不写，HTML6254b7保护。原usage freshCAS、锁/准入/UNKNOWN/tombstone、父目录/owner/mode/备份/回退保持；同fence worker+range，无Nginx/unit/timer操作。真实已归档audit存在的成功/worker失败/range失败/readiness失败回退在原publisher直接回归；OS/daemon服务为明确夹具，不冒生产验收。memory/skill已由总控独审后实际应用并由干净SDK读取；新聊天session加载及06:10自然日审仍未验。

2026-11-03总控核收94b/nav033506软件及独立2-turn验收：terminal工具开始后一次stop→cancelled/空回复与产物；同cid下一completed轮generated空且无停止文件，真实skill_view已读已批内容，记忆标记在未提供值的提示后正确回答。仅此实际范围，不证明终端kill或计费立即结束；强制late场景复用原真实workspace/SDK合同。验收index：FS-Hermes-94b-Stop-Read-20261103T034607Z/index.json，SHA8355dd61428618a2e9f4ac512120492e1d665ddb4af3c7e31c15bb593ad12c56。

#### 可信用户数据与显式追踪宿主（本地候选）

继续原`--native-capabilities --followup`，唯一baseline为94b/nav033506成功manifest eec34e…c05f8及journal ae0327…b87e；原已验HTML包含在该成功保护链，不再回写旧HTML。16 targets／767保护／NEW4；9个必要delta（native/service/worker、B原样B2、user-runtime权限入口及4新helper），其余7只CAS/备份不写。既有user_query/user_store/live入口保持现役字节；不把当前Git候选当已装数据版本。新root模块使用官方registry的owner profile overlay，旧共享profile插件仍受保护，普通native无绑定时拒绝且不回落固定管理员。原worker+range同fence，原锁/准入/quiescent/usage freshCAS/tombstone/备份回退保持；不动unit、Nginx、timer或FC消费。

普通客户问题只走真实A2/B2投影；live邮箱仅host成员校验后通过原private-body validator与既有共享Admin准入，逐页复核且不回传邮箱。显式追踪沿原ConversationGoals/TaskStore outbox持久CAS，fact版本绑定scope/identity/policy/data和有效cutoff；仅fresh CAS胜者在当前轮完成后交原native submit，取消/不确定或重启丢失的fresh派发权只沿原ID对账，不新建调度/执行器或重放。当前仅本地组合通过；尚未生产安装/调用客户模型或证明自然追踪周期。

#### 客户调查范围衔接（bd9后续本地修复）

bd9/nav052236已真实安装，manifest4a6c58744029e3251d5ebf926a9161d977cf8bd2487596682bb45352e1b3c7ce、journal a548cdcab2e06c8568a7ff2231a6e979ab23d5babfb4990f12c5e5b4ef07a1a5；普通问题可读目录/聚合，正常回答报告候选403，未取得客户ID、未验通持续跟踪。该次403来源尚未独立确认，不能冒认IAM缺权或本地复现就是现场原因。

本地真实worker/host/Store/Service/QueryContext复现：公开工具允许默认/global聚合，但客户调查只接site/project快照。保留global/series聚合；目录、聚合回执和原工具声明给出实际授权的显式范围选择路径，客户工具对聚合快照返回unavailable及原因，不偷偷选站、不改快照或返回假零；真实private/撤权仍拒绝。只修host helper与原生工具声明，B两blob、SDK和现役数据源不变。

沿原`--native-capabilities --followup`钉上述bd9成功proof：16现存／767保护／NEW0，仅conversation_user_data.py、fs_native_readonly.py两delta；其余14运行文件不写，共781项元数据保持。四helper已安装，不再沿94b/NEW4基线。原usage freshCAS、审批内容/索引、HTML/live、tombstone/UNKNOWN、锁/准入与同fence worker+range及兼容回退保持；不新模式/writer，不动Nginx/unit/timer/FC。本轮只有本地候选与直接回归，未发布、未新增现场读取或模型请求。

2026-11-03补齐已核收的单Nginx成功保护链：同一native-capabilities模式先核原bd9/nav052236成功proof，再消费固定`/var/backups/fs-navigation-native-20261006/workspace-native-20261006-07c816ca3c25`的manifest `0df40939921c58fda8a089a5b37d6d49e1629f2dc46153690047dd217fbed171`、journal `fa2355f41815a06633e6755388848d4864a901514e505fcb1c8a2336d28e95aa`。核root600/单链接/no-follow/稳定、release/scope/成功status/activation/manifest绑定/无回退及immutable页面SHA46a9d8…26bb0，仅将原Nginx保护SHA75a9b5…34b3d推进fde65e…69da4；原schema无written/sourceCommit，不补造字段，不导入另一publisher其它保护条目。16源/767保护/NEW0和两runtime delta不变，其余766保护沿原链；prepare后Nginx再变仍CAS拒绝。真实tempFS安装及worker/range/readiness失败回退核Nginx和781项元数据不写；OS身份/服务为显式夹具，本轮无SSH、安装或模型，后续必须从最终merge Git重新fresh发布，055924失败stage禁复用。

后续history-ID修复沿同一模式钉已安装3c45/nav065027成功manifest `11fd2c4c2384913e7da9855028b50be05c3fc50836e658b5863fda3681c64eac`、journal `c946e8cac39b1f0fde71a05f9dea49d86f9c76173a5d9e2dd767c712fc4819bf`。16现存/767保护/NEW0，仅活动proxy delta，其余782不写。当前Nginx必须已为fde65/root600；旧native过渡proof的文件安全、SHA、release/scope/status/activation/manifest绑定、唯一before75a9→afterfde65/page及无回退校验全部保留，验证后原样返回metadata，不再次赋SHA。原Hermes16项intent/written、锁/准入/usage freshCAS/tombstone及回退保持，同fence worker+range，无Nginx/unit/timer/FC动作。4项publisher直接回归含成功/worker/range/readiness失败回退及782元数据保持，OS/服务为明确夹具；B38项消费者证据复用。此前两份方案被auto-review拒绝未应用，澄清后双验证方案正常通过。原failed run是否触发history-ID分支仍未证，线上新闭环未验。

#### 官方压缩后的工具历史接续（本地集成候选，未发布）

6927停发，生产仍3c45。仅native实例forward官方`_compress_context`和事件/请求构造：同attempt真实压缩事件、计数上升、正常返回且改写消息后，在下一原请求构造时经私有host relay确认规范化messages摘要；原7字段binding、ready/run、literalTrue授权及同gateway均复核。Core自己取成功付费槽上界，确认只允许退休该边界前的历史prefix校验；新prefix和工具id/name/JSON语义args/index及顺序继续锁定，不信模型summary或自报边界，不改SDK pin/DB。重复、错绑定/hash/计数、迟到/失败压缩和重建无确认均拒。真实官方facade返回→worker→原call_tool/Grants→host→同Core gateway继续工具的直接组合已过；压缩summary/engine/window/持久化及最终provider为明确fixture，非完整SDK进程或生产成功，也未追认原400触发原因。

沿同一native-capabilities followup、3c45/nav065027证明和完整旧native Nginx证明，再核五批UI `nav070000/070100/070200/070300/090000`及management `nav083725`固定manifest/journal成功链，仅推进home/conversation/FC HTML、hubnav、range与formal Nginx这六个保护SHA。每段before→after、root600/no-follow/单链接/完整stat稳定性/原schema intent-written及无回退均核，不导入其它清单；Nginx沿原writer的beforeMode保持0600，不采用management manifest0644。16现存/767保护/NEW0，实际四delta为native/worker/native_chat/proxy，其余779只CAS备份不写，usage freshCAS、审批、tombstone/UNKNOWN保持。直接publisher五方法全绿，含六链反例、prepare后CAS及真实tempFS安装/worker-range-readiness失败回退；身份/OS服务为明确fixture。同fence只重载worker+range，不动Nginx/unit/timer/FC。旧083821失败root保留禁复用，最终merge后另建fresh包/根/阶段才可发布。

#### 6dc后续四项已发生保护变更（本地候选，未发布）

6dc/nav103504仅prepare，因保护漂移停止，生产仍3c45。新增保护来源只在原native-capabilities followup生效：formal Nginx续接固定`nav084925/085857/090248/112000`成功manifest/journal，完整2907ad→7fe051→545304→bc6040→c45e6f，沿beforeMode保持0600；不采纳这些批次其它目标。shared data-storytelling仅消费root600原`17cf23dc…b451`已批准/已应用回执（原bytes SHA a7a43e…ae4a），复核canonical request、candidate/record/target/backup/result/package与SKILL.md116925→c6c828；不重apply或复制同包文件。curator telemetry仅接受149994B旧prefix97318add…5e32到150832B当前86e005…6011的精确两条追加，末条15b63d181884/patch/相同SKILL.md before-after；actor不授审批权，也不要求reader注释字段。特定运行祖先按已核0:9876/0750、9876/0700、9876/0755核目录/身份稳定性，root审批与proof根不放宽。唯一3a5f…空锁依据用户授权和d8133c成功回执，只把期望owner推进9876:9876，保持0644/单链接/空bytes，不chown/unlink/flock。

四文件均为保护项；receipt/ledger/lock原no-follow、单链接、完整九字段FD前后稳定及固定SHA均保留。仍16现存/767保护/NEW0、运行四delta与6dc原字节相同、779项不写；原usage freshCAS、fence、tombstone/UNKNOWN、审批索引及回退保持。真实tempFS旧输入RED后，直接覆盖固定来源/坏proof与canonical/applied/内容、ledger prefix/末条、锁owner/非空以及prepare后CAS拒绝；成功及worker/range/readiness失败回退均验证bytes/owner/mode/inode/mtime不写。OS身份/服务为显式fixture；本候选无现场、模型或技能写。103504旧root保留禁复用，最终merge后须新Git包/fresh stage，原已批技能不再灌入，native直导仍是独立未实现能力。

## 2026-11-03：36d7/nav120348正式安装与最小真实客户闭环核收

总控已独立核收最终源 `36d7d92540d9153e9b1cc764f900990ded17362d`、release `nav-20261103T120348Z`。备份 `/var/backups/fs-navigation-20261006/nav-20261103T120348Z`；manifest `bd9da6f0bf945d194af8d3538c5686676b57bab97b2fd400c6bbcde398c2f029`，journal `44dba92d35d29427f4f85f44af82f0d138691113d5975e14ea21d788d063e8b7`。原publisher prepare→inspect→apply各一次成功，16after正确；实际native/worker/native_chat/proxy四delta，其余779的SHA/uid/gid/mode/size/inode/mtime全等，readiness/health通过。审批memory/skill/index、HTML/live、原UNKNOWN保持，0新增技能/权限/mount变更，无Nginx/unit/timer/FC写入。

真实正常入口新cid `e8279d3cc7a2465a80739127d8e4d46a`：客户目录→聚合→候选→describe及live工具完成，明确追踪＋一次原机制自然followup通过；三个turn `5ad86485a30c4f018cb4978c5a945292`、`e735948a399442cd860e7d27a4e40851`、`77aaaf48b71b4f6f8da038344a37a141`均completed。唯一Goal `customer-7049a9e973bd3900b0dffddbb77b34050d4502d125f76a8231f92bec12ce9435` revision5/work completed，CAS expected_revision0..4；原request `followup_372af5c1d9eea7c2b393129225d4483df359e98134ab67caa19c2cf319b3541a`、outbox handoff/inputSHA及完成receipt匹配。实际2client POST202＋1自然followup，0business_actions；自建草稿/事件流/浏览器session已清理，原用户窗口保持，新增付费已止。

证据：`C:/Users/Administrator/AppData/Local/Temp/FS-Hermes-Native-Compaction-Deploy-20261103T120348Z/final/index.json`，5644B／35件，SHA256 `705cf70c579d98bebd4261c90a54a4d3a11883a5aca3faed029162d45813cc4f`。核收限当前DeepSeek下客户分析与显式持续追踪最小闭环：partial/最早观察不冒终生首购，不扩大为所有新客识别或运营均通过；未来自然周期、生产自然压缩、完整OpenAI生产路由、provider调用数/effort/费用unknown继续独立记录。历史403、failed400及当时未发布段保留原时点事实，不把旧failed4dae追认为本Bug或回填成功。本次补记仅文档，不重跑模型、生产或旧run。

## 2026-11-03：阶段3 coupon 单页与受控宿主接线候选（未部署）

新增 site266 coupon 单个真实上游页，使用原 `/admin/market.Coupon/index` 的 page/limit/search，默认100、上限200沿原reader；只投影对象ID/范围/状态/领取使用计数，明确single_page/partial与续页，不请求discount或下一页，原无参数benefits_read不变。原native工具经真实run binding、Grants、NativeChatScope及每次原IAM复核接 BackendServices→CouponEdit→OperationLedger；仅disabled、fetch/used0的brief差异，原ID/完整字段保留/UNKNOWN不重POST/业务成功审计与精确读回保持。**生产业务批准producer尚缺**：可信宿主组合需提供绑定原run、对象、原operation_id、before_hash、精确brief、授权引用与时限的 `campaign_approval(binding, operation_id)`；当前没有该配置，默认 `business_authorization_required`。模型body/admin权限/总控均不代替业务批准；本候选不表示阶段3真实业务写入已完成。

原native-capabilities followup推进到上述36d7/nav120348成功16文件基线。3c45原证明及旧native Nginx、六链/后四批、17cf技能、精确ledger追加/单锁授权仍在各自历史metadata上完整验证，再与36d7保护精确比对，不重复推进当前SHA。仅首次纳管bridge/adapters/services/backend-client四文件，固定before为36d7 Git原bytes（801863…99c9d／85d4c589…f5479／8fa6942a…20911／1153be85…0c76c，root0644/单链接/固定size）；来源元信息收据 `.agent_runtime/stage3-current-campaign/index.json` 645B／4项，SHA a14496025aa3bee954e3d194895b7d87c075f5a91202e12609fa831086938bf1。013850仅backend-client历史成功引用，不冒四文件整批安装回执。20existing/767protected/NEW0，仅user_data＋campaign四文件共5delta，其余782不写。原frozen writer、四锁/fence、usage freshCAS、审批/UNKNOWN及业务policy/operationledger不写；campaign缓存随原worker＋range一致重载，失败先还原代码再恢复服务，无Nginx/unit/timer/FC动作。

本地直接验证包含真实单页请求次数/路径参数、worker Request→Grants/Proxy→host→原IAM→真实BackendServices/临时OperationLedger（只替最终Admin边界）、缺批准/撤权/错绑定/对象/原ID与UNKNOWN，以及真实临时FS prepare→inspect→apply和campaign/worker/range/readiness失败回退；782项bytes/owner/mode/inode/mtime保持。Windows身份/服务为明确fixture，不冒Linux现场权限或真实业务验收。本轮0新增模型/业务写，最终merge后才沿原publisher串行安装，再用已授权只读单页选确切对象；尚无对象/精确业务批准，不执行优惠券mutation。
