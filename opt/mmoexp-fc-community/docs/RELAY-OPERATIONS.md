# EasySBC quote relay

Each configured channel waits for 300 seconds without another accepted EasySBC message before publishing its category quote card. Every accepted event resets the deadline, including across restarts. The existing 600-second cooldown and message claims remain in place. A pause exceeding 300 seconds is considered the end of a batch; EasySBC supplies no explicit batch-end signal.

`quote_relay.content_filter` defaults to false. This metadata-only mode works without Message Content Intent, but cannot distinguish ordinary subscription confirmation messages from content updates. Slash-command replies with interaction metadata are still rejected. Enable the content filter only after Discord approves and enables Message Content Intent; both the gateway intent and embed/attachment filter use this setting. Discord rejected enabling that intent on 2026-11-08 pending privileged-intent review, so production remains in metadata mode.

Run EasySBC administration commands in the private `fc-bot-ops` channel. Keep alert destinations pointed at their respective public FC channels. A third-party confirmation sent directly to its destination channel cannot be relocated by changing where the command was invoked; remove such one-time confirmations after configuration. Do not repeatedly re-subscribe during daily operations.

Player alert preferences remain ephemeral. Save/clear acknowledges by editing the same private panel, instead of adding a follow-up message. The persistent welcome entry remains public.

Validation: local relay/integration/alert/club suites passed (40 tests). The 187 stage passed the same suites before the additional metadata-mode regression was added (39 tests). The deployed alert Save button was exercised in Discord and updated the existing private panel without adding a reply. A new natural EasySBC burst after deployment has not yet been observed.
