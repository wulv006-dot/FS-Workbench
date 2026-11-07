# FC27 tag catalog repair — 2026-11-08

The deprecated `GoodsTag/tagSelect` endpoint rejects the service role even when tag-list access is present. Both maintained Player clients now use `GoodsTag/index`, with `quick_search=%`, bounded pagination and local `gid/cate_id` filtering. The old endpoint is removed from each client's GET allowlist. Other Admin methods and response contracts remain unchanged.

Pagination fails instead of returning partial data when totals change, IDs repeat, pages terminate early, rows exceed the reported total, or 40 pages do not finish the catalog. An empty complete catalog remains valid.

## SBC source delta

`sbc-admin-tags.patch` contains only the equivalent `list_tags` and GET allowlist changes for `/opt/fc27-sbc-tool/admin_client.py`; the full live client, credentials and runtime data are deliberately not packaged.

- Expected original SHA-256: `1ea3a4e859d26994caf78d7bf7e2b112ba252b90fe560fe619d956bb1805f948`
- Repaired SHA-256: `4fd818cd6a6ff465da9a5a245113e45b516b4c70b2ab0976e70293e01651ea02`

Apply only to that verified source, preserve ownership/mode, and retain a backup. For the running Player release, transplant only `list_tags` and the old GET allowlist entry; do not replace its whole file with a repository snapshot.

## Verification

```sh
python releases/fc-sbc/tag-index-20261108/test_tags.py
# Optional: verify the actual staged SBC and Player files too.
python releases/fc-sbc/tag-index-20261108/test_tags.py /path/to/sbc/admin_client.py /path/to/player/admin_client.py
```

Nine offline contract tests execute the actual methods without authentication/network access. The production publisher additionally performed real read-only calls for FC27 Player (`cid=9627`) and SBC (`cid=9625`) before and after the atomic replacement. No Admin product writes or Player service restart were required.

187 deployment backup: `/opt/mmoexp-fc-tags-stage-20261108/backup-1794079722`.
Post-deployment Player client SHA-256: `b09ec56f6b7dd4bdbe30f1deb07e80f2920f5179bf50424ea4ec067fa2aeb239`.
Rollback restores only the two backed-up client files, preserving runtime state; subsequent consumer processes must load the intended version when restarted by their owner.
