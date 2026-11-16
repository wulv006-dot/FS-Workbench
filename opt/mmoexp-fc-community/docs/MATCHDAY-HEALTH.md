# FC27 daily fixture heartbeat

The FC Chat service treats a valid UnifyFootball daily fixtures card, including an explicit no-matches placeholder, as a healthy daily delivery. It stores the observed London date in the existing `matchday_focus.state_path` SQLite database before deleting an empty placeholder. Recovery scans the public Matchday channel after a restart, so a card already posted that day still counts.

To enable one private missing-card alert per London day, set `matchday_focus.ops_channel_id` to the Discord channel ID of `fc27-bot-ops` in `content.chat.config.json`. The official guild must be in `matchday_focus.guild_ids`, and the FC Chat bot needs only View Channel, Send Messages and Read Message History in that private channel. The official server uses `1568699207022285040`; the test server does not send this alert.

After 10:00 Europe/London, the existing FC Chat worker checks the heartbeat once a minute. If no card was seen, it sends one warning to the private operations channel. It never sends a public health message and never selects a match just to fill a day. The SQLite claim prevents repeats across restarts. If the Discord send result is unknown, the alert is marked `unknown` and not retried automatically, avoiding duplicate warnings; inspect the service log and channel when that occurs.

This checks that **at least one** daily card arrived, not that all seven configured competitions remain active. Premium status and the seven Unify subscriptions still need separate verification around trial expiry.

The same private operations channel receives one warning if an official-guild `Match to Squad` follow-up is still pending or has an unconfirmed send result 10 minutes after its due time. A successfully sent follow-up does not warn. The warning names the target discussion channel and asks staff to check it before any manual retry; the bot never blindly resends an uncertain public card. The alert claim is stored in `matchday_engagement.state_path` and survives restarts. The test guild does not send these warnings to official operations.
