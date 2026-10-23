def fetch_all_needed(s, cfg, keys):
    """Read known product IDs by category first, preserving search/full-list fallback."""
    byid = {}
    kws = keywords_of(cfg)
    by_gid = {}
    for key in keys:
        gid = game_gid_of(cfg, key)
        by_gid.setdefault(gid, []).append((key, kws.get(key)))
    for gid, pairs in by_gid.items():
        need_ids = {str(i) for key, _ in pairs for i in (ids_of(cfg, key) or [])}
        if need_ids:
            try:
                got, _nocid, ncat = read_needed_by_cid(s, gid, need_ids)
                byid.update(got)
                if ncat:
                    log("  gid=%s 按已登记类目优先读取：%d 类，找齐 %d/%d 个ID"
                        % (gid, ncat, len(need_ids & set(byid)), len(need_ids)))
            except Exception as error:
                log("  gid=%s 类目读取失败，保留关键词与全量兜底：%r" % (gid, error))
        if need_ids and need_ids <= set(byid):
            continue
        used = set()
        if len(pairs) <= KEYWORD_SEARCH_MAX:
            for key, keyword in pairs:
                required = {str(i) for i in (ids_of(cfg, key) or [])}
                if required and required <= set(byid):
                    continue
                if not keyword or keyword in used:
                    continue
                used.add(keyword)
                search = _search_kw(keyword)
                try:
                    rows, pages = read_all_pages(s, gid, keyword=search, need_ids=required)
                    log("  搜索 gid=%s %s → %d 行（%d 页）" % (gid, search, len(rows), pages))
                    for row in rows:
                        byid.setdefault(row["id"], row)
                except Exception as error:
                    log("  gid=%s 关键词读取失败，保留全量兜底：%r" % (gid, error))
        else:
            log("  gid=%s 有 %d 个对标商品（> %d），保留全量兜底"
                % (gid, len(pairs), KEYWORD_SEARCH_MAX))
        # Missing mapped IDs must remain eligible after a failed/stale category read.
        missing = need_ids - set(byid)
        if not missing:
            continue
        try:
            rows, pages = read_all_pages(s, gid, need_ids=missing, max_pages=None)
            log("  gid=%s 全量列表兜底 → %d 页 / %d 行" % (gid, pages, len(rows)))
            for row in rows:
                byid.setdefault(row["id"], row)
        except Exception as error:
            log("  gid=%s 全量列表失败：%r" % (gid, error))
    return byid
