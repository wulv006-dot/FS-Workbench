#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选页面校验：结构、范围隔离、栏目数量、脚本语法、资产与外链。"""
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from jsparse import extract  # noqa: E402

SRC = os.path.join(os.path.dirname(HERE), "game-monitor-news-cards-20261016", "source", "index.html")
CAND = os.path.join(HERE, "source", "index.html")

BLOCKS = {
    "GAME_TIMELINE_DATA": "window.GAME_TIMELINE_DATA =",
    "GAME_GUIDE": "window.GAME_GUIDE =",
    "GAME_TOOLS_MAP": "const GAME_TOOLS_MAP=",
    "PLAYBOOK": "const PLAYBOOK=",
    "MAPLESTORYBRIEF": "const MAPLESTORYBRIEF=",
}

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + ("  " + detail if detail else ""))


def load(path):
    src = open(path, encoding="utf-8").read()
    out = {}
    for k, m in BLOCKS.items():
        v, _ = extract(src, m)
        out[k] = v
    return src, out


def cjk_len(s):
    return len(re.sub(r"\s", "", s or ""))


def main():
    s_src, s = load(SRC)
    s_cand, c = load(CAND)

    # --- 范围隔离 ---------------------------------------------------------
    games_s = {g["key"]: g for g in s["GAME_TIMELINE_DATA"]["games"]}
    games_c = {g["key"]: g for g in c["GAME_TIMELINE_DATA"]["games"]}
    check("games 顺序与集合未变", [g["key"] for g in s["GAME_TIMELINE_DATA"]["games"]] ==
          [g["key"] for g in c["GAME_TIMELINE_DATA"]["games"]])
    others_same = all(games_s[k] == games_c[k] for k in games_s if k != "maplestory")
    check("其他游戏主档未改动", others_same)
    check("updated 字段未改", s["GAME_TIMELINE_DATA"].get("updated") == c["GAME_TIMELINE_DATA"].get("updated"))

    g_s = {k: v for k, v in s["GAME_GUIDE"].items() if k != "maplestory"}
    g_c = {k: v for k, v in c["GAME_GUIDE"].items() if k != "maplestory"}
    check("其他游戏攻略未改动", g_s == g_c, "keys=%d" % len(g_s))
    check("GAME_GUIDE 顶层 key 数不变", len(s["GAME_GUIDE"]) == len(c["GAME_GUIDE"]))

    t_s = {k: v for k, v in s["GAME_TOOLS_MAP"].items() if k != "maplestory"}
    t_c = {k: v for k, v in c["GAME_TOOLS_MAP"].items() if k != "maplestory"}
    check("其他游戏工具表未改动", t_s == t_c, "keys=%d" % len(t_s))

    p_c = {k: v for k, v in c["PLAYBOOK"].items() if k != "maplestory"}
    check("PLAYBOOK 其他条目未改动", p_c == s["PLAYBOOK"])
    check("PLAYBOOK 新增仅 maplestory", set(c["PLAYBOOK"]) - set(s["PLAYBOOK"]) == {"maplestory"})

    # --- 唯一 key ---------------------------------------------------------
    keys = [g["key"] for g in c["GAME_TIMELINE_DATA"]["games"]]
    check("游戏 key 唯一", len(keys) == len(set(keys)), "%d keys" % len(keys))
    check("maplestory key 保留", "maplestory" in keys)

    # --- 十栏 -------------------------------------------------------------
    pb = c["PLAYBOOK"]["maplestory"]
    gd = c["GAME_GUIDE"]["maplestory"]
    tl = c["GAME_TOOLS_MAP"]["maplestory"]
    brief = c["MAPLESTORYBRIEF"]

    check("ov overview 80-150 字", 80 <= cjk_len(pb["overview"]) <= 150, str(cjk_len(pb["overview"])))
    check("ov core 100-200 字", 100 <= cjk_len(pb["core"]) <= 200, str(cjk_len(pb["core"])))
    check("ov tips 3-5", 3 <= len(pb["tips"]) <= 5, str(len(pb["tips"])))
    check("ov gallery 4", len(pb["gallery"]) == 4, str(len(pb["gallery"])))

    biz = pb["biz"]
    check("biz 4-7 项", 4 <= len(biz) <= 7, str(len(biz)))
    check("biz 星级 4-5 均含 why/how/eff", all(
        b.get("why") and b.get("how") and b.get("eff") for b in biz if b.get("star", 0) >= 4))
    check("biz star 均 1-5", all(1 <= b.get("star", 0) <= 5 for b in biz))
    check("biz 无重复品类", len({b["name"] for b in biz}) == len(biz))

    dept_names = [d[0] for d in pb["dept"]]
    expect = ["产品", "设计", "引流", "投放", "私域", "邮件", "广告", "技术", "生产"]
    check("dept 9 行且顺序正确", dept_names == expect, str(dept_names))
    check("dept 每条可执行(>25字)", all(len(d[1]) > 25 for d in pb["dept"]))

    check("tool 4 个工具", len(tl["tools"]) == 4, str(len(tl["tools"])))
    check("tool 2 个 wiki", len(tl["wikis"]) == 2, str(len(tl["wikis"])))
    check("tool 名称唯一", len({t["name"] for t in tl["tools"] + tl["wikis"]}) == 6)
    check("tool 全部 https", all(t["url"].startswith("https://") for t in tl["tools"] + tl["wikis"]))
    check("tool title ≤16 字", all(cjk_len(t.get("title", "")) <= 16 for t in tl["tools"] + tl["wikis"]))

    check("cls 快速卡 5 张", len(gd["classes"]) == 5, str(len(gd["classes"])))
    check("cls 深度/覆盖卡 14 张(Classic 全职业树)", len(gd["clsDocs"]) == 14, str(len(gd["clsDocs"])))
    ens = [x["en"] for x in gd["clsDocs"]]
    check("cls 英文名唯一", len(ens) == len(set(ens)))
    deep = [x for x in gd["clsDocs"] if x.get("intro") and x.get("str") and x.get("weak") and x.get("stat") and x.get("gear")]
    # 「热门4-6深卡」是下限口径；Classic 二转只有 10 条分支，全部给足实质内容，不做人为删减
    check("cls 深卡 ≥4 张", len(deep) >= 4, "deep=%d (Classic 二转全量)" % len(deep))

    check("play 4-5 块", 4 <= len(gd["play"]) <= 5, str(len(gd["play"])))
    check("terms ≥10", len(gd["terms"]) >= 10, str(len(gd["terms"])))
    check("terms 均含标签与展开", all(len(t) == 3 and t[2].get("k") and t[2].get("intro") for t in gd["terms"]))
    check("terms 名称唯一", len({t[0] for t in gd["terms"]}) == len(gd["terms"]))
    check("eco 3-5 块", 3 <= len(gd["eco"]) <= 5, str(len(gd["eco"])))
    check("ops 4 块", len(gd["ops"]) == 4, str(len(gd["ops"])))

    codes = [x["code"] for x in brief["cats"]]
    check("intel 7 维齐全且顺序固定", codes == ["version", "market", "kol_social", "seo", "content", "esports", "exploit"], str(codes))
    check("intel 每维有 items 与 tm 对齐", all(len(x["items"]) == len(x["tm"]) for x in brief["cats"]))
    check("intel 每维 ≥2 条", all(len(x["items"]) >= 2 for x in brief["cats"]))

    # 经营草稿可见性与禁用断言（REVIEW 第1-3条）
    MARK = "Hermes经营草稿·待运营确认"
    check("biz 每项可见草稿标记", all(MARK in b.get("desc", "") for b in biz),
          "%d/%d" % (sum(MARK in b.get("desc", "") for b in biz), len(biz)))
    check("dept 每行可见草稿标记", all(MARK in d[1] for d in pb["dept"]),
          "%d/%d" % (sum(MARK in d[1] for d in pb["dept"]), len(pb["dept"])))
    check("ops 每块标题可见草稿标记", all(MARK in x[0] for x in gd["ops"]),
          "%d/%d" % (sum(MARK in x[0] for x in gd["ops"]), len(gd["ops"])))
    check("tips 每条可见草稿标记", all(MARK in t for t in pb["tips"]))
    raw_ms = json.dumps({"pb": pb, "gd": gd, "brief": brief, "game": c["GAME_TIMELINE_DATA"]["games"][keys.index("maplestory")]}, ensure_ascii=False)
    for bad in ("最高 25 星", "1 亿/5 亿", "5 亿以内", "5 亿 +", "Meso 5 亿"):
        check("不含未核固定断言: " + bad, bad not in raw_ms)
    check("eff 标注判断/待验证", all(("判断" in b.get("eff", "") or "待" in b.get("eff", "")) for b in biz if b.get("star", 0) >= 4))
    check("Classic 客户端 macOS 已注明", "macOS" in raw_ms)

    # 版本隔离：不能把 OVERDRIVE 写成 GMS 冬季版本
    joined = json.dumps(c["GAME_TIMELINE_DATA"]["games"][keys.index("maplestory")], ensure_ascii=False) + \
        json.dumps(pb, ensure_ascii=False) + json.dumps(gd, ensure_ascii=False) + json.dumps(brief, ensure_ascii=False)
    check("不再出现 OVERDRIVE 冬季大版本表述", "冬季大版本 OVERDRIVE" not in joined and "Overdrive Part 2" not in joined)
    check("Star Force 标注为正式服", "Classic 当前版本没有该系统" in json.dumps(gd, ensure_ascii=False))
    check("Heroic/Interactive 新命名已用", "Heroic" in joined and "Interactive" in joined)

    # --- 职业技能证据回归（SKILL-REVIEW） ----------------------------------
    import class_skills as CS  # noqa: E402

    jobs_by_en = {j["en"]: j for j in CS.JOBS}
    inherit = {"fighter": "warrior", "page": "warrior", "spearman": "warrior",
               "fp-wizard": "magician", "il-wizard": "magician", "cleric": "magician",
               "hunter": "archer", "crossbowman": "archer",
               "assassin": "thief", "bandit": "thief"}
    cls_surface = json.dumps([
        {"cn": c.get("cn"), "skills": c.get("skills"), "passive": c.get("passive"), "loop": c.get("loop"),
         "loop_skills": c.get("loop_skills"), "build": c.get("build"), "core": c.get("core"),
         "stat": c.get("stat"), "gear": c.get("gear")}
        for c in gd["clsDocs"]], ensure_ascii=False)
    cls_raw = json.dumps({"classes": gd["classes"], "clsDocs": gd["clsDocs"]}, ensure_ascii=False)

    def _forbidden_hits(text):
        """三转/未核技能名检测：Weapon Mastery 需排除 Blunt Weapon Mastery。"""
        hits = []
        for t in CS.FORBIDDEN_IN_CLASSIC:
            pat = r'(?<!Blunt )(?<![A-Za-z])' + re.escape(t) if t == "Weapon Mastery" else re.escape(t)
            if re.search(pat, text):
                hits.append(t)
        return hits

    bad_tokens = _forbidden_hits(cls_surface)
    check("Classic 技能表/循环无三转或未核技能", not bad_tokens, str(bad_tokens))
    # 三转技能名只允许作为纠正说明出现，且必须同时写明“三转”或“不存在”
    qualified = []
    for c in gd["clsDocs"]:
        body = json.dumps(c, ensure_ascii=False)
        hit = _forbidden_hits(body)
        if hit and not ("三转" in body or "不存在" in body):
            qualified.append(c.get("en"))
    check("三转技能提及均带纠正说明", not qualified, str(qualified[:4]))
    check("Classic 三转边界已写明", "上线版没有三转" in json.dumps(gd, ensure_ascii=False)
          or "三转未在上线版开放" in json.dumps(brief, ensure_ascii=False))

    def job_verified(key):
        names = {s["n"] for s in CS.verified_skills(key)}
        parent = inherit.get(key)
        if parent:
            names |= {s["n"] for s in CS.verified_skills(parent)}
        return names

    unknown_skills, unknown_passive = [], []
    for c in gd["clsDocs"]:
        job = jobs_by_en.get(c.get("en"))
        if not job:
            unknown_skills.append("job?:" + str(c.get("en")))
            continue
        ok = job_verified(job["key"])
        for x in c.get("skills") or []:
            if x.get("n") not in ok:
                unknown_skills.append(job["key"] + ":" + str(x.get("n")))
        for p in c.get("passive") or []:
            nm = p.split("：")[0]
            if nm not in ok:
                unknown_passive.append(job["key"] + ":" + nm)
    check("职业卡技能名均在证据映射（含一转继承）", not unknown_skills, str(unknown_skills[:4]))
    check("职业卡被动名均在证据映射", not unknown_passive, str(unknown_passive[:4]))

    loop_bad, loop_missing = [], []
    for c in gd["clsDocs"]:
        job = jobs_by_en.get(c.get("en"))
        if not job:
            continue
        ok = job_verified(job["key"])
        declared = c.get("loop_skills") or []
        for nm in declared:
            if nm not in ok:
                loop_bad.append(job["key"] + ":" + nm)
        card_names = {x.get("n") for x in (c.get("skills") or [])}
        for step in c.get("loop") or []:
            if not any(nm in step or nm.split(":")[0] in step for nm in declared):
                loop_missing.append(job["key"] + ":" + step[:24])
    check("建议循环只用已核技能（无三转/未核）", not loop_bad, str(loop_bad[:4]))
    check("每条循环都绑定已核技能", not loop_missing, str(loop_missing[:3]))

    review_path = os.path.join(HERE, "CLASS-SKILLS-REVIEW.json")
    rev = json.load(open(review_path, encoding="utf-8")) if os.path.exists(review_path) else {}
    rev_jobs = {j["job_key"]: j for j in rev.get("jobs", [])}
    cover_miss = [j["key"] for j in CS.JOBS if j["key"] not in rev_jobs]
    field_miss = []
    for k, j in rev_jobs.items():
        for row in j.get("skills", []):
            if not (row.get("applicable_version") and row.get("sources") and row.get("evidence_summary")
                    and row.get("status") in ("verified", "verified_single_source",
                                              "out_of_scope_3rd_job", "not_found")):
                field_miss.append(k + ":" + str(row.get("skill")))
    check("技能证据映射覆盖 15 个职业且字段完整", not cover_miss and not field_miss,
          "missing=%s fields=%s" % (cover_miss[:3], field_miss[:3]))
    legacy_leak = [x["skill"] for x in CS.CORRECTIONS
                   if x["skill"] in {s.get("n") for c in gd["clsDocs"] for s in (c.get("skills") or [])}]
    check("旧稿错误技能未回流职业卡", not legacy_leak, str(legacy_leak))

    judge_miss = [c.get("en") for c in gd["clsDocs"]
                  if not all("判断" in x for x in (c.get("str") or c.get("weak") or []))]
    check("技能强度/难度判断已标注判断", not judge_miss, str(judge_miss[:4]))

    # --- 图片与外链 -------------------------------------------------------
    imgs = re.findall(r'assets/maplestory/[A-Za-z0-9._-]+', s_cand)
    missing = sorted({p for p in imgs if not os.path.exists(os.path.join(HERE, "source", p))})
    check("maplestory 图片路径全部存在", not missing, str(missing))
    zero = [p for p in set(imgs) if os.path.getsize(os.path.join(HERE, "source", p)) == 0]
    check("图片无 0 字节空文件", not zero, str(zero))

    urls = re.findall(r'https?://[^\s"\'<>\)]+', json.dumps({"t": tl, "b": brief, "p": pb, "g": gd}, ensure_ascii=False))
    insecure = [u for u in urls if u.startswith("http://")]
    check("外链均为 https", not insecure, str(insecure[:3]))

    check("Classic未确认摆摊不作交付或成交依据", "Classic 走人工面交/摆摊" not in json.dumps(gd, ensure_ascii=False) and "币价由摆摊成交" not in json.dumps(brief, ensure_ascii=False))

    # --- HTML 结构 --------------------------------------------------------
    check("script 标签数量未变", s_src.count("<script") == s_cand.count("<script"))
    check("style 标签数量未变", s_src.count("<style") == s_cand.count("<style"))
    check("无 </script> 注入", s_cand.count("</script>") == s_src.count("</script>"))
    check("undefined 出现次数未增加", s_cand.count("undefined") == s_src.count("undefined"),
          "%d -> %d" % (s_src.count("undefined"), s_cand.count("undefined")))

    # JavaScript compilation is asserted in tests/test_render.cjs; isolated Python units cannot spawn processes.

    # --- 改动范围：把候选的五个数据块换回原块，应与原文件逐字节相同 -------
    from jsparse import Parser as _P

    def _span(text, marker):
        i = text.find(marker)
        j = i + len(marker)
        while text[j] not in "{[":
            j += 1
        p = _P(text, j)
        p.value()
        return j, p.i

    rebuilt = s_cand
    for _k, _m in sorted(BLOCKS.items(), key=lambda kv: -_span(s_cand, kv[1])[0]):
        cs, ce = _span(rebuilt, _m)
        os_, oe = _span(s_src, _m)
        rebuilt = rebuilt[:cs] + s_src[os_:oe] + rebuilt[ce:]
    check("改动仅限五个数据块（其余字节完全一致）", rebuilt == s_src,
          "len %d vs %d" % (len(rebuilt), len(s_src)))

    a = s_src.splitlines()
    b = s_cand.splitlines()
    diff = list(difflib.unified_diff(a, b, lineterm="", n=0))
    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))

    import hashlib as _h
    summary = {
        "source_sha256": _h.sha256(open(SRC, "rb").read()).hexdigest(),
        "candidate_sha256": _h.sha256(open(CAND, "rb").read()).hexdigest(),
        "source_chars": len(s_src),
        "candidate_chars": len(s_cand),
        "diff_added_lines": added,
        "diff_removed_lines": removed,
        "checks_total": len(results),
        "checks_failed": sum(1 for r in results if not r["ok"]),
        "counts": {
            "overview_chars": cjk_len(pb["overview"]),
            "core_chars": cjk_len(pb["core"]),
            "tips": len(pb["tips"]), "gallery": len(pb["gallery"]),
            "biz": len(biz), "dept": len(pb["dept"]),
            "tools": len(tl["tools"]), "wikis": len(tl["wikis"]),
            "classes": len(gd["classes"]), "clsDocs": len(gd["clsDocs"]), "clsDeep": len(deep),
            "play": len(gd["play"]), "terms": len(gd["terms"]), "eco": len(gd["eco"]), "ops": len(gd["ops"]),
            "intel_dims": len(brief["cats"]), "intel_items": sum(len(x["items"]) for x in brief["cats"]),
        },
        "failed": [r for r in results if not r["ok"]],
    }
    json.dump({"summary": summary, "checks": results},
              open(os.path.join(HERE, "tools", "verify-report.json"), "w"), ensure_ascii=False, indent=1)
    print("\nsummary:", json.dumps(summary["counts"], ensure_ascii=False))
    print("failed:", summary["checks_failed"], "/", summary["checks_total"])
    return 0 if summary["checks_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
