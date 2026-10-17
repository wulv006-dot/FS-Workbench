# -*- coding: utf-8 -*-
"""只读核验「新增模型」通道是否对 MLB 开放。

方法：POST /admin/goods.GoodsMould/add，**body 为空对象 {}}**。
判读：
  - 若返回 '仅支持 FC26/FC27'  → MLS 被 gid 白名单拦（与 importPlayers 同）
  - 若返回 字段必填校验错误     → 通道开放，只是缺字段（说明 MLB 能走这条路）
  - 空 body 在任何后端必填校验下都**不可能创建成功**，因此本探测零写入风险。
"""
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from admin_api_client import AdminApiClient

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

print("\n--- 探测 POST /admin/goods.GoodsMould/add （空 body，零写入风险）---")
try:
    r = c._json("POST", "/admin/goods.GoodsMould/add", json_body={})
    print("  响应:", json.dumps(r, ensure_ascii=False)[:400])
except Exception as e:
    print("  异常:", repr(e))

print("\n--- 对照：GET /admin/goods.GoodsMould/add（只读，看是否被当作 index）---")
try:
    r = c._json("GET", "/admin/goods.GoodsMould/add")
    print("  响应:", json.dumps(r, ensure_ascii=False)[:400])
except Exception as e:
    print("  异常:", repr(e))
