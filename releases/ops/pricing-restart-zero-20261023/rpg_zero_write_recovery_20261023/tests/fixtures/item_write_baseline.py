def cmd_write(a):
    cfg = load_cfg(a.config)
    plan = json.load(io.open(a.plan, encoding="utf-8"))
    items = plan.get("items") if isinstance(plan, dict) else plan
    if not isinstance(items, list):
        raise SystemExit("计划格式不对：应为 {\"items\":[...]} 或 [...]")

    jobs = []
    for it in items:
        key = it.get("key")
        tgt = it.get("new", it.get("unit_price", it.get("target")))
        if key is None or tgt is None:
            continue
        ids = ids_of(cfg, key)
        if not ids:
            log("跳过 %s：没有后台商品ID" % key)
            continue
        jobs.append({"key": key, "ids": ids, "unit_price": float(tgt),
                     "old": it.get("old"), "gid": it.get("gid")})
    if not jobs:
        log("计划里没有可执行的改价项")
        return 0

    log("待改 %d 件（%d 行）" % (len(jobs), sum(len(j["ids"]) for j in jobs)))
    for j in jobs:
        log("  %-24s 后台ID %s  $%.5f → $%.5f" %
            (j["key"], ",".join(j["ids"]), j.get("old") or 0, j["unit_price"]))
    if not a.confirm:
        log("★ 预演结束（没加 --confirm，未发任何写请求）")
        return 0

    s = Session(a.profile, a.show)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑：python p2pah_local.py login")
        byid = fetch_all_needed(s, cfg, [j["key"] for j in jobs])
        ok = fail = 0
        for j in jobs:
            changed = [i for i in j["ids"]
                       if not byid.get(i) or (byid[i]["unit_price"] or 0) != round(j["unit_price"], 5)]
            if not changed:
                log("  = %s 已经是目标价，跳过" % j["key"])
                continue
            # gid 按游戏取（暗黑4=456 / POE2=552）。工单里带了 gid 就用工单的。
            body = [{"id": int(i), "gid": str(j.get("gid") or game_gid_of(cfg, j["key"])),
                     "min_qty": 0,
                     "unit_price": "%.5f" % j["unit_price"], "cprice": None} for i in changed]
            r = s.write_rows(body)
            if r["ok"]:
                ok += 1
                log("  ✓ %s → $%.5f（%s）" % (j["key"], j["unit_price"], r["msg"]))
            else:
                fail += 1
                log("  ✗ %s 失败：%s" % (j["key"], r["msg"]))
            time.sleep(1.5)

        log("写请求完成：成功 %d / 失败 %d。开始复核…" % (ok, fail))
        after = fetch_all_needed(s, cfg, [j["key"] for j in jobs])
        bad = []
        for j in jobs:
            for i in j["ids"]:
                got = (after.get(i) or {}).get("unit_price")
                if got is None or abs(got - round(j["unit_price"], 5)) > 1e-9:
                    bad.append((j["key"], i, got, j["unit_price"]))
        if bad:
            log("⚠ 复核不一致 %d 处：" % len(bad))
            for k, i, got, want in bad:
                log("   %s id=%s 实际 %s / 目标 %s" % (k, i, got, want))
        else:
            log("✅ 复核通过：所有目标行都已是目标价")

        # 改完顺手清缓存，让前端立即刷新（等同人工在后台点一次「清除全部」）
        # 清缓存只能由本机执行：要不要清由工单里的 clearcache 带过来，命令行可覆盖。
        cache_ok = None
        want_cache, cache_src = cache_wanted(a, plan)
        if ok and not bad and want_cache:
            # ① 主后台 admin.p2pah.cn「工具箱 → 缓存管理 → 一键清理所有」—— 前端刷新的关键一步
            log("① 主后台 admin.p2pah.cn「缓存管理 → 一键清理所有」…［意图来源：%s］" % cache_src)
            # 🔴 2026-09-27：清缓存**绝不允许影响已经完成的写价**。以前它一抛异常，
            #   整段（含 ② order 清缓存、结果落盘）全被跳过、工单误记 failed。
            try:
                mok, mtxt = clear_main_cache()
            except Exception as e:
                mok, mtxt = False, "清缓存异常（写价已成功，不受影响）：%r" % e
            log(("  ✓ %s" if mok else "  ⚠ %s") % mtxt)
            # ② order 后台自带的「清除全部」（保留，无害）
            log("② order 后台「清除全部」…")
            try:
                cok2, txt2 = s.clear_cache()
            except Exception as e:
                cok2, txt2 = False, repr(e)
            log(("  ✓ %s" if cok2 else "  ⚠ %s") % (txt2 or ""))
            cache_ok = bool(mok)
        elif ok and not bad:
            log("（本次跳过清缓存 —— %s）" % cache_src)

        out = os.path.join(HERE, "p2pah_write_result_%s.json"
                           % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        io.open(out, "w", encoding="utf-8").write(json.dumps(
            {"operation_id": os.environ.get("FS_RPG_JOB_ID"), "ts": dt.datetime.now().isoformat(timespec="seconds"), "ok": ok, "fail": fail,
             "mismatch": bad, "clearcache_ok": cache_ok,
             "clearcache_wanted": want_cache, "clearcache_意图来源": cache_src,
             "jobs": jobs},
            ensure_ascii=False, indent=1))
        log("结果已存：%s" % out)
        return 0 if not fail and not bad else 1
    finally:
        s.close()
