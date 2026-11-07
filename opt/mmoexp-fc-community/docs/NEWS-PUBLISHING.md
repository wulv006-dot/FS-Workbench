# FC27 news publishing

The bot and FS console share `/opt/mmoexp-fc-community/news_feed.py` and the fixed database `/opt/mmoexp-fc-community/var/news.sqlite3`. The bot must initialize the database as its service user before FS accepts links. FS never changes file ownership or database mode, and reads queue content with SQLite `mode=ro`. No customer tables are queried.

`content.config.json` uses an independent section:

```json
"news_publish": {
  "guild_id": 1041923524601851914,
  "channel_id": "DISCORD_NEWS_CHANNEL_ID",
  "enabled": true,
  "poll_seconds": 900
}
```

The collector fetches only `https://www.mmoexp.com/News/game/fc-27.html`, rejects redirects, and limits responses to 2 MiB. It parses the existing list previews, dates, titles and cover URLs; it does not fetch or republish article bodies. Article URLs remain on `www.mmoexp.com/News/` and cover images remain on the known `assets.mmoexp.com/images/` CDN.

On the first successful collection, the newest article becomes pending and all others become baseline. Unique source URLs prevent repeat publication. Later collections ignore newly surfaced older articles below the previous date high water mark. Dates are source dates only; no publication time or timezone is invented for the article itself.

Bot integration: initialize `NewsStore(path)` and call `recover_sending()` once at process startup; collect with `fetch_listing()` off the event loop and call `store.ingest(rows)`. `await publish_pending(store, channel_id, sender)` sends at most three pending items; `sender(item, channel_id)` must validate the configured Discord guild/channel, use `AllowedMentions.none()`, and return the acknowledged message ID. `news_embed(item)` produces a source-linked card. X links can additionally be included as plain content so Discord may render its native preview.

The queue states are baseline, pending, sending, published, failed and uncertain. Every item is claimed transactionally before sending. Acknowledged messages retain their Discord message ID. All ambiguous send errors and process interruptions become uncertain; no failed or uncertain item is automatically retried. `DefinitelyNotSent` is reserved for errors where the adapter knows Discord accepted nothing. Operators should verify Discord before manually resolving uncertainty; there is intentionally no blind retry endpoint.

FS endpoints: logged-in `GET /api/fc/news/config` and `GET /api/fc/news/items`; administrator and CSRF-protected `POST /api/fc/news/config` and `POST /api/fc/news/x`. Config writes require a current SHA-256 revision, create a protected backup and replace the config atomically. X submissions require the current revision and an enabled news route. Only HTTPS public `x.com` / `twitter.com` account/status/numeric-ID URLs are accepted; tracking query parameters are removed, and the globally unique numeric status ID deduplicates account aliases and hostname variations. Optional administrator summary is limited to 600 characters. The backend does not request X pages or private APIs.

Local evidence: `var/news-source-validation.json` records a successful HTTP 200 read and 22 unique FC27 list articles, with the latest dated November 7, 2026. Verification commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_news_feed.py -v
```

The FS candidate also includes administrator, CSRF, revision, backup, queue privacy, and duplicate-submission coverage in `test_fc_console.py`.
