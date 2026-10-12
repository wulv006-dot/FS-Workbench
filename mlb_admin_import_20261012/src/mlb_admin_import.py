# -*- coding: utf-8 -*-
"""MLB 新卡「xlsm → 后台产品模型」导入编排器。

阶段划分
--------
- 阶段 0（probe）：登录 + 只读。列出 MLB scope 下已有模型，确认 gid/cid 正确。
- 阶段 1（dry-run）：解析 xlsm，算出「将新增 / 已存在」清单，**不写后台**。
- 阶段 2（apply）：真正上传导入 → 轮询进度 → 回读后台核对模型是否生成。

红线（照抄项目纪律，不可协商）
--------------------------
1. 写操作**绝不自动重试**；结果未知一律转人工。
2. 幂等：导入前先按 scope 拉全量模型，比对产品名，已存在的跳过（并在报告里标出）。
3. 每次 apply 必须显式 `--confirm <scope-key>`，防止误触。
4. token / 密码不落盘、不写日志。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from admin_api_client import (  # noqa: E402
    AdminApiClient, AdminAuthError, AdminAuthRequired, AdminContractError,
    AdminUnknownResult, SCOPE_FC27_PLAYERS, SCOPE_MLB26_PLAYERS,
)

SCOPES = {
    "mlb26-players": SCOPE_MLB26_PLAYERS,
    "fc27-players": SCOPE_FC27_PLAYERS,
}


def _log(*a):
    print(*a, flush=True)


def _load_credentials(args) -> tuple[str, str]:
    """凭据来源优先级：命令行 → 环境变量 → 同目录 .p2pah_cred（key=value）。

    ⚠️ 凭据文件不得进 Git（.gitignore 已排除）。
    """
    user = args.user or os.environ.get("P2PAH_USERNAME")
    pwd = args.password or os.environ.get("P2PAH_PASSWORD")
    if not (user and pwd):
        for cand in (HERE / ".p2pah_cred", HERE.parent / ".p2pah_cred"):
            if cand.is_file():
                d = {}
                for line in cand.read_text(encoding="utf-8").splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        d[k.strip()] = v.strip()
                user = user or d.get("P2PAH_USERNAME")
                pwd = pwd or d.get("P2PAH_PASSWORD")
                break
    if not (user and pwd):
        raise SystemExit("[X] 缺少后台凭据：请用 --user/--password、环境变量 "
                         "P2PAH_USERNAME/P2PAH_PASSWORD，或同目录 .p2pah_cred")
    return user, pwd


# --------------------------------------------------------------- xlsm 解析
HEADERS = ["游戏", "服务区", "产品分类", "产品名称", "图标地址", "单价", "折扣",
           "最小购买量", "收货价格(¥)", "是否推荐", "是否热门", "是否启用",
           "产品摘要", "产品描述", "扩展属性", "分类ID（勿改）"]


def read_xlsm_rows(path: str | Path) -> list[dict]:
    """读出 xlsm 里待上架的行（第 4 列有值的 + 启用列=1）。"""
    from openpyxl import load_workbook
    p = Path(path).expanduser()
    wb = load_workbook(p, keep_vba=str(p).lower().endswith(".xlsm"), data_only=True)
    target = None
    for ws in wb.worksheets:
        row1 = [str(ws.cell(row=1, column=i + 1).value or "").strip() for i in range(len(HEADERS))]
        if row1 == HEADERS:
            target = ws
            break
    if target is None:
        raise SystemExit("[X] %s 找不到 16 列表头匹配的工作表" % p.name)
    rows = []
    for r in range(2, target.max_row + 1):
        name = target.cell(row=r, column=4).value
        if not name:
            continue
        rows.append({
            "row": r,
            "product_name": str(name).strip(),
            "price": target.cell(row=r, column=6).value,
            "enabled": target.cell(row=r, column=12).value,
            "hash": str(target.cell(row=r, column=15).value or ""),
            "category_id": target.cell(row=r, column=16).value,
        })
    return rows


def _name_key(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).casefold()


# --------------------------------------------------------------- 三个动作
def do_probe(client: AdminApiClient, scope_key: str, scope: Mapping) -> dict:
    """阶段 0：只读确认 scope 与现有模型数。"""
    _log("== 阶段 0：连通性与 scope 侦察 ==")
    _log("  目标 scope：%s  gid=%s cid=%s" % (scope_key, scope["gid"], scope["cid"]))
    data = client.list_models(gid=scope["gid"], cid=scope["cid"], page=1, limit=1)
    total = data.get("total")
    _log("  模型列表 OK，scope 下现有模型总数 = %s" % total)
    return {"scope": dict(scope), "total": total, "ok": True}


def do_dry_run(client: AdminApiClient, scope_key: str, scope: Mapping,
               xlsm: str | Path) -> dict:
    """阶段 1：算出将新增/已存在清单，不写后台。"""
    _log("== 阶段 1：dry-run（不写后台）==")
    rows = read_xlsm_rows(xlsm)
    _log("  xlsm 待上架行数：%d" % len(rows))

    existing: dict[str, Any] = {}
    page, total = 1, None
    while True:
        data = client.list_models(gid=scope["gid"], cid=scope["cid"], page=page, limit=200)
        for row in data.get("list") or []:
            nm = row.get("title") or row.get("name") or ""
            if nm:
                existing[_name_key(nm)] = row.get("id")
        total = data.get("total")
        if len(existing) >= int(total or 0) or not (data.get("list") or []):
            break
        page += 1
        if page > 200:
            raise AdminContractError("模型分页超过安全上限")

    to_add, dup = [], []
    for r in rows:
        key = _name_key(r["product_name"])
        # xlsm 产品名含 斜杠分段（名/OVR/位置/队/系列），后台 title 通常同名
        if key in existing:
            dup.append(r["product_name"])
        else:
            to_add.append(r["product_name"])

    _log("  后台现有模型：%d 个" % len(existing))
    _log("  将新增：%d 个" % len(to_add))
    for n in to_add:
        _log("    + %s" % n)
    if dup:
        _log("  已存在（跳过）：%d 个" % len(dup))
        for n in dup:
            _log("    = %s" % n)
    return {"rows": len(rows), "existing": len(existing),
            "to_add": to_add, "dup": dup}


def do_apply(client: AdminApiClient, scope_key: str, scope: Mapping,
             xlsm: str | Path, *, wait: float = 180.0) -> dict:
    """阶段 2：真正导入 + 轮询 + 回读。"""
    _log("== 阶段 2：提交导入 ==")
    before = client.list_models(gid=scope["gid"], cid=scope["cid"], page=1, limit=1)
    before_total = before.get("total")
    _log("  导入前模型数：%s" % before_total)

    _log("  上传 %s ..." % Path(xlsm).name)
    try:
        res = client.import_file(xlsm, gid=scope["gid"], cid=scope["cid"])
    except AdminUnknownResult as e:
        _log("  [X] %s" % e)
        return {"ok": False, "unknown": True, "message": str(e)}
    except AdminContractError as e:
        _log("  [X] 后台拒绝或响应异常：%s" % e)
        return {"ok": False, "message": str(e)}

    _log("  导入受理：%s" % json.dumps(res, ensure_ascii=False)[:400])
    job_id = str(res.get("job_id") or res.get("jobId") or res.get("id") or "").strip()
    if not job_id:
        # 有些实现同步返回结果，不返回 job_id —— 直接回读核对
        _log("  ⚠ 响应无 job_id，改为直接回读核对")
    else:
        try:
            prog = client.wait_import(job_id, timeout=wait)
        except AdminContractError as e:
            _log("  [!] 进度查询未成功：%s" % e)
            prog = {}
        else:
            _log("  进度完成：%s" % json.dumps(prog, ensure_ascii=False)[:400])

    time.sleep(2)
    after = client.list_models(gid=scope["gid"], cid=scope["cid"], page=1, limit=1)
    after_total = after.get("total")
    _log("  导入后模型数：%s（前 %s）" % (after_total, before_total))
    return {"ok": True, "job_id": job_id, "before_total": before_total,
            "after_total": after_total, "accepted": res}


# --------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="MLB 新卡后台导入（admin-api.p2pah.cn）")
    ap.add_argument("--scope", default="mlb26-players", choices=sorted(SCOPES),
                    help="业务 scope（默认 mlb26-players）")
    ap.add_argument("--action", default="probe", choices=["probe", "dry-run", "apply"],
                    help="probe=只读侦察 / dry-run=比对不写 / apply=真正导入")
    ap.add_argument("--xlsm", help="待导入的 xlsm/xlsx 路径（dry-run / apply 必需）")
    ap.add_argument("--user"); ap.add_argument("--password")
    ap.add_argument("--wait", type=float, default=180.0, help="导入进度最长等待秒数")
    ap.add_argument("--confirm", help="apply 时必须等于 scope key，防误触")
    ap.add_argument("--json-out", help="把结果写到此 JSON 文件")
    args = ap.parse_args(argv)

    scope = SCOPES[args.scope]
    if args.action in ("dry-run", "apply") and not args.xlsm:
        raise SystemExit("[X] 需要 --xlsm")
    if args.action == "apply" and args.confirm != args.scope:
        raise SystemExit("[X] 危险操作：必须 --confirm %s 才执行导入" % args.scope)

    user, pwd = _load_credentials(args)
    client = AdminApiClient(log=_log)

    _log("登录中（ddddocr 自动过码）...")
    try:
        client.login_with_ocr(user, pwd)
    except AdminAuthError as e:
        raise SystemExit("[X] 登录失败：%s" % e)

    result: dict
    if args.action == "probe":
        result = do_probe(client, args.scope, scope)
    elif args.action == "dry-run":
        result = do_dry_run(client, args.scope, scope, args.xlsm)
    else:
        result = do_apply(client, args.scope, scope, args.xlsm, wait=args.wait)

    _log("== 完成 ==")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        _log("结果已写入 %s" % args.json_out)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
