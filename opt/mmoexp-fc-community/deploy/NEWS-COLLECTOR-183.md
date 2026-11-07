# Optional 183 news fetcher

Status: restricted worker installed on 183 and service-user transport verified; production news routing is controlled separately by the main release.

The existing `/opt/fs-fc-collector` is a competitive-price collector with a separate job/context protocol. Do not alter it for Discord news. The standalone worker only accepts `{"source":"mmoexp"}` or `{"source":"ea"}` on stdin and returns source plus bounded HTML. Parsing, season filtering, ordering, deduplication and Discord sending remain on 187. The worker has no bot token, Admin credentials, database access or publication capability.

## Restricted deployment contract

1. On 183 create a dedicated unprivileged `fc27-news-fetch` account. Install `news_collector_worker.py` root-owned at `/opt/fc27-news-fetch/worker.py`, mode 0644, directory root-owned 0755. The account must not be able to replace the worker or SSH authorization configuration. A shell executable is necessary for OpenSSH forced commands; prohibit all interactive usage using the key options below.
2. Generate a NEW ed25519 key on 187 solely for this worker; root-owned, group `mmoexp-fc-community`, mode 0640 under a root:bot 0750 directory. Never copy the root/FS administrative private key into the bot environment.
3. Keep 183 `authorized_keys` root-owned and install only this key with options:

   `restrict,from="172.18.108.187",command="/usr/bin/python3 -I -B /opt/fc27-news-fetch/worker.py" ssh-ed25519 PUBLIC_KEY`

   `restrict` disables PTY and forwarding. The fixed command ignores requested commands. Verify the source IP against actual 187 egress before installation. No public HTTP listener is needed. Disable password login for this dedicated account; keep other accounts unchanged.
4. Pin the independently verified 183 SSH host key in a root-owned bot-readable known_hosts file. Set `FC27_NEWS_SSH_KEY` and `FC27_NEWS_KNOWN_HOSTS` only after connection verification. Router uses `StrictHostKeyChecking=yes`, `IdentitiesOnly=yes`, 8-second connection and 40-second total SSH timeout.
5. Validate as the actual 187 service user, including forced-command enforcement, invalid source rejection, and a real fetch. Then activate collector `183` in a test configuration. Exercise `auto` with an injected local failure before production enablement.

Default `collector` is `187` for backward compatibility. `auto` retries 183 only after 187 fetch OR parser failure. Manual `183` does not silently reroute to 187. Neither mode changes the publication queue; raw HTML is parsed on 187 using the same parser as local collection.

Observability returned by `collect`: source, selected collector, fallback boolean, checked_at Unix timestamp and attempts with elapsed_ms and sanitized error codes. Failure raises `CollectionError` with attempts. Timeout, HTTP status, network and invalid_response are separately classified locally; SSH remote failure is currently `collector_error` (worker stderr only contains exception class). Do not log complete response bodies or credentials. A failed collection does not consume publication quota.

## Isolation evidence (2026-11-08)

Final transport is the same-VPC address `172.18.108.183`, with fixed `HostKeyAlias=47.85.170.62` and the preverified public-address host key. Public-address port 22 timed out from 187; internal SSH verified that the host key is identical. The only permitted source on the new account key is `172.18.108.187`.

Final credentials: `/etc/mmoexp-fc-news/collector_ed25519` on 187 is root-owned, group `mmoexp-fc-community`, mode 0640, under root:bot 0750 directory. `/etc/mmoexp-fc-news/known_hosts` is root-owned mode 0644. The private key never leaves 187. The 183 dedicated account password is locked. Worker and authorization file are root-owned. Real service-user testing returned both sources successfully; attempted `id` command was ignored and an arbitrary URL source was rejected.

The validation uncovered an existing incorrect `/dev/null` permission on 187 (uid 996, gid 0, mode 0644), which blocked nonroot SSH before connection. With explicit coordinator approval, verified `lstat` showed a non-symlink character device major 1/minor 3, then ownership/mode were restored to standard root:root 0666 without replacing the device. Original metadata was recorded at `/tmp/fc27-news-route-20261108/dev-null-before.json`.

Real auto fallback validation as `mmoexp-fc-community`: injected local `TimeoutError`, fetched once via 183, parsed using the release `news_feed.parse_source`; MMOEXP returned 22 rows in 1320ms, EA returned 13 rows in 458ms. Both reported `fallback=true`, `collector=183`, exactly one remote call. No database or Discord publication was used.

`/tmp/fc27-news-router-20261108/worker.py` executed on 183 as `nobody`, called through an administrator-owned test harness. MMOEXP returned 761802 wire bytes and EA returned 494496 wire bytes, both exit 0. Public HTML fixtures were retrieved to local `var/mmoexp-183-fixture.json` and `var/ea-183-fixture.json`. Initial probe changed no services or credentials. Following approval, the dedicated nonroot account and forced-command key were installed; no existing service, firewall, bot environment or news route was changed. Test scripts and public results remain in this isolated directory.

