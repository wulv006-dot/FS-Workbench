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
