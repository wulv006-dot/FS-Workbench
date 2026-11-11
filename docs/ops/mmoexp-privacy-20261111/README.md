# MMOEXP_BOT privacy upgrade · 2026-11-11

The deployed bot now provides private `/privacy` and `/privacy-delete` interactions, authenticated encryption for its JSON/JSONL data and operational copies, account-bound deletion with a second confirmation, and periodic retention cleanup. Existing impersonation rules, configured exemptions and Discord role/ban state are retained. The active welcome entry is `self-welcome.js`, including WorkBuddy's latest direct-message welcome behavior; do not replace it with the older public welcome entry.

## Published materials

- Policy: https://mmoexp-bot-privacy.workspace-584227.chatgpt.site/
- Evidence: https://mmoexp-bot-privacy.workspace-584227.chatgpt.site/evidence.html
- Privileged access requested: Guild Members only. Necessary active configuration can remain longer than 30 days, so the application's “all API data within 30 days” answer remains No.

## Storage and deletion

`secure-storage.js` is an explicit file adapter, not a global fs patch. It encrypts bot JSON/JSONL state with AES-256-GCM using fresh nonces and atomic fsynced replacements. A wrong key, corrupt ciphertext or unencrypted production data is rejected. Package metadata is excluded. Old operational copies in the bot directory are included in migration, account deletion and retention checks. Data deletion removes whole associated diagnostic rows, including their name snapshots, rather than masking only an identifier.

The root-owned 32-byte data key is outside the bot data directory at `/etc/mmoexp-guardbot/data.key`. Service configuration supplies only its path through `GUARD_PRIVACY_KEY_FILE` and sets `GUARD_PRIVACY_ENFORCE=1`, with `UMask=0077`. Data files and keys use mode 0600. Never commit, print, upload or place key bytes in evidence. Losing the key makes the encrypted records unrecoverable; it has not been exported from the host.

Users delete only their own data, using identity supplied by Discord. Confirmations are single-use, expire after ten minutes and cannot be replayed by another account. Configured user-ID exemptions are included. Discord roles, bans, audit logs and already-posted messages are not automatically changed. Failed or partially verified operations are reported as incomplete. The welcome module's in-memory deduplication state is also cleared for the account. Future activity can produce new necessary records.

Moderation and welcome records expire after 30 days, diagnostics after 7 days, and historical JSON snapshots after 30 days from their last modification. Cleanup runs at startup and hourly; maximum scheduling lag while running is one hour. Active configuration remains while necessary. Support requests concerning manual exports outside the bot directory require an administrator to handle those copies separately.

For administrator-assisted deletion when the self-service interface is unavailable, verify account ownership through support, stop this one bot, run `privacy-admin.js erase <verified-user-id>` with the two service environment variables, and restart it. Stopping the bot prevents stale in-memory configuration from being written back. Do not send the user ID, decrypted data or key to a public terminal transcript. Routine users should use the self-service route.

## Legacy system journal

The operator explicitly authorized shared journal migration. After the upgraded bot switched to generic journal labels, 43 fixed rotated files were exported using `journalctl --all --output=json`, preserving complete event fields/cursors. The 4,102,004 entries were partitioned into 297 bot-related entries and 4,101,707 other-service entries. The latter were compressed and AES-GCM encrypted into 358,372,509 bytes. Source file hashes, category hashes, entry counts and authenticated decryption were verified before removing only those unchanged rotated files. The current journal was not removed or stopped.

The other-service archive is at `/var/lib/mmoexp-privacy-archive/20261111/other-services.jsonl.gz.enc`, with a separate root-only key at `/etc/mmoexp-guardbot/journal-archive.key`. Bot entries are in encrypted `legacy-system-events.jsonl` and are subject to the bot's diagnostic deletion/retention rules. This is a structured full-record archive, not a copy of the original binary journal format. Original category hashes in the manifest describe the migration instant; later authorized bot retention/deletion intentionally changes the bot category.

The old host runs systemd 219. Rotation therefore uses the documented SIGUSR2 mechanism and verifies that `system.journal` was replaced; it does not restart journald. No global logging settings, firewall, pricing process or unrelated service configuration was changed. Archive verification and cleanup have fixture tests for source mutation, ciphertext tampering and out-of-root paths. Never rerun the one-time cleanup against a new file set without a fresh reviewed archive plan.

## Validation and deployment

- 19 privacy assertions passed: encryption, nonce freshness, tamper/wrong-key rejection, retention, deletion of the correct account and operational copies, cross-account/replay/expiry protection, and honest failure reporting.
- 6 journal protection assertions passed using fabricated journal records.
- 79 existing multibrand assertions and 27 existing self-check routing assertions passed.
- Legacy matching and self-check suites retained the identical 4 and 5 failures present in the unmodified baseline. They were not presented as green.
- 5 additional latest-DM-welcome integration checks passed with fabricated members and a stub send function: deduplication, encrypted delivery state, disk/memory deletion and no repeated or public fallback when DMs are blocked.
- Production connected, registered privacy commands, passed authenticated-data verification, retained the latest DM welcome, and returned live private privacy/confirmation responses. The real confirmation was cancelled. A read-only check of the operator's own account correctly recognized its allowlist exemption. No real ban or real-account deletion was used as a test.
- The initial migration checked that all nine active data payloads were byte-identical after decrypting their new envelopes. Later authorized retention/deletion and WorkBuddy welcome changes are expected to change runtime data.

Sources are recorded from the actual deployed files. The repository baseline predates several previously deployed welcome and brand changes, so this PR also brings those owning-source files into line with the active service. Git merge and Discord application approval are distinct from production deployment. Do not claim either occurred without its receipt.

## Recovery

The release backup is `/opt/mmoexp-guardbot/backups/privacy-20261111`. Keep the master key and encrypted current data in place. Run `/opt/mmoexp-privacy-release-20261111.cjs rollback` with the same key-path/enforcement environment to restore the prepared compatibility recovery code. This preserves encrypted files and subsequent deletions, does not restore old data copies, and temporarily falls back to support/administrator-assisted deletion instead of the self-service commands. The latest `self-welcome.js` entry and its module must remain in use. Recovery was prepared and syntax-checked, not executed against production.

Old Python/Node operator scripts that directly parse JSON will need the secure adapter or an explicitly controlled in-memory read. Do not decrypt configuration back onto persistent disk to make an old script work. Do not use old full-directory rollback scripts to restore pre-deletion data or unencrypted files.
