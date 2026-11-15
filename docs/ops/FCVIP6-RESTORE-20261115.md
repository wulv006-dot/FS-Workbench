# FCVIP6 restoration — 2026-11-15

Owner: this restoration task. Branch: `codex/fcvip6-restore-20261115`.
Base: `bb403de` (`origin/main` fetched before creating the worktree).

The user authorized restoring the two previously paused Discord distribution
paths and their necessary service restarts. The parent task confirmed Admin
coupon ID 6025 was enabled: MMOEXP, FC27, 6% discount (94% price), unlimited
usage count, 2026-10-27 through 2027-11-01. No coupon was created or altered by
this task. No order was placed and no code was sent to members for testing.

## Applied change

- Order panel: pause flag false; existing reaction DM and private recovery button
  restored. Copy identifies MMOEXP FC27 6%, validity, and checkout eligibility.
  Existing lookup, interaction database, marker and eligibility checks preserved.
- Chat: only `chat_bot.surprise.enabled` and `texts` changed in runtime config.
  `FCVIP6`, `!drop`, staff restrictions, daily limit 3 and cooldown 600 seconds
  retained. Removed inaccurate limited-quantity / first-come wording. Generic
  drop footer corrected in tracked `chat_service.py` as well as live code.
- Only `mmoexp-fc-community.service` and `mmoexp-fc-chat.service` restarted.
  Existing order and editorial release locks held during the baseline-checked
  operation. No changes to the concurrent fixture worktree or DSH worktree.

## Deployment and rollback

Applied at 2026-11-15 01:57:04 UTC (09:57:04 CST).
Backup directory:
`/opt/mmoexp-fc-community/var/releases/fcvip6-restore-20261115T015704Z`.
Contains the pre-change `order_panel.py`, `chat_service.py`, and
`content.chat.config.json`. Original pause-time backups were also preserved.

| File | Restored SHA256 |
| --- | --- |
| order_panel.py | 43aa09484ae70564761b97a588e2c5e5fc37da1a8cfa6c557b054d23849983a0 |
| chat_service.py | ea96ec3eefb725c483b071eea8871be7296ad7c9e12222e331a42d9d2207b8bf |
| content.chat.config.json | d1e6d2fffda7e7f0f4db653ec9bd61de9795481772722d0aca6a84695c695374 |

For rollback, first compare these hashes and inspect concurrent changes; restore
only the affected hunks / surprise fields if another task has changed a file.
If all three still match, restore the three corresponding backup files under
the same release locks, then restart the same two services. Preserve all state
databases, markers, queues and other config. Re-read the order card after reload.
Rollback does not change Admin coupon status.

## Evidence

- Offline `opt/mmoexp-fc-community/deploy/check_fcvip6_restore_20261115.py`: PASS with Python 3.9 and
  discord.py 2.7.1. Mocked callbacks verified enabled buttons, first reaction
  DM, no repeat DM, eligible recovery and ineligible response; surprise staff
  check and existing limits retained. No Discord connection made by this test.
- Production Python compile / baseline dry run passed before writes. After
  deployment, exact candidate bytes read back for all three files.
- Existing [live order card](https://discord.com/channels/1041923524601851914/1570789310813442080/1570795908205903873)
  read through Discord GET: both buttons enabled; accurate private code
  description, no paused notice. Existing marker unchanged.
- FC ready.json matches current PID and reports connected. Chat PID 22962 is
  active/running and logged a successful Gateway connection at 09:57:05 CST.
  Order bridge remains active. All non-surprise Chat config compared equal to
  the backup; within surprise only enabled/texts changed.
- No real reaction or live `!drop` was triggered, and no purchase/redemption
  test performed. Actual member DM delivery / checkout redemption are untested.
  Previously disabled obsolete order cards were not reactivated; the active
  marker card above is the restored entry.

## Source integration and next release

Main does not yet track the DSH order module. Its four uncommitted files in
`D:/FS/DSH-worktrees/fc-order-self-service-20261113` were read only and remain
untouched. This task intentionally does not import or commit them. The exact
three-file transformation is preserved in `opt/mmoexp-fc-community/deploy/restore_fcvip6_20261115.py`,
which refuses mismatched baselines and defaults to dry run. It is a one-time
recovery record, not a new general publisher. Production config/secrets are not
committed. The code footer correction is a normal tracked source diff.

Before the next order or Chat deployment, reconcile this restoration against
the then-current live files and retain the enabled rewards and accurate copy.
The DSH owner still needs to land their order module with these restored
semantics. This draft PR must not be merged without user authorization.
CodeGraph tools were unavailable in this session; direct source inspection used.

## Source closeout after user resumed the independent task

Read-only production verification repeated: all three restored hashes above,
the enabled card and surprise config remain unchanged; three services active.
No second deployment, restart or distribution test was performed.

Two self-contained regression tests (`tests/test_fcvip6_restore.py`) pass,
including rendering the actual Chat drop method with a mocked send. The existing
module `ci_check.py` ran 317 tests on Windows/Python 3.9: 315 passed, one failure
in `test_information_panels.test_panel_creation_is_recorded_and_reconnect_edits_existing`
and one error involving missing `WindowsPath.is_junction`. This is not a Linux
CI pass. Unrelated modules were not modified to make that run green.

Source and recovery records were committed locally. GitHub push and draft PR
creation were rejected by automatic approval review before execution. A
read-only check confirmed origin is private `wulv006-dot/FS-Workbench`, with
ADMIN access; one evidence-based push retry was also rejected because explicit
authorization to transmit this code to that destination was required. No
remote branch, PR, CI result or merge is claimed. Obtain that authorization
before retrying publication; do not bypass the rejection. DSH work remains
untouched and still needs its own source integration.
