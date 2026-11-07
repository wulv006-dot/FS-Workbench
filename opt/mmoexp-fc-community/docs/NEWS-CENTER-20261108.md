# FC27 news center — 2026-11-08 candidate verification

## Delivery behavior

- Automatic polling defaults to 6 hours; FS presents hours and stores seconds. Collector mode is `187`, `183`, or `auto` (187 first, 183 fallback). Existing configuration remains 187 until explicitly changed.
- A durable SQLite collection round starts only when due. Both EA and MMOEXP are attempted before the round becomes publishable. EA articles rank first, then MMOEXP; each source sorts by publication time descending.
- Each round permits at most **6 automatic send attempts**, not 6 per publication-loop pass. An ambiguous Discord outcome consumes its slot and is never automatically replayed. This conservative rule guarantees no more than 6 automatic posts even when acknowledgement is lost.
- Remaining automatic pending items carry forward to the next round. Restarting the bot or retrying through the other collector does not replenish the round's allowance. Shortening the configured interval can make the next round due sooner.
- Manual X and website submissions each receive an independent UUID. Identical URLs can intentionally be posted again; manual posts do not consume the automatic allowance. The automatic toggle pauses automatic collection/delivery while explicit manual submissions continue to publish to the configured, validated channel.
- Automatic ingestion uses a persistent unique canonical URL. Before an automatic claim, the queue checks for an existing published/sending/uncertain record of the same URL, including manual publications, and marks the redundant automatic record `duplicate`.

## Sources and initial baseline

- EA: `https://www.ea.com/games/ea-sports-fc/fc-27/news`. Parse the rendered page's `__NEXT_DATA__` initial news records including its featured article. Require the `fc-27` game association and an FC27/Ultimate Team 27 title; exclude FC26 and Mobile entries. No browser login or anti-bot bypass is involved.
- MMOEXP: existing fixed FC27 listing. Article URLs remain on the explicitly allowed FC27 paths.
- The first successful collection for a newly introduced source queues only its newest article; older records become an internal baseline to prevent historical flooding. Later unseen current articles become pending. The baseline is an internal deduplication ledger, not a manual publishing restriction.
- Manual website publishing accepts a permitted article URL plus optional title/summary. It does not fetch arbitrary submitted URLs. Users can publish an older baseline article manually any number of times.

## Storage migration and isolation

- Non-destructive migration adds `delivery_mode`, `batch_id`, and `last_seen_at` columns to `news_items`, and a `news_batches` table with start time, state, and atomic claim counter. Existing X rows become manual. Existing URL keys, message IDs, audit actors and outcomes are preserved.
- `begin_cycle`, `finish_cycle`, and `claim` use SQLite `BEGIN IMMEDIATE` transactions. Claiming and increasing the round allowance are committed together. No sender sees a `collecting` round; `finish_cycle` commits ready state and collection metadata atomically after both source attempts finish.
- A process interruption during collection leaves that round unpublishable until the next due round. A process interruption during sending converts the claim to `uncertain` at startup and does not replay it.
- Remote collection uses a dedicated restricted SSH identity, not Admin/website/root credentials. Required bot environment paths: `FC27_NEWS_SSH_KEY` and `FC27_NEWS_KNOWN_HOSTS`. Parsing, SQLite state, sorting, quotas, and Discord publishing remain on 187.
- Collection status: `last_attempt_at`, `last_poll_at` (at least one successful source), `last_poll_error` (`partial_failure`/`all_sources_failed`/empty), and per-source `collector_status` JSON. Failures record bounded codes, not response bodies or secrets.

## Verification so far

- Local full suite: **172 tests passed**, including 25 news tests. Log: `var/news-validation-20261108/local-tests.log`.
- Covered: repeated publication-loop calls and restart retain the six-attempt cap; concurrent automatic claims share one cap; concurrent manual claims never claim one row twice; two source attempts complete before publication; repeated source ingestion stays unique; manual same-link submissions exceed six; manual works with automatic disabled; automatic skips a link already manually published; collector failure is recorded and restart does not create a fresh round.
- Actual 183 response fixtures parsed and validated: EA 13 FC27 records, newest UEFA Road to the Knockouts (Nov 6), no FC26 entry; MMOEXP 22 records, newest Openda SBC (Nov 7). Full EA public HTML saved only as validation evidence under `var/news-validation-20261108/ea-public-listing.html`.
- Linux isolated suite: **170 tests passed**, excluding the two Windows-only token helper tests. Stage: `/opt/mmoexp-fc-news-stage-20261108-core/mmoexp-fc-pilot`; log copied to `var/news-validation-20261108/linux-tests.log`. Initial stage setup lacked the worker script directory and incorrectly discovered a Windows-only helper; those stage-only setup issues were corrected before this passing run.
- Actual Discord test guild verification: channel `1568260661010497627`, guild `1565922092518613064`; one automatic EA RTTK preview (`1568678999213867034`) followed by two manual submissions of that same URL (`1568679000170307680`, `1568679001306832915`). All three sends were acknowledged and read back with the expected bot author and exact source URL. These were explicitly labeled TEST PREVIEW and used an isolated SQLite queue, not the production news database. Receipt: `var/news-validation-20261108/news-preview-receipts.json`.
- After explicit approval for isolated validation and deployment, the FS candidate was uploaded to the original stage destination and **16 Linux FS tests passed**. Log: `var/news-validation-20261108/fs-linux-tests.log`.

## Production release and acceptance

- Root released the five reviewed files (`news_feed.py`, `content_bot.py`, `collector_router.py`, FS `server.py`, and `static/fc27.html`) with backup `/opt/mmoexp-fc-community/backups/news-center-1794072783`. Existing panel markers remained unchanged. Deployment receipt: `var/news-validation-20261108/deployment.json`, including per-file SHA-256 values. Recorded bot PID at deployment was 5310.
- Live configuration is automatic collection enabled, **6 hours**, collector **auto** (187 first, 183 fallback), official news channel `1501757710381748254`.
- Read-only post-release verification confirmed `mmoexp-fc-community`, `bot-console`, and `mmoexp-fc-quotes` all active. First production round successfully fetched both sources through 187; no fallback was needed for that round. The dedicated 183 route and forced local-failure fallback had separately passed service-user validation.
- The new EA RTTK article was published as `1568679727592644660`. Existing MMOEXP Openda message `1568666851611770881` remained the sole publication of that article. Round 1 persisted `claimed=1`; the source baselines retained 12 EA and 21 MMOEXP records without historical flooding. Safe current-state receipt: `var/news-validation-20261108/production-verification.json`.
- Root's real FS browser acceptance verified the three news-center tabs, 6-hour setting, automatic routing, successful source statuses, and the manual publishing page. Screenshots: `docs/visual-qa-20261108/news-settings.jpg`, `news-manual.jpg`, and `news-preview.jpg`.
- Order self-service remains paused pending the user's developer interface confirmation. It was not changed in this release.
