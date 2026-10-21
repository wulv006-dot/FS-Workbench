# -*- coding: utf-8 -*-
"""FC27 SBC 上架工具 —— 本地网页界面。

为什么不用 tkinter：本机 Python 是精简版，**没有 tkinter**（无 Lib/tkinter、无 tcl/tk），
桌面版会直接崩。改用纯标准库的本地 HTTP 服务 + 单页界面，任何 Python 3.10+ 都能跑，
验证码也直接在浏览器里显示，比命令行方便。

安全：只监听 127.0.0.1，不对外开放；账号密码只存在进程内存。
"""

from __future__ import annotations

import base64
import fnmatch
import io
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))


def _check_deps() -> None:
    """缺依赖时给一句人话，而不是甩一段 traceback。"""
    missing = []
    for mod, pkg in (("openpyxl", "openpyxl"), ("PIL", "pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.stderr.write(
            "\n"
            "========================================================\n"
            "  缺少运行依赖：" + "、".join(missing) + "\n"
            "\n"
            "  请先安装（在本文件所在目录执行）：\n"
            "      python -m pip install -r requirements.txt\n"
            "========================================================\n"
            "\n"
        )
        raise SystemExit(2)


_check_deps()

from datetime import datetime  # noqa: E402
from decimal import Decimal, InvalidOperation  # noqa: E402
from typing import Any, Mapping, Optional, Sequence  # noqa: E402

import admin_client as ac  # noqa: E402
import fetch_sbc  # noqa: E402
import fetch_futgg  # noqa: E402
import auto_flow  # noqa: E402
import iconfix  # noqa: E402
import pricing  # noqa: E402
import repricer  # noqa: E402
import watermark  # noqa: E402
import workbook as wb  # noqa: E402
import uploader  # noqa: E402 —— 还要用它的 normalize_title / build_title_index（跨类目去重）
from uploader import Plan, Uploader, icon_extensions, icon_stem  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8791
OUTPUT_DIR = APP_DIR / "output"
CACHE_DIR = APP_DIR / "cache"
ICON_DIR = CACHE_DIR / "icons"
RAW_ICON_DIR = CACHE_DIR / "icons_raw"
HISTORY_PATH = OUTPUT_DIR / "sbc_history.json"
DEFAULT_XLSX = OUTPUT_DIR / "SBC导入表.xlsx"
# 改价设置（金币数 / 加成）持久化在这里
REPRICE_SETTINGS = OUTPUT_DIR / "repricer_settings.json"
# ⑥ 自动化（定时采集改价 / 自动下架）的设置与运行留痕
AUTO_SETTINGS = OUTPUT_DIR / "auto_settings.json"
# 云端部署时的 URL 前缀（如 /dashboard/fc27-sbc）。本地为空。
# 所有路由先剥掉这个前缀再匹配；前端 JS 用 BASE 变量拼 API 地址。
BASE_PREFIX = os.environ.get("FC27_BASE_PATH", "").strip().rstrip("/")
# 「记住登录状态」的可选落盘位置。
# 默认不写；只有用户在登录框勾选后才会落盘，且放在 cache/ 下
# （cache/ 不进交付包，见根目录 make_release.py 的排除规则）。
# 「这个模型的图是本工具加过水印的」台账。属于**用户数据**，放 output/：
# 换新版解压覆盖时它会留着，同时**不进交付包**（已登记在 make_release.py / pack_zip.py）。
#
# 为什么需要它：工具无法从图片本身判断"这图加过印没有"，而模型图是**全站点共用**的，
# 重复点一次「一键添加水印」就会在同一张图上叠第二层 —— 肉眼看得出来，且不可逆。
# 所以**用我们自己的产出当幂等依据**：记下"这个 mid 现在挂的 icon 是本工具生成的附件 id"，
# 下次开工前比一下 icon 是否仍是它 —— 是就跳过。
# （和「一键修复图片」拿 cache/icons_raw 当幂等源是同一个思路。）
MODEL_WATERMARK_RECORD = OUTPUT_DIR / "model_watermark.json"
DELIST_RECEIPTS = OUTPUT_DIR / "delist_receipts.json"

MAX_ICON_BYTES = 6 * 1024 * 1024      # 单张图上限
MAX_ICON_PIXELS = 1024                # 超过就等比缩小

# ⑤「一键添加水印」一次最多处理多少个模型 —— 避免误勾全选把几百个产品串着改一遍
MAX_WATERMARK_MODELS = 200
# 下载后台商品图时的 UA。b2c-static 是公开 CDN，不带 UA 会被挡。
IMAGE_UA = "Mozilla/5.0 (compatible; FC27-SBC-Tool)"

_CTYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _ctype_for(path: Path) -> str:
    return _CTYPE.get(path.suffix.lower(), "application/octet-stream")


def _route_path(raw: str) -> str:
    """云端部署时剥掉 URL 前缀（FC27_BASE_PATH，如 /dashboard/fc27-sbc）。

    本地（前缀为空）原样返回。前端 JS 用 BASE 变量拼 API 地址，两边对齐。
    """
    if BASE_PREFIX and (raw == BASE_PREFIX or raw.startswith(BASE_PREFIX + "/")):
        trimmed = raw[len(BASE_PREFIX):]
        return trimmed or "/"
    return raw


# ---------------------------------------------------------------- 会话状态


class Session:
    def __init__(self) -> None:
        self.client = ac.AdminClient()
        self.logs: list[str] = []
        self.rows: list[wb.SbcRow] = []
        self.lock = threading.Lock()
        self.last_scope = ""
        self.busy = False
        # 本轮**真正上架过**的模型 ID（2026-10-15 用户口径：自动流程的水印只加这些）。
        # 上架（③）写、水印（⑤）读；进程内有效，重启清零。
        self.shelved_mids: list[int] = []

        # 列表编辑态：uid 是给前端的稳定标识，避免删行后下标串位
        self.rows_path: Path = DEFAULT_XLSX
        self.uid_of: dict[str, wb.SbcRow] = {}
        self.uid_of_row: dict[int, str] = {}
        self.uid_seq = 0
        self.dirty = False          # 是否有未保存到导入表的改动

        # 改价：设置 + 最近一次拉到的在售行
        self.reprice_settings = repricer.Settings(REPRICE_SETTINGS)
        self.goods_rows: list[repricer.GoodsRow] = []

    def log(self, message: str) -> None:
        """打一条操作日志。**每条都带 HH:MM:SS 时间戳**（2026-10-15 用户要求）——
        多行消息（traceback / 多行摘要）逐行加，行首对齐好读；控制台同步打印同一份。"""

        text = str(message)
        stamp = time.strftime("[%H:%M:%S] ")
        stamped = "\n".join(stamp + line for line in text.splitlines()) or stamp.rstrip()
        with self.lock:
            self.logs.append(stamped)
            if len(self.logs) > 600:
                del self.logs[:200]
        print(stamped, flush=True)

    def take_logs(self, since: int) -> tuple[list[str], int]:
        with self.lock:
            return self.logs[since:], len(self.logs)

    @property
    def logged_in(self) -> bool:
        return self.client.authenticated

    # ---- 列表与 uid ----
    def set_rows(self, rows, path) -> None:
        self.rows = list(rows)
        self.rows_path = Path(path)
        self.uid_of = {}
        self.uid_of_row = {}
        for row in self.rows:
            self.uid_seq += 1
            uid = f"r{self.uid_seq}"
            self.uid_of[uid] = row
            self.uid_of_row[id(row)] = uid
        self.dirty = False

    def uid(self, row) -> str:
        return self.uid_of_row.get(id(row), "")

    def row_by_uid(self, uid) -> wb.SbcRow | None:
        return self.uid_of.get(str(uid or ""))

    def drop(self, row) -> None:
        try:
            self.rows.remove(row)
        except ValueError:
            return
        self.uid_of.pop(self.uid_of_row.pop(id(row), ""), None)

    def selected_count(self) -> int:
        return sum(1 for r in self.rows if r.selected)


SESSION = Session()


def _truthy(value: Any) -> bool:
    """严格解析开关值，只认 JSON true / 1 和常见的真值字符串。

    这里**不能**用 Python 的 bool()：字符串 "false" 在 Python 里是真值，
    会把「不要记住」误判成「要记住」——而这个开关的后果是把登录凭据写进磁盘。
    所以宁可严格，让不认识的输入一律按「不记住」处理。
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return str(value or "").strip().lower() in {"true", "1", "yes", "on"}


class BadInput(Exception):
    """用户填的输入有问题 —— 回 400 + ok:False，不当 500 报。

    凡是会影响**写操作**（保存设置、改价、上架）的参数校验失败都抛这个，
    这样前端拿到的是能直接弹给人看的中文提示，而不是一坨 traceback。
    """


def _workbook_path(raw=None) -> Path:
    """Keep every user-selected workbook inside this tool's output directory."""
    if OUTPUT_DIR.is_symlink():
        raise BadInput("输出目录不能是符号链接")
    root = OUTPUT_DIR.resolve()
    path = Path(raw or DEFAULT_XLSX)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if root not in path.parents or path.suffix.lower() != ".xlsx":
        raise BadInput("仅允许读写本工具输出目录内的 .xlsx 文件")
    return path


def _dec(value, default: str) -> Decimal:
    """宽松解析：空值或乱填都回落到 default。

    ⚠️ 只适合**读**场景或「默认值就是唯一正确答案」的场景。
    凡是参数会被写进后台/落盘的，请用 `_strict_dec` —— 否则用户把 0.24
    打成全角 "0.2４"，会被静默换成默认值而他完全看不出来。
    """
    try:
        text = str(value).strip()
        return Decimal(text) if text else Decimal(default)
    except (InvalidOperation, TypeError):
        return Decimal(default)


def _strict_dec(value, default: str, label: str) -> Decimal:
    """严格解析：空 -> default；乱填 -> 抛 `BadInput`（带中文说明）。

    注意 `default` 之前这里有个坑：老代码写 `_dec(x)` 少传 default，
    直接 TypeError。所以这个函数把两个参数都设成必填，且调用点有静态自检。
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return Decimal(default)
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        raise BadInput(f"{label}不是数字：{value!r}") from None


# ---------------------------------------------------------------- 模型图水印台账


_model_wm_lock = threading.Lock()
_model_wm_cache: Optional[dict] = None      # None = 还没从磁盘读过


def watermark_records() -> dict:
    """``{ '<mid>': {'icon': <附件 id>, 'at': '...'} }``。

    文件不存在 / 读坏了一律当**空**：这样最坏结果是"可能多叠一层"，
    而不是"该加的没加" —— 后者用户根本看不出来。
    """

    global _model_wm_cache
    with _model_wm_lock:
        if _model_wm_cache is None:
            data = None
            try:
                data = json.loads(MODEL_WATERMARK_RECORD.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            done = data.get("done") if isinstance(data, Mapping) else None
            _model_wm_cache = dict(done) if isinstance(done, Mapping) else {}
        return dict(_model_wm_cache)


def record_watermark(mid: int, icon: int) -> None:
    """记下「mid 现在挂的这张图是本工具生成的」。写盘失败只记日志，不中断换图。"""

    global _model_wm_cache
    with _model_wm_lock:
        done = dict(_model_wm_cache or {})
        done[str(int(mid))] = {
            "icon": int(icon),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _model_wm_cache = done
        try:
            MODEL_WATERMARK_RECORD.parent.mkdir(parents=True, exist_ok=True)
            MODEL_WATERMARK_RECORD.write_text(
                json.dumps({"version": 1, "done": done}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            SESSION.log(f"  台账写盘失败（本次换图不受影响，但下次可能重复加印）：{exc}")


def watermark_record_of(mid: Optional[int]) -> Optional[int]:
    """台账里记的 icon id；没有记录 / 记录坏了返回 None。"""

    if not mid:
        return None
    item = watermark_records().get(str(int(mid)))
    if isinstance(item, Mapping):
        try:
            return int(item.get("icon"))
        except (TypeError, ValueError):
            return None
    return None


def _uploader(cid: int | None = None, *, title_index: Mapping | None = None) -> Uploader:
    """构造上架器。``cid`` 不传用默认 9971（SBC > Upgrade）。

    2026-10-15 起导入表里同时有 SBC（9971 / 10203）与 Packs（10255）行 ——
    上架按 **cid 分组**，每组各建一个 Uploader（见 ``_plan_now``）；
    ``title_index`` 是**跨类目同名索引**（口径 B），用来避免跨类目重复建同名模型。
    """
    kwargs: dict = {"title_index": title_index or {}}
    if cid:
        kwargs["cid"] = int(cid)
    return Uploader(SESSION.client, cache_dir=CACHE_DIR, log=SESSION.log, **kwargs)


def _row_payload(row: wb.SbcRow) -> dict:
    local = bool(row.icon_path and Path(row.icon_path).is_file())
    rev = ""
    if local:
        try:
            # 用**纳秒**而不是秒。秒级的 mtime 在同一秒内换过两次图时算出来是同一个数，
            # 缩略图 URL 里的 ?t= 就不变，浏览器可能继续拿旧图 —— 看着就是"换了没反应"。
            # 纳秒的值全部是数字，JS 侧 `${esc(r.icon_rev)||0}` 不受影响。
            rev = str(Path(row.icon_path).stat().st_mtime_ns)
        except OSError:
            rev = ""
    return {
        "uid": SESSION.uid(row),
        "status": row.status,
        "title": row.title,
        "cid": row.cid,
        "coins": row.coins,
        "price": str(row.price_usd) if row.price_usd is not None else "",
        "sbc_id": row.sbc_id,
        "model_id": row.model_id or "",
        "futbin": row.futbin_url,
        "include": row.include,
        "selected": row.selected,
        "summary": row.summary,
        "description": row.description,
        "remark": row.remark,
        "expires": row.expires,
        "platform": row.platform,
        "icon_url": row.icon_url,
        "has_icon": bool(local or row.icon_url),
        "local_icon": local,
        "icon_rev": rev,
    }


def _rows_payload() -> list[dict]:
    return [_row_payload(r) for r in SESSION.rows]


def _list_state() -> dict:
    """所有会改动列表的接口都回这一份状态，前端统一刷新。"""

    return {
        "rows": _rows_payload(),
        "count": len(SESSION.rows),
        "selected": SESSION.selected_count(),
        "dirty": SESSION.dirty,
        "path": str(SESSION.rows_path),
    }


def _load_rows(path: str) -> list[wb.SbcRow]:
    target = Path(path) if path else DEFAULT_XLSX
    if not target.is_file():
        raise FileNotFoundError(f"导入表不存在：{target}")
    return wb.read_rows(target)


def _refresh_coin(aid: int):
    return pricing.fetch_coin_prices(
        [aid], cache_path=CACHE_DIR / "coin_price.json"
    )[aid]


def _price_inputs(body: dict) -> tuple:
    coin = _refresh_coin(int(body.get("aid") or pricing.DEFAULT_AREA_AID))
    # 空 = 用实时行情（正常路径）；乱填 = 报错。
    # 原来这里用 _dec(..., "0")，手打错会静默用实时价，用户以为自己设了自定义价。
    raw = "" if body.get("unit_price") is None else str(body.get("unit_price")).strip()
    if not raw:
        per_coin = Decimal("0")
    else:
        per_coin = _strict_dec(raw, "0", "金币单价") / Decimal("1000")
    if per_coin <= 0:
        per_coin = coin.per_coin
    return coin, per_coin


def _ensure_icon(row: wb.SbcRow) -> Path | None:
    """保证这一行有本地图片；没有就按图标地址下载。返回本地路径。"""

    if row.icon_path and Path(row.icon_path).is_file():
        return Path(row.icon_path)
    _uploader().download_icons([row])
    if row.icon_path and Path(row.icon_path).is_file():
        return Path(row.icon_path)
    return None


# ---------------------------------------------------------------- 业务动作


def do_readonly_check() -> dict:
    up = Uploader(SESSION.client, cache_dir=CACHE_DIR, log=SESSION.log)
    existing = up.fetch_existing()
    scope = up.describe_scope()
    SESSION.last_scope = scope
    SESSION.log(f"后台 9971 类目现有模型 {len(existing)} 个")
    return {"ok": True, "scope": scope, "existing": list(existing)[:40],
            "count": len(existing)}


# ---------------------------------------------------------------- 按区改价


def _paged_goods(
    *,
    gid: int = ac.GID_FC27,
    cid: Optional[int] = None,
    mid: Optional[int] = None,
    site_id: Optional[int] = None,
    limit: int = 200,
) -> list[Mapping[str, Any]]:
    """翻页拉完在售商品；cid / mid / site_id 为服务端筛选条件。"""

    out: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    page = 1
    while True:
        page_data = SESSION.client.list_goods(
            gid=gid, cid=cid, mid=mid, site_id=site_id, page=page, limit=limit,
        )
        for raw in page_data.rows:
            rid = int(raw.get("id") or 0)
            if not rid or rid in seen:
                continue
            seen.add(rid)
            out.append(raw)
        if not page_data.rows or len(seen) >= page_data.total:
            break
        page += 1
        if page > 200:
            SESSION.log(f"翻页超过 200 页，提前停止（已取 {len(out)} 条）")
            break
    return out


def _cid_of(raw: Mapping[str, Any]) -> Optional[int]:
    value = raw.get("cid")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_rows(raws: Sequence[Mapping[str, Any]], *,
                extra_leaf_kinds: Mapping[int, str] = {}) -> list[repricer.GoodsRow]:
    """后台原始行 -> GoodsRow（带金币数 / 每金币价 / 手续费 / 加成）。

    ``extra_leaf_kinds``：后台现问出来的、**代码里没写死**的叶子 cid -> 它算哪个类目
    （``{10500: "SBC"}`` / ``{10255: "Packs"}`` 这种）。这些 cid 不在任何常量里，
    ``kind_of_cid()`` 推不出归属，所以要显式告诉它 —— 否则会被当成"类目未知"
    （kind=''）：**SBC 会静默少收 0.24×加成，Packs 的「类目」列会显示空**。

    ⚠️ 参数默认值给的是空字典但**只读不写**（当常量用），不要往里塞东西。
    """

    settings = SESSION.reprice_settings
    # 当前所有区服默认值。用来判断某个逐产品值"看起来是不是自动带出的"（见 rate_auto）。
    aid_values = set(settings.aid_rates().values())
    rows: list[repricer.GoodsRow] = []
    for raw in raws:
        def _opt_int(key: str) -> Optional[int]:
            v = raw.get(key)
            if v in (None, ""):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        mid_int = _opt_int("mid")
        title = str(raw.get("title") or "")
        coins = settings.coins_for(model_id=mid_int, title=title)
        # 每金币价：逐产品手改优先，其次按区服的 MMOEXP 默认值。
        # 拿不到就是 None —— 这时目标价会留空，而不是塞一个错的值。
        rate = settings.rate_for(model_id=mid_int, title=title, aid=_opt_int("aid"))
        # 同时告诉前端「这个值是手改的还是带出的」——
        # 「重新按 MMOEXP 带出」时前者不能覆盖，后者该被新行情刷新。
        own_rate = settings.own_rate(model_id=mid_int, title=title)
        rate_own = own_rate is not None
        # 这个"手改值"是不是**看起来就是自动带出后被存下来的**：值恰好等于某个区服默认价。
        # 见 GoodsRow.rate_auto 的注释 —— 只用于把弹窗措辞说清楚，不参与计算、不自动改数据。
        rate_auto = rate_own and own_rate in aid_values
        # 手续费**逐产品可覆盖**（2026-09-29 起）：表格里「手续费」列每行能单独改。
        #   设过  -> 用那个覆盖值，并打 fee_own 标记（改全局手续费时不许顺手改掉它）
        #   没设  -> 沿用全局 settings.fee
        # 传下去的是**已解析的生效值**，前端直接显示；是否真的加仍由类目决定
        # （只有 SBC 加、Packs 恒为 0），见 GoodsRow.fee_applied。
        fee_override = settings.row_fee(model_id=mid_int, title=title)
        # 加成**逐产品可覆盖**（2026-10-06 起）：表格里「加成」列每行能单独改。
        #   设过  -> 用那个覆盖值，并打 markup_own 标记（改全局加成时不许顺手改掉它）
        #   没设  -> 沿用全局 settings.markup
        # 与 fee 唯一的差别：加成**不分类目**，SBC / Packs 都乘它。
        markup_override = settings.row_markup(model_id=mid_int, title=title)
        # 后台现问出来的新叶子（不在常量里）：显式告诉它算 SBC 还是 Packs。
        # 漏了这一步 kind 就是空串 —— SBC 静默少收手续费、Packs「类目」列显示空。
        raw_cid = _cid_of(raw)
        extra_kind = extra_leaf_kinds.get(raw_cid) if raw_cid is not None else None
        rows.append(repricer.row_from_api(raw, coins=coins, rate=rate,
                                          rate_own=rate_own,
                                          rate_auto=rate_auto,
                                          fee=(fee_override if fee_override is not None
                                               else settings.fee),
                                          fee_own=fee_override is not None,
                                          kind=extra_kind,
                                          markup=(markup_override
                                                  if markup_override is not None
                                                  else settings.markup),
                                          markup_own=markup_override is not None))
    return rows


def _leaf_cids_online(parent_cid: int, fallback: tuple[int, ...]) -> tuple[tuple[int, ...], str]:
    """现问一次后台：``parent_cid`` 底下**现在**有哪些叶子类目。

    返回 ``(叶子 cid 元组, 来源说明)``。**问不到就退回写死的清单** ——
    读类目树纯粹是为了"别漏"，绝不该因为它失败就拉不到在售行。

    为什么不缓存：类目是后台随时能改的 ——
    2026-10-06 在 SBC(9625) 底下加了 10203 SBC Players；
    2026-10-13 又在 Packs(9629) 底下加了 10255 In-Game Packs。
    **两次事故都是"写死"造成的**，别再换成"缓存住旧类目"。
    """

    try:
        leaves = SESSION.client.child_leaf_cids(int(parent_cid), gid=ac.GID_FC27)
    except Exception as exc:            # noqa: BLE001 —— 见 docstring，绝不因此拉不到数据
        return fallback, f"退回写死清单（问后台失败：{type(exc).__name__}）"
    if not leaves:
        return fallback, f"退回写死清单（后台说 {parent_cid} 底下没有叶子）"
    extra = sorted(set(leaves) - set(fallback))
    note = f"后台实时 {list(leaves)}"
    if extra:
        note += f"，其中 {extra} 没写死在代码里（照样收）"
    return tuple(leaves), note


def _sbc_leaf_cids_online() -> tuple[tuple[int, ...], str]:
    """SBC(9625) 底下现在的叶子（薄包装，调用点读起来更直白）。"""

    return _leaf_cids_online(repricer.CID_SBC, repricer.SBC_LEAF_CIDS)


def _packs_leaf_cids_online() -> tuple[tuple[int, ...], str]:
    """Packs(9629) 底下现在的叶子（2026-10-13 起有 10255 In-Game Packs）。"""

    return _leaf_cids_online(repricer.CID_PACKS, repricer.PACKS_LEAF_CIDS)


def _extra_leaf_kinds(leaves: Sequence[int], kind: str) -> dict[int, str]:
    """把"``kind_of_cid()`` 自己推不出归属"的叶子挑出来，映射成 ``cid -> kind``。

    判据就是 ``kind_of_cid(cid) == ''`` —— **只给推不出来的补**，凡是已经在
    常量里的 cid 一律不碰。这一点很关键：如果按"不在本类目清单里"来判，
    那么把另一个父类目的叶子（如 9971）也算成"新的"，就会**把 SBC 的叶子
    标成 Packs**，手续费跟着静默变 0。

    这些 cid 不在任何常量里，``kind_of_cid()`` 推不出归属，所以要显式告诉
    ``_build_rows()``；否则会被当成"类目未知"（kind=''），
    **SBC 少收手续费、Packs 显示空类目**，都是静默的。
    """

    return {int(c): kind for c in leaves if not repricer.kind_of_cid(int(c))}


# 目标父类目 -> (写死兜底的叶子, kind 名)。**只读常量**。
# ⚠️ 加新父类目时只改这一处 —— 收口、日志、kind 覆盖三件事都从这里取。
_PARENT_LEAF_SPECS: tuple[tuple[int, tuple[int, ...], str], ...] = (
    (repricer.CID_SBC, repricer.SBC_LEAF_CIDS, "SBC"),
    (repricer.CID_PACKS, repricer.PACKS_LEAF_CIDS, "Packs"),
)


def _online_leaf_kinds(parents: Sequence[int]) -> tuple[set[int], dict[int, str]]:
    """给一批父类目，每个都现问一次叶子。

    返回 ``(实时拿到的所有叶子 cid, 「代码里没写死的叶子」cid -> kind)``：
    前者用于**收口**（行里带的是叶子 cid，必须认），后者用于**告诉 kind 口径**
    （不然新叶子会被当成"类目未知"）。

    两个父类目**都要问**：SBC(9625) 和 Packs(9629) 都各自被后台加过叶子
    （2026-10-06 的 10203、2026-10-13 的 10255）。只补一个，另一个就静默丢产品。

    返回的 ``all_leaves`` 是"信任后台"的全集（不去重跨类目）—— 收口阶段宁可多收，
    真正决定 kind 的是 `_extra_leaf_kinds()`，它只认 `kind_of_cid()` 推不出来的 cid。
    """

    all_leaves: set[int] = set()
    extra: dict[int, str] = {}
    for parent, fallback, kind_name in _PARENT_LEAF_SPECS:
        if parent not in parents:
            continue
        leaves, src = _leaf_cids_online(parent, fallback)
        all_leaves.update(int(c) for c in leaves)
        unknown = _extra_leaf_kinds(leaves, kind_name)
        for cid_, k in unknown.items():
            # 同一个 cid 被两个父类目都报成"未知"实际上不可能（cid 全局唯一），
            # 真出现就**保留先到的那个**（SBC 在 _PARENT_LEAF_SPECS 里排在前），
            # 别让后来的把定价口径悄悄改掉（SBC↔Packs 决定收不收手续费）。
            extra.setdefault(cid_, k)
        if unknown:
            hint = "SBC_LEAF_CIDS" if kind_name == "SBC" else "PACKS_LEAF_CIDS"
            SESSION.log(f"  ⚠️ 后台的 {kind_name} 叶子里有工具没写死的 {sorted(unknown)}："
                        f"本次照样收、并按 {kind_name} 计价"
                        + ("（含手续费）" if kind_name == "SBC" else "（Packs 不收手续费）")
                        + f"；想让「类目」列显示它的名字，把它加进 repricer.{hint}")
        SESSION.log(f"  {kind_name}({parent}) 的叶子类目：{src}")
    return all_leaves, extra


def _goods_audit(
    *,
    cids: Sequence[int] = repricer.TARGET_CIDS,
    gid: int = ac.GID_FC27,
    site_id: Optional[int] = repricer.SITE_ALL,
    only_live: bool = True,
) -> list[dict]:
    """拉在售商品（只取指定类目：SBC 9625 + Packs 9629）。

    每行 = 模型 × 站点 × 区服。**默认只取 site_id=0（"0 ALL"）**，
    这样每个产品只出 3 行（PC / Xbox / PS5），与后台页面「所属站点=0 ALL」
    的视图一致；不传 site_id 会把 18 个站点全铺开，看着像大量重复。

    ``only_live`` 默认 True —— **状态没亮的行不返回**（用户要求：不显示），
    因为那些行本来也不允许改价，留在列表里只是噪音。

    对「服务端是否支持 cid / site_id 筛选」做了容错：先按条件拉，
    若一个都没拉到，就退化成全量拉 + 本地过滤，避免后端不认条件时静默拉空。
    """

    target = {int(c) for c in cids}

    # 收口用的"可接受 cid"= 目标父类目 + **它底下所有叶子**。
    #
    # ⚠️ 为什么必须带上叶子：列表查询传父类目时后端会把子孙都带回来，
    #    但**每一行带的是叶子的 cid**（如 9971 / 10203），父类目 9625 根本不出现。
    #    2026-10-06 后台在 9625 下新加了叶子 10203 SBC Players，而这里当时只认
    #    写死的 9971，于是那 18 行被**静默丢掉**：日志只有一句"过滤掉 18 行"，
    #    用户看到的是「后台里有、工具里没有」，还以为工具坏了。
    accept = set(target)
    leaves_now, extra_leaf_kinds = _online_leaf_kinds(target)
    accept |= leaves_now

    raws: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for cid in cids:
        part = _paged_goods(gid=gid, cid=int(cid), site_id=site_id)
        fresh = [r for r in part if int(r.get("id") or 0) not in seen]
        for r in fresh:
            seen.add(int(r.get("id") or 0))
        SESSION.log(f"  cid={cid}（{repricer.kind_of_cid(int(cid))}）拉到 {len(fresh)} 行")
        raws.extend(fresh)

    if not raws:
        SESSION.log("  按 cid 筛选没拉到任何行，退化为全量拉取后本地过滤")
        raws = _paged_goods(gid=gid, site_id=site_id)

    # 收口：行里带了 cid 的，必须落在可接受集合内；
    # 没带 cid 的（后端没返回该字段）一律保留 —— 宁可多显示，也不能凭缺失字段丢数据。
    #
    # 丢弃时**必须留痕**：只报"丢了几行"等于没报 —— 用户看不出丢的是哪个类目、
    # 哪些产品，也就没法判断该不该管。这里把 cid 和几个标题写进日志。
    kept: list[Mapping[str, Any]] = []
    dropped: list[tuple[Optional[int], str]] = []
    for raw in raws:
        c = _cid_of(raw)
        if c is None or c in accept:
            kept.append(raw)
        else:
            dropped.append((c, str(raw.get("title") or "")))
    if dropped:
        kinds = sorted({str(c) for c, _ in dropped})
        sample = "、".join(f"{t or '(无标题)'}(cid={c})" for c, t in dropped[:3])
        SESSION.log(f"  本地过滤掉 {len(dropped)} 行（cid 不在 {sorted(accept)} 内）："
                    f"cid={kinds}；例如 {sample}"
                    + ("…" if len(dropped) > 3 else "")
                    + "。若是新类目，把它加进 repricer.SBC_LEAF_CIDS"
                      " 或 repricer.PACKS_LEAF_CIDS（看它挂在 9625 还是 9629 下）")
    if kept:
        found = sorted({_cid_of(r) for r in kept if _cid_of(r) is not None})
        sites = sorted({int(r.get("site_id") or 0) for r in kept})
        SESSION.log(f"  实际出现的 cid：{found or '（行里没有 cid 字段）'}")
        SESSION.log(f"  实际出现的 site_id：{sites}")

    rows = _build_rows(kept, extra_leaf_kinds=extra_leaf_kinds)
    if only_live:
        rows, dead = repricer.split_live(rows)
        if dead:
            SESSION.log(f"  已隐藏 {len(dead)} 条状态未亮的行"
                        f"（{repricer.summarize_titles(dead)}）")

    SESSION.goods_rows = rows
    titles = len({r.title for r in rows})
    SESSION.log(f"共 {len(rows)} 条在售行 / {titles} 个产品（全部为亮的行）")
    return [r.to_dict() for r in rows]


def do_fetch_rates(body: dict) -> dict:
    """按区服从 MMOEXP 取「每金币价」，写成默认值并应用到当前拉取到的行。

    这是 `目标价 = (金币数 × 每金币价) × 加成` 里那个「每金币价」的来源。
    取回后按 aid 存进设置当**默认值**（逐产品手改过的仍以手改优先），
    所以下次拉取不用再点一次。
    """

    aids = [int(a) for a in (body.get("aids") or list(pricing.AREA_AIDS))]
    if not aids:
        return {"ok": False, "error": "没有要取价的区服"}

    # `force=true` = 跳过 30 分钟缓存，真的去打一次 MMOEXP。
    # 2026-09-28 补的：原来只有一条路，缓存期内点多少次都返回同一个数、
    # 界面还照样说"已按 MMOEXP 取回" —— 用户据此以为那就是最新价，实测晚了 10 分钟就差了 5.5%。
    #
    # 2026-09-29 收敛：⑤ 面板**只剩一个取价按钮**，且恒定传 `force=true`
    # （用户要求把「按 MMOEXP 带出每金币价」和「强制刷新最新价」合成一个）。
    # 界面那边**不再存在**"可能给你缓存值、却看起来像最新价"的入口。
    # 参数保留是因为 ③ 计价面板 / 其它调用方仍可能要缓存 —— 而且断网时
    # `fetch_coin_prices` 还是会退回缓存，那时 `from_cache=true` 必须如实上报（见下）。
    force = bool(body.get("force"))
    # `overwrite_own=true` = 「连那些被单独设过的行也一起覆盖」。
    #
    # 为什么需要这个开关（2026-09-29 用户报「强制刷新后 PC 价是 141，表格里不变」）：
    # 老版本的「保存」会把表格里**自动带出的区服默认值**一起写进 by_model / by_title，
    # 而这两级的优先级高于 by_aid —— 于是这些产品从此被判成"手改过"，
    # 点带出/强制刷新一律跳过（实测日志：「其中 0 行用上了默认值」）。
    # 光靠代码分不出"真手填"和"被保存冻结的自动值"，所以这件事**交给用户决定**：
    # 前端会先弹一次确认，用户点了确定才把 overwrite_own 传过来。
    #
    # ⚠️ 覆盖时必须**同时清掉这些产品的逐产品 rate**，否则下面那个循环照样
    #    因为 own_rate() 非空而跳过，这次刷新等于白点（而且下次拉行又会取回旧值）。
    overwrite_own = bool(body.get("overwrite_own"))
    meta: dict = {}
    cache_path = CACHE_DIR / "coin_price.json"

    # ① **优先从后台取**（site_id=266 = mmoexp.com 那个站点）—— 2026-10-16 实测：
    #    公开站 www.mmoexp.com 对数据中心 IP 返回 WowVendor 反爬校验（HTTP 403），
    #    云端**永远**取不到；而**同一份数据在后台里**（gid 1327 / cid 9623 / site 266
    #    的 unit_price，单位也是"每 1K"），实测与公开站完全一致（0.119946 / 0.119946 / 0.1039）。
    prices: Optional[dict] = None
    if SESSION.logged_in:
        try:
            prices = pricing.fetch_from_admin(SESSION.client, aids=aids, log=SESSION.log)
            pricing.save_cached_prices(cache_path, prices,
                                       source="后台 site_id=266（mmoexp.com）")
            meta = {"from_cache": False, "fetched_at": time.time(),
                    "areas": len(prices), "source": "后台 site 266（mmoexp.com）"}
        except Exception as exc:  # noqa: BLE001 —— 后台这条路失败就退回公开站
            SESSION.log(f"后台取每金币价失败（改走公开站）：{type(exc).__name__}: {str(exc)[:120]}")
            prices = None

    try:
        if prices is None:
            prices = pricing.fetch_coin_prices(
                aids, cache_path=cache_path, use_cache=not force, meta=meta,
            )
    except pricing.PricingError as exc:
        # 联网失败时，别让用户空手而归：退回上次缓存到的价（并如实说明）
        prices = pricing.load_cached_prices(cache_path, aids)
        if not prices:
            SESSION.log(f"取每金币价失败：{exc}")
            return {"ok": False, "error": str(exc)[:300]}
        meta = {"from_cache": True,
                "fetched_at": None,
                "areas": len(prices),
                "warning": f"联网取价失败（{exc}），下面是上次缓存到的价"}

    from_cache = bool(meta.get("from_cache"))
    age = pricing.coin_cache_age(cache_path)
    settings = SESSION.reprice_settings

    out: list[dict] = []
    for aid, coin in sorted(prices.items(), key=lambda kv: aids.index(kv[0])):
        settings.set_aid_rate(aid, coin.per_coin)
        out.append({
            "aid": aid,
            "area": coin.area,
            "per_coin": str(coin.per_coin),
            "unit_price_per_1k": str(coin.unit_price_per_1k),
            "price_per_100k": str(coin.price_per_100k),
        })

    # 覆盖手改值（可选）：先把**当前拉到的这些产品**的逐产品 rate 清掉。
    # ⚠️ 必须在下面那个刷新循环**之前**做 —— 那个循环靠 own_rate() 判断"要不要跳过"，
    #    不清掉的话它照样跳过，用户会觉得"点了确定还是没反应"。
    # 只针对 `SESSION.goods_rows` 里的产品（= 用户眼前这批），不去动别处存着的值。
    # 具体逻辑在 repricer.clear_own_rates（纯函数，已离线钉住）。
    cleared: list[str] = []
    if overwrite_own:
        cleared = repricer.clear_own_rates(settings, SESSION.goods_rows)

    settings.save()

    # 顺手把内存里已经拉到的行也更新一遍（逐产品手改过的不动 —— 除非用户选了覆盖）
    touched = 0
    overwritten = 0
    for row in SESSION.goods_rows:
        if row.aid is None:
            continue
        if not overwrite_own and settings.own_rate(model_id=row.model_id,
                                                  title=row.title) is not None:
            continue                      # 手改过，别覆盖
        coin = prices.get(int(row.aid))
        if coin is not None:
            if row.rate_own:
                overwritten += 1          # 这些原本是"单独设过"的，这次被盖掉了
            row.rate = coin.per_coin
            row.rate_own = False
            row.rate_auto = False
            touched += 1

    for item in out:
        SESSION.log(f"MMOEXP {item['area']}：每金币价 {item['per_coin']}"
                    f"（每 1K ${item['unit_price_per_1k']}）")
    if cleared:
        head = "、".join(cleared[:6]) + (f" 等 {len(cleared)} 个" if len(cleared) > 6 else "")
        SESSION.log(f"已覆盖逐行手改的每金币价：{len(cleared)} 个产品（{head}）"
                    f"—— 它们回到「按区服默认值」")
    src = ("缓存（%.0f 分钟前取的）" % (age / 60)) if (from_cache and age) else \
          "缓存" if from_cache else "刚联网取回"
    # ⚠️ 别写嵌套 f-string（f"{f"...}""）—— 服务器是 Python 3.9，不认 3.12 的
    #    PEP 701 同引号嵌套；先算好再拼接。
    overwritten_note = (f"，覆盖了 {overwritten} 行原本单独设过的"
                        if overwritten else "")
    SESSION.log(f"已带出 {len(out)} 个区服的每金币价（来源：{src}），"
                f"其中 {touched} 行用上了默认值" + overwritten_note)
    res = {"ok": True, "rates": out, "applied": touched,
           "overwritten": overwritten, "cleared": cleared,
           "overwrite_own": overwrite_own,
           "from_cache": from_cache,
           "age_seconds": int(age) if age is not None else None,
           "source": src}
    if meta.get("warning"):
        res["warning"] = str(meta["warning"])
    return res


def do_sites() -> dict:
    """返回站点列表，供界面下拉选择。"""

    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台"}
    page_data = SESSION.client.list_goods(gid=ac.GID_FC27, page=1, limit=1)
    sites = [
        {"id": int(x.get("id") or 0),
         "name": str(x.get("full_title") or x.get("title") or "")}
        for x in page_data.site_config
    ]
    areas = [
        {"aid": int(x.get("id") or 0), "name": str(x.get("title") or "")}
        for x in page_data.game_area_config
    ]
    sites.sort(key=lambda s: (s["id"] != repricer.SITE_ALL, s["name"]))
    SESSION.log(f"站点 {len(sites)} 个，游戏区 {len(areas)} 个")
    return {"ok": True, "sites": sites, "areas": areas}


def do_goods_list(body: dict) -> dict:
    """拉取在售商品，供界面显示各区服现价。

    默认：类目 SBC(9625)+Packs(9629)、站点 0 ALL、**只保留状态亮的行**。
    ``kind`` 可缩小到单个类目；``site`` 可切换站点（``all`` = 全部站点，会很慢且"重复"）。
    ``mid`` 用于只看某一个模型（不受 cid/site 限制）。
    """

    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台，无法读取在售商品"}

    only_live = bool(body.get("only_live", True))

    mid = body.get("mid")
    if mid not in (None, "", 0, "0"):
        try:
            mid_int = int(mid)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"mid 不是整数：{mid!r}"}
        site = body.get("site")
        try:
            site_id = None if str(site).lower() == "all" else (
                int(site) if site not in (None, "") else repricer.SITE_ALL)
        except (TypeError, ValueError):
            site_id = repricer.SITE_ALL
        raws = _paged_goods(gid=ac.GID_FC27, mid=mid_int, site_id=site_id)
        # 这条路不按 cid 收口（是"只看某个模型"），但一样要认得新叶子：
        # 不然从这条路看进来的新叶子行会按"类目未知"算 —— SBC 静默少收手续费、
        # Packs 的「类目」列显示空。两个父类目都要问（见 _online_leaf_kinds）。
        _leaves_now, extra_kinds = _online_leaf_kinds(repricer.TARGET_CIDS)
        rows = _build_rows(raws, extra_leaf_kinds=extra_kinds)
        if only_live:
            rows, dead = repricer.split_live(rows)
            if dead:
                SESSION.log(f"  已隐藏 {len(dead)} 条状态未亮的行"
                            f"（{repricer.summarize_titles(dead)}）")
        SESSION.goods_rows = rows
        SESSION.log(f"模型 {mid_int} 在售行 {len(rows)} 条（site={site_id}）")
        return {"ok": True, "rows": [r.to_dict() for r in rows],
                "count": len(rows), "scope": "single"}

    kind = str(body.get("kind") or "all").strip().lower()
    # ⚠️ 这里传的是**父类目**：后端查询会把子孙一起带回来（行里带的是叶子的 cid）。
    #    所以 `pack` 只传 9629 就够了，10255 的行照样会回来 —— 关键是
    #    `_goods_audit` 的收口必须认那些叶子（2026-10-13 之前它不认，于是被丢掉）。
    if kind in ("sbc", "9625"):
        cids = (repricer.CID_SBC,)
    elif kind in ("pack", "packs", "9629"):
        cids = (repricer.CID_PACKS,)
    else:
        cids = repricer.TARGET_CIDS

    raw_site = body.get("site")
    if str(raw_site).strip().lower() == "all":
        site_id: Optional[int] = None
    elif raw_site in (None, ""):
        site_id = repricer.SITE_ALL
    else:
        try:
            site_id = int(raw_site)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"site 不是整数：{raw_site!r}"}

    label = "全部站点" if site_id is None else f"site_id={site_id}"
    SESSION.log(f"拉取后台在售商品，类目 cid={list(cids)}，站点 {label}")
    rows = _goods_audit(cids=cids, site_id=site_id, only_live=only_live)
    return {"ok": True, "rows": rows, "count": len(rows),
            "scope": "all", "cids": list(cids), "site_id": site_id}


def do_save_settings(body: dict) -> dict:
    """保存金币数、每金币价、手续费与加成（按模型 / 标题）。"""

    settings = SESSION.reprice_settings
    if "markup" in body:
        markup = _dec(body.get("markup"), "1.1")
        if markup <= 0:
            return {"ok": False, "error": "加成必须大于 0"}
        settings.set_markup(markup)

    # 手续费：分两层（2026-09-29 起）
    #   ① 这里这个顶层的 fee = **全局**值，所有没被单独设过的 SBC 都用它；
    #   ② items 里每条自己的 fee = **逐产品覆盖**，优先级高于全局（见下面的循环）。
    # 只有 SBC 会真的加上（Packs 恒为 0）。
    # 注意这里**不**用 _dec(value, "0.24")：那样填成 "abc" 会被静默变成 0.24，
    # 等于悄悄改了一个定价常量。宁可报错也不要静默取默认值。
    if "fee" in body:
        raw_fee = body.get("fee")
        if raw_fee in (None, ""):
            fee = repricer.DEFAULT_FEE          # 框里清空 = 回落默认 0.24
        else:
            try:
                fee = Decimal(str(raw_fee).strip())
            except (InvalidOperation, TypeError, ValueError):
                return {"ok": False, "error": f"手续费不是数字：{raw_fee!r}"}
            if fee < 0:
                return {"ok": False, "error": f"手续费不能为负：{fee}"}
        settings.set_fee(fee)

    # 可选：把按区服的默认每金币价也存一遍（界面上的区服回显用）
    # 这里是**容错**口径（脏值当"没填"，不报错）—— aid_rates 只是回显用。
    # 注意别用 _dec(value)：它的 default 是必填参数，漏传会 TypeError → 整个保存 500。
    aid_rates = body.get("aid_rates")
    if isinstance(aid_rates, Mapping):
        for aid, value in aid_rates.items():
            try:
                text = str(value).strip()
                rate = Decimal(text) if text else None
            except (InvalidOperation, TypeError, ValueError):
                rate = None
            if rate is not None and rate <= 0:
                rate = None
            try:
                settings.set_aid_rate(int(aid), rate)
            except (TypeError, ValueError):
                continue

    items = body.get("items") or []
    if not isinstance(items, list):
        return {"ok": False, "error": "items 必须是数组"}
    saved = 0
    fee_rows = 0
    # 逐行加成覆盖真正写了几条。与 fee_rows 同理：只数前端明确发过来的（= 被单独设过的）。
    markup_rows = 0
    # 逐产品每金币价真正写了几条。以前这个数恒等于 len(items)（前端无条件全发率），
    # 所以日志里的「N 条（金币数 + 每金币价）」看着没毛病 —— 但那正是"把自动带出的
    # 区服默认价一起冻成手改值"的根源（见 rpSaveSettings 的长注释）。
    # 现在前端只发被单独设过的行，这里就得如实分开数，否则日志会骗人。
    rate_rows = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = item.get("model_id")
        try:
            mid_int = int(mid) if mid not in (None, "") else None
        except (TypeError, ValueError):
            mid_int = None
        title = str(item.get("title") or "")

        # ⚠️ 「字段不在」和「字段是空串」必须分开：
        #   不在  -> 这次不动它（支持部分更新）
        #   空串  -> 用户清空了框，按"清掉"处理
        # 老代码用 item.get("coins")，两种情况都变成 None，于是只传 rate 的
        # 部分更新会把金币数一起删掉（实测踩到过）。
        if "coins" in item:
            raw_coins = item["coins"]
            coins: int | None
            if raw_coins in (None, ""):
                coins = None               # 清空 = 不复用这条金币数
            else:
                try:
                    coins = int(float(str(raw_coins)))
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"金币数不是数字：{raw_coins!r}"}
                if coins < 0:
                    return {"ok": False, "error": f"金币数不能为负：{coins}"}
            settings.set_coins(model_id=mid_int, title=title, coins=coins)

        # 逐产品每金币价：**严格**口径，和上面的 fee 一样。
        # ⚠️ 这里原来写的是 `rate = _dec(raw_rate)` —— 但 _dec 的 default 是必填的，
        # 于是「保存」按钮只要表格里有行就必然 TypeError → 500，
        # 逐产品手改价从来没真正存进去过。
        if "rate" in item:
            raw_rate = item["rate"]
            rate: Decimal | None
            if raw_rate in (None, ""):
                rate = None                # 清空 = 回落到按区服默认
            else:
                try:
                    rate = Decimal(str(raw_rate).strip())
                except (InvalidOperation, TypeError, ValueError):
                    return {"ok": False, "error": f"每金币价不是数字：{raw_rate!r}"}
                if rate <= 0:
                    return {"ok": False, "error": f"每金币价必须大于 0：{rate}"}
            settings.set_rate(model_id=mid_int, title=title, rate=rate)
            rate_rows += 1

        # 逐产品**手续费覆盖**（表格里「手续费」列手改走这里）。
        # 口径和上面两个字段完全一致：字段不在 = 不动；空串 = 清掉覆盖（回落全局）。
        # ⚠️ 只有前端明确认为「这行被单独设过」时才会带这个字段 —— 否则每点一次保存
        #    都会把所有 SBC 都钉死成当时的全局值，之后再改全局就再也刷不动了。
        if "fee" in item:
            raw_row_fee = item["fee"]
            row_fee: Decimal | None
            if raw_row_fee in (None, ""):
                row_fee = None                 # 清空 = 取消覆盖，回落到全局手续费
            else:
                try:
                    row_fee = Decimal(str(raw_row_fee).strip())
                except (InvalidOperation, TypeError, ValueError):
                    return {"ok": False, "error": f"手续费不是数字：{raw_row_fee!r}"}
                if row_fee < 0:
                    return {"ok": False, "error": f"手续费不能为负：{row_fee}"}
            settings.set_row_fee(model_id=mid_int, title=title, fee=row_fee)
            fee_rows += 1

        # 逐产品**加成覆盖**（表格里「加成」列手改走这里）。
        # 口径与上面三个字段一致：字段不在 = 不动；空串 = 清掉覆盖（回落全局加成）。
        # ⚠️ 同 fee：只有前端明确认为「这行被单独设过」时才会带这个字段，
        #    否则每点一次保存都会把所有行钉死成当时的全局加成。
        # ⚠️ 与 fee 的差别：这里**拒绝 0 和负数** —— 加成 0 会让目标价变 0（白送），
        #    不是谁的本意；要"不加成"填 1。
        if "markup" in item:
            raw_row_markup = item["markup"]
            row_markup: Decimal | None
            if raw_row_markup in (None, ""):
                row_markup = None                  # 清空 = 取消覆盖，回落到全局加成
            else:
                try:
                    row_markup = Decimal(str(raw_row_markup).strip())
                except (InvalidOperation, TypeError, ValueError):
                    return {"ok": False, "error": f"加成不是数字：{raw_row_markup!r}"}
                if row_markup <= 0:
                    return {"ok": False, "error": f"加成必须大于 0（不加成请填 1）：{row_markup}"}
            settings.set_row_markup(model_id=mid_int, title=title, markup=row_markup)
            markup_rows += 1
        saved += 1

    settings.save()
    SESSION.log(f"已保存改价设置：{saved} 条金币数，"
                f"逐产品每金币价 {rate_rows} 条（只算被单独设过的），"
                f"逐行手续费覆盖 {fee_rows} 条，"
                f"逐行加成覆盖 {markup_rows} 条，"
                f"全局加成 {settings.markup}，全局 SBC 手续费 {settings.fee}（Packs 不计）")
    return {"ok": True, "saved": saved, "rate_rows": rate_rows, "fee_rows": fee_rows,
            "markup_rows": markup_rows,
            "markup": str(settings.markup), "fee": str(settings.fee)}


# 改价（以及配套的读接口）需要的权限节点。
#
# ⚠️ 为什么要把这件事显式做出来：2026-09-28 用户报「改价 27 行全失败」，
#    连着两轮都以为是"忘了勾权限"。其实后台规则表里「产品管理」下**没有**
#    `singleedit` 这个节点 —— 后台操作日志把这个动作的规则标题记成
#    「产品管理-Unknown(singleedit)」，而同页面的 edit / excel / fetchGoodsOcr
#    都有正经标题、「产品模型管理-单值编辑」也有。也就是说权限管理里**很可能
#    根本勾不到它**，只有 super 账号能过。所以工具必须能自己把这件事说清楚，
#    而不是给一句"去勾一下就好"。
REQUIRED_RULES: tuple[tuple[str, str, str], ...] = (
    # ⚠️ 2026-09-28 更正：改价用的是 goods.Goods/edit，不是 goods.Goods/singleEdit。
    #    singleEdit 在产品管理页只用于「推荐/启用/禁用/自动下架/SKU/属性」，不含 price；
    #    而且后台规则表里根本没建这个节点（日志记成「产品管理-Unknown(singleedit)」），
    #    非 super 账号打它恒 401 —— 之前把这个 401 当成了"你没有改价权限"，是误诊。
    #    详见 admin_client.GOODS 常量上方的长注释。
    ("goods/goods/edit", "改价（写「每个价格」）",
     "后台 → 权限管理 → 你的角色 → 产品管理 → 编辑"),
    ("goods/goods/index", "读取在售商品列表",
     "后台 → 权限管理 → 你的角色 → 产品管理 → 列表"),
)


def do_permcheck(body: dict) -> dict:
    """只读自检：当前账号的角色里有没有改价要用的权限节点。

    ``GET /admin/index/index`` 会返回 ``data.adminInfo``（含 ``super`` 标志）+ ``data.menus``
    （这个角色实际被授予的规则树），所以不用试探写端点就能回答"我到底缺什么"。
    """

    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台，无法自检权限"}

    info = SESSION.client.whoami()
    rules = info.get("rules") or frozenset()
    is_super = bool(info.get("super"))

    checks = []
    for rule, what, where in REQUIRED_RULES:
        # super 账号不受规则表限制（BuildAdmin 对 super 直接放行）
        has = True if is_super else (rule in rules)
        checks.append({"rule": rule, "what": what, "where": where, "has": has,
                       "why": "super 账号，不受规则表限制" if (is_super and rule not in rules) else ""})

    missing = [c for c in checks if not c["has"]]
    can = not missing

    if can:
        msg = f"✅ 改价权限齐全（账号 {info.get('username')}）"
    else:
        msg = (f"⛔ 账号 {info.get('username')} 缺改价权限："
               + "、".join(c["rule"] for c in missing))

    SESSION.log(f"权限自检：{msg}")
    # 规则名集合不往前端发（没意义且很长），只回结论
    return {
        "ok": True,
        "username": info.get("username"),
        "nickname": info.get("nickname"),
        "id": info.get("id"),
        "super": is_super,
        "rule_count": len(rules),
        "checks": checks,
        "missing": missing,
        "can_reprice": can,
        "message": msg,
    }


def do_reprice(body: dict) -> dict:
    """按区改价。

    只改「亮的」行（``live``），且必须显式给出目标价 —— 不做"全表扫"。
    """

    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台，拒绝改价"}

    settings = SESSION.reprice_settings
    markup = _dec(body.get("markup"), str(settings.markup))
    if markup <= 0:
        return {"ok": False, "error": "加成必须大于 0"}

    # 手续费：和 /api/settings/save 同一个口径 —— 乱填就报错，不静默降级成旧值。
    # 原来这行写在下面的逐行循环里、且用 _dec(..., 当前值)，填错会被悄悄换掉。
    #
    # ⚠️ 这里解析出来的是**全局**值。逐产品设过覆盖的那些行**不**用它 ——
    #    见下面循环里的 use_fee。这条只在前端没传具体目标价、要后端自己算时才走。
    raw_fee = body.get("fee")
    if raw_fee in (None, ""):
        fee = settings.fee
    else:
        try:
            fee = Decimal(str(raw_fee).strip())
        except (InvalidOperation, TypeError, ValueError):
            return {"ok": False, "error": f"手续费不是数字：{raw_fee!r}"}
        if fee < 0:
            return {"ok": False, "error": f"手续费不能为负：{fee}"}

    items = body.get("items")
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "没有要改价的行"}

    by_id = {r.goods_id: r for r in SESSION.goods_rows}
    # 允许前端直接传目标价；否则按 (金币 × 每金币价) × 加成 算
    plan: list[tuple[int, Decimal, str, bool]] = []
    skipped: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            gid_row = int(item.get("goods_id"))
        except (TypeError, ValueError):
            skipped.append(f"goods_id 非法：{item.get('goods_id')!r}")
            continue
        row = by_id.get(gid_row)
        if row is None:
            skipped.append(f"行 {gid_row} 不在本次拉取结果里，跳过")
            continue
        if not row.live:
            skipped.append(f"{row.title} / {row.area}：状态未亮，按要求跳过")
            continue

        raw_price = item.get("price")
        if raw_price not in (None, ""):
            try:
                target = Decimal(str(raw_price)).quantize(Decimal("0.01"))
            except Exception:  # noqa: BLE001
                skipped.append(f"行 {gid_row} 目标价非法：{raw_price!r}")
                continue
        else:
            coins = item.get("coins")
            if coins in (None, ""):
                coins = settings.coins_for(model_id=row.model_id, title=row.title)
            try:
                coins_int = int(float(str(coins))) if coins not in (None, "") else None
            except (TypeError, ValueError):
                coins_int = None
            if coins_int is None:
                skipped.append(f"{row.title} / {row.area}：没有金币数，跳过")
                continue
            per_coin = row.rate
            if per_coin is None:
                per_coin = settings.rate_for(model_id=row.model_id, title=row.title,
                                            aid=row.aid)
            if per_coin is None:
                skipped.append(f"{row.title} / {row.area}：没有每金币价，跳过"
                               f"（先在界面上「按 MMOEXP 带出」或手填）")
                continue
            # 手续费按类目 + 按行：
            #   · 类目不是 SBC -> 压根不加（Packs / 未知都恒为 0）
            #   · 这行被**单独设过**手续费 -> 用它自己的（row.fee 就是解析好的覆盖值）
            #   · 否则 -> 用本次传进来的全局值
            # 不加区分的话，表格里明明显示 0.30 的行，后端会按全局 0.24 算，
            # 你确认的价和提交的价就是两个数。
            if repricer.fee_applies(row.kind):
                use_fee = row.fee if row.fee_own else fee
            else:
                use_fee = None
            # 加成同理（2026-10-06 起逐行可覆盖）：
            #   · 这行被**单独设过**加成 -> 用它自己的（row.markup 是解析好的覆盖值）
            #   · 否则 -> 用本次传进来的全局值（用户可能刚在顶部框改过，比行上的新）
            # 不加区分的话，表格里显示 1.5 的行后端会按全局 1.3 算，
            # 你确认的价和提交的价就是两个数 —— 和 fee 那个坑一模一样。
            use_markup = row.markup if row.markup_own else markup
            target = repricer.compute_target(
                coins_int, per_coin, markup=use_markup, fee=use_fee,
            )
            if target is None:
                skipped.append(f"{row.title} / {row.area}：目标价算不出来，跳过")
                continue

        # 跳过条件有两个：
        #   ① 目标价没变；② 行是干净的（折扣=100，此时单价==每个价格）。
        # 折扣歪了的行（早先把目标价写进「单价」被后端反算出来的 87.05/147.74）
        # 即使价格没变也要重写一遍 —— 顺手把折扣归 100，把三件套摆正。
        need_discount_fix = row.discount != 100
        if not need_discount_fix and row.price is not None and target == row.price:
            skipped.append(f"{row.title} / {row.area}：价格未变（{row.price}），跳过")
            continue
        plan.append((gid_row, target, f"{row.title} / {row.area}", need_discount_fix))

    if not plan:
        SESSION.log("没有需要改价的行")
        return {"ok": True, "changed": 0, "skipped": skipped, "detail": []}

    detail: list[dict] = []
    changed = 0
    # 「权限不够」是**整体性**失败（不是某一行的数据问题），而且重试与改参数都没用
    # —— 实测 27 行会一模一样地失败 27 次，把后端白打一遍。
    # 所以第一次撞上就立刻停下，只报一次，并把还没试过的行如实标出来。
    blocked: str | None = None
    for gid_row, target, label, need_discount_fix in plan:
        if blocked:
            detail.append({"goods_id": gid_row, "label": label, "price": str(target),
                           "ok": False, "error": "未尝试（前一行已被后台拒绝，已整体中止）"})
            continue
        try:
            # ⚠️ 写「每个价格(unit_price)」，不是「单价(price)」——
            #    写单价会被后端反算折扣（87.05/147.74 那批就是 这么来的）。
            #    折扣歪的行先发一发把它归 100（顺序不能反，见 admin_client 注释）。
            env = SESSION.client.edit_goods_price(
                gid_row, unit_price=str(target),
                discount=("100" if need_discount_fix else None),
            )
        except ac.AdminPermissionError as exc:
            blocked = str(exc)
            SESSION.log(f"改价整体中止（权限不足）：{blocked}")
            detail.append({"goods_id": gid_row, "label": label, "price": str(target),
                           "ok": False, "error": blocked})
            continue
        except Exception as exc:  # noqa: BLE001
            SESSION.log(f"改价失败 {label}：{exc}")
            detail.append({"goods_id": gid_row, "label": label, "price": str(target),
                           "ok": False, "error": str(exc)[:200]})
            continue
        code = env.get("code")
        msg = str(env.get("msg") or "")
        # ⚠️ `edit_goods_price` 走的是 `admin_client._json()`，而 `_json()` **只会在
        #    code ∈ {1, "1"} 时正常返回**，其它一律抛异常（302→登录失效、401→权限不足、
        #    其余→契约错误）。也就是说：能走到这一行，就是成功。
        #    早先这里写的是 `{"0", "200", "None"}` —— 把 1 漏了，于是 `ok` 恒为 False，
        #    **改价成功了界面也报「成功 0 / 共 N 行」**，看起来像"改价全失败"。
        #    留着 0/200/None 是为了容忍以后换成别的客户端实现时口径不同。
        ok = code is None or str(code) in {"0", "1", "200", "None"}
        SESSION.log(f"{'改价成功' if ok else '改价被拒'} {label} -> {target}（code={code} {msg}）")
        detail.append({"goods_id": gid_row, "label": label, "price": str(target),
                       "ok": ok, "code": code, "msg": msg[:160]})
        if ok:
            changed += 1

    out = {"ok": all(item["ok"] for item in detail), "changed": changed, "total": len(plan),
           "skipped": skipped, "detail": detail}
    if blocked:
        out["blocked"] = blocked
        out["error"] = f"后台拒绝了改价操作：{blocked}"
    return out


def do_fetch(body: dict) -> dict:
    """① 开始采集 SBC —— 2026-10-15 起源站换成 **FUT.GG**（用户指定）。

    * 全种类都采（Players / Upgrades / Challenges / Foundations），**唯一闸门 =
      金币价 > min_coins**（用户口径），futbin 时代的 Completed / Item Score /
      只看新上架闸门随源一起退役（后端参数仅保留兼容）。
    * 链接带 ``/sbc/players/`` 的归 10203 SBC Players，其余归 9971 Upgrade。
    * 图 / 名字 / 金币价全部取 fut.gg；同表同步对齐（下架删、在架刷、旧 futbin
      行按标题收编）。
    """
    target = _workbook_path(body.get("path") or DEFAULT_XLSX)
    stats: dict = {}
    sync: dict = {}
    path, added = fetch_futgg.run_fetch_sbc(
        target,
        history_path=HISTORY_PATH,
        min_coins=int(body.get("min_coins") or fetch_futgg.MIN_COINS_DEFAULT),
        fill_text=bool(body.get("fill_text", False)),
        append=bool(body.get("append", True)),
        sync_live=_truthy(body.get("sync_live", True)),
        futbin_map_path=OUTPUT_DIR / "futbin_id_map.json",
        # set_id 的主源：SBC 数据站（2026-10-17；数据站不是实时更新，采集时会先点它的「采集 SBC」）
        index_map_path=OUTPUT_DIR / "sbc_index.json",
        log=SESSION.log,
        stats=stats,
        sync_out=sync,
    )
    SESSION.log(f"采集完成：{path}（新增 {added} 行）")
    result = do_reload({"path": str(path)})
    result["added"] = added
    # 图标地址被同步换过的行 → 清掉本机旧缓存图，保证上架/缩略图用的是**采集站的新图**
    # （不然 find_local_icon 会拿 stem 相同的旧缓存文件，新图永远下不下来）
    _discard_icons_for_migrated((sync.get("refreshed") or []))
    # 「每道闸各挡掉多少」要带回界面 —— 筛选是串联的，只看得到"采到几个"
    # 的话，用户取消了一道闸却发现没效果时无从下手（2026-09-29 的真实困惑）。
    result["stats"] = stats
    # 「和列表对齐」的结果也要带回界面：删了哪些行、收编了哪些行 ——
    # 自动删行不告诉用户才是最糟的（他会以为工具偷偷弄丢了他的数据）。
    result["sync"] = sync
    return result


def do_fetch_packs(body: dict) -> dict:
    """①b 采集 Packs —— 源站 FUTGenie（用户 2026-10-15 指定）。

    只收列表页**右上角有倒计时**的 pack，进详情页拿全名 + 精确金币价；
    行进同一张导入表（sbc_id 前缀 ``fg``），cid = 10255 In-Game Packs。
    """
    target = _workbook_path(body.get("path") or DEFAULT_XLSX)
    stats: dict = {}
    sync: dict = {}
    path, added = fetch_futgg.run_fetch_packs(
        target,
        history_path=HISTORY_PATH,
        fill_text=bool(body.get("fill_text", False)),
        append=bool(body.get("append", True)),
        sync_live=_truthy(body.get("sync_live", True)),
        log=SESSION.log,
        stats=stats,
        sync_out=sync,
    )
    SESSION.log(f"Packs 采集完成：{path}（新增 {added} 行）")
    result = do_reload({"path": str(path)})
    result["added"] = added
    _discard_icons_for_migrated((sync.get("refreshed") or []))
    result["stats"] = stats
    result["sync"] = sync
    return result


# ---- 自动下架（2026-10-15 用户口径） ----


def _all_models(cid: int) -> list[dict]:
    """拉全某个（父）类目下的产品模型；**没拉全直接抛错** —— 拉不完整绝不许删任何东西。"""

    rows: list[dict] = []
    total: Optional[int] = None
    page = 1
    while True:
        data = SESSION.client.list_models(gid=ac.GID_FC27, cid=cid, page=page, limit=200)
        if total is None:
            total = data.total
        rows.extend(data.rows)
        if not data.rows or (total is not None and len(rows) >= total):
            break
        page += 1
        if page > 100:
            break
    if total is not None and len(rows) < total:
        raise RuntimeError(
            f"类目 {cid} 的模型列表没拉全（{len(rows)}/{total}），为安全起见拒绝执行下架")
    return rows


def do_delist(body: dict) -> dict:
    """自动下架：本轮**采集到的** SBC+Packs 与后台在架模型比对，没采到的（过期）下架。

    下架方式 = 用户指定：产品模型管理（goodsMould）游戏 1327、类目 9625 SBC / 9629
    packs 的「状态」开关点灭。程序化等价物是 ``edit_model_status(mid, 0)``
    （单字段快路径，见 admin_client.edit_model_status）。

    ``body["dry_run"]=true``：**只看不动** —— 把「会被下架 / 会被保留」的名单列出来，
    一个字节都不写后台（2026-10-15 加的：上线前先看影响面，别拿正式商品试刀）。

    护栏：
    * 只比**标题**；导入表里**任何一行**（含手工行）的标题都算「还在产」——
      手工行不是采集来的，不该被「没采到」误杀。
    * 后台模型行没带 ``status`` 字段 → 一个都不敢动（判不了亮灭）。
    * 已经是灭的模型跳过（重复发 0 无害但没意义）。
    * 每个下架写完回读核对；回读失败只记警告，不回滚（写已发生，如实报告）。
    """

    dry_run = _truthy(body.get("dry_run", False))
    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台，拒绝下架"}
    receipts = json.loads(DELIST_RECEIPTS.read_text(encoding="utf-8")) if DELIST_RECEIPTS.exists() else []
    if not isinstance(receipts, list) or any(not isinstance(r, dict) or r.get("state") not in ("unknown", "confirmed") for r in receipts):
        raise BadInput("下架回执损坏，停止写入，请先人工核对")
    for receipt in receipts:
        if receipt["state"] == "unknown":
            row = ac.AdminClient.model_row(SESSION.client.get_model(receipt["mid"]))
            if not row or row.get("status") not in (0, "0"):
                return {"ok": False, "state": "unknown", "error": "存在未确认下架，已停止；请核对原模型及回执，不得重复提交"}
            receipt["state"] = "confirmed"
            _save_delist_receipts(receipts)
    if not SESSION.rows:
        do_reload({})
    # 保护名单口径与「跨类目去重」一致（用户口径 B）：**剥掉 (Non-repeatable) 后缀再比** ——
    # 后台 9971 里的 ``X(Non-repeatable)`` 与表里归 10203 的 ``X`` 是同一个 SBC，
    # 必须一起保护；否则上架刚复用了旧模型、下架转头就把它灭掉。
    protected = {uploader.normalize_title(r.title) for r in SESSION.rows if r.title}
    protect_patterns = [uploader.normalize_title(x) for x in
                        (_auto_settings_load().data.get("delist_protect") or [])
                        if str(x).strip()]

    def _is_protected(title: str) -> bool:
        norm = uploader.normalize_title(title)
        if norm in protected:
            return True
        return any(fnmatch.fnmatchcase(norm, pat) for pat in protect_patterns)

    try:
        models = _all_models(ac.CID_SBC) + _all_models(ac.CID_PACKS)
    except RuntimeError as exc:
        # 「列表没拉全」是硬闸 —— 拒绝执行，一个都不许动
        SESSION.log(f"自动下架：{exc}")
        return {"ok": False, "error": str(exc)}
    if not models:
        SESSION.log("自动下架：后台没有返回任何模型，未做任何改动")
        return {"ok": True, "delisted": 0, "kept": 0, "skipped": 0, "details": []}

    status_missing = sum(1 for m in models if m.get("status") in (None, ""))
    if status_missing == len(models):
        return {"ok": False,
                "error": "后台模型列表没有返回 status 字段，判不了亮灭 —— 拒绝下架"}

    details: list[dict] = []
    delisted = kept = skipped = 0
    for model in models:
        mid_raw = model.get("id")
        title = str(model.get("title") or "").strip()
        if not title or mid_raw in (None, "", 0, "0"):
            continue
        try:
            mid = int(mid_raw)
        except (TypeError, ValueError):
            continue
        if _is_protected(title):
            kept += 1
            continue
        if model.get("status") in (None, ""):
            details.append({"mid": mid, "title": title, "ok": False,
                            "state": "unknown", "detail": "缺少状态，已停止后续下架"})
            break
        if int(model.get("status")) != 1:
            skipped += 1          # 本来就是灭的
            continue
        if dry_run:
            delisted += 1
            details.append({"mid": mid, "title": title, "ok": True,
                            "detail": "预览：将会下架（未写入）"})
            continue
        try:
            receipt = {"mid": mid, "title": title, "state": "unknown",
                       "operation_id": str(time.time_ns())}
            receipts.append(receipt)
            _save_delist_receipts(receipts)
            SESSION.client.edit_model_status(mid, 0)
        except Exception as exc:  # noqa: BLE001 —— 单个失败不拖垮整批
            details.append({"mid": mid, "title": title, "ok": False,
                            "state": "unknown", "detail": f"{type(exc).__name__}: {exc}"})
            SESSION.log(f"自动下架｜{title}（模型 {mid}）写状态失败：{exc}")
            break
        note = ""
        try:
            # ⚠️ 回读也走 data.row（顶层没有 status，照顶层读永远核对不到东西）
            row_after = ac.AdminClient.model_row(SESSION.client.get_model(mid))
            after_status = (row_after or {}).get("status")
            if row_after is None:
                note = "（回读响应里没有 data.row，未能核对）"
            elif after_status not in (0, "0"):
                note = f"⚠️ 回读 status={after_status!r}，请人工核对"
        except Exception as exc:  # noqa: BLE001
            note = f"（回读失败：{exc}）"
        if note:
            details.append({"mid": mid, "title": title, "ok": False,
                            "state": "unknown", "detail": note})
            SESSION.log(f"自动下架｜{title}（模型 {mid}）结果未确认，停止后续下架{note}")
            break
        receipt["state"] = "confirmed"
        _save_delist_receipts(receipts)
        delisted += 1
        details.append({"mid": mid, "title": title, "ok": True, "detail": note or "已下架"})
        SESSION.log(f"自动下架｜{title}（模型 {mid}）已把状态点灭{note}")

    if dry_run:
        SESSION.log(f"自动下架【预览】：后台模型 {len(models)} 个，将会下架 {delisted}、"
                    f"在产保留 {kept}、原本就是灭的 {skipped}（未写入后台）")
        return {"ok": all(item["ok"] for item in details), "dry_run": True, "delisted": delisted, "kept": kept,
                "skipped": skipped, "total": len(models), "details": details}
    SESSION.log(f"自动下架完成：后台模型 {len(models)} 个，下架 {delisted}、"
                f"在产保留 {kept}、原本就是灭的 {skipped}")
    return {"ok": all(item["ok"] for item in details), "delisted": delisted, "kept": kept, "skipped": skipped,
            "total": len(models), "details": details}


def _save_delist_receipts(receipts) -> None:
    DELIST_RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".delist-receipts-", dir=str(DELIST_RECEIPTS.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipts, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, DELIST_RECEIPTS)
        if os.name == "posix":
            directory = os.open(str(DELIST_RECEIPTS.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


# ---- 列表编辑（勾选 / 删除 / 改标题 / 换图 / 保存） ----


def _discard_icons_for_migrated(refreshed: list) -> int:
    """同步把图标地址换过的行 → 清本机旧缓存图（2026-10-15 用户口径：
    采集行一律用采集站的图；不清的话 find_local_icon 会拿 stem 相同的旧缓存）。

    ``refreshed`` 是 sync 返回的 ``[(标题, [改了哪些字段])]``，只处理带
    ``icon_url`` 的行。尽力而为，失败不拖垮采集。"""
    titles = {t for t, fields in refreshed if "icon_url" in (fields or [])}
    if not titles:
        return 0
    n = 0
    for row in SESSION.rows:
        if row.title in titles:
            try:
                _discard_local_icon(row)
                n += 1
            except Exception:  # noqa: BLE001 —— 尽力而为
                pass
    if n:
        SESSION.log(f"已清掉 {n} 行的本机旧缓存图（图标地址换成了采集站的图，"
                    f"下次上架/缩略图会重新下载）")
    return n


def do_reload(body: dict) -> dict:
    """从导入表重新载入列表，并把本地已有的图片挂回去。会丢弃未保存的改动。"""

    path = _workbook_path(body.get("path") or SESSION.rows_path or DEFAULT_XLSX)
    rows = _load_rows(str(path))
    hits = _uploader().attach_local_icons(rows)
    SESSION.set_rows(rows, path)
    SESSION.log(f"已载入 {path.name}：{len(rows)} 行（其中 {hits} 行命中本地已存图片）")
    return {"ok": True, **_list_state(), "loaded": len(rows), "local_icons": hits}


def do_select(body: dict) -> dict:
    """勾选 / 取消勾选。传 all 表示全选或全不选，否则传 uid + selected。"""

    if body.get("all") is not None:
        value = bool(body.get("all"))
        for row in SESSION.rows:
            row.selected = value
        SESSION.dirty = True
        SESSION.log(f"{'全选' if value else '全不选'}：{len(SESSION.rows)} 行")
        return {"ok": True, **_list_state()}

    row = SESSION.row_by_uid(body.get("uid"))
    if row is None:
        return {"ok": False, "error": "这条记录已不在列表里，请点「重新载入」"}
    row.selected = bool(body.get("selected"))
    SESSION.dirty = True
    return {"ok": True, **_list_state()}


def do_delete(body: dict) -> dict:
    """把某条 SBC 从列表里移除（只动内存列表，点「保存改动」才写回导入表）。"""

    row = SESSION.row_by_uid(body.get("uid"))
    if row is None:
        return {"ok": False, "error": "这条记录已不在列表里，请点「重新载入」"}
    title = row.title
    SESSION.drop(row)
    SESSION.dirty = True
    SESSION.log(f"已从列表移除：{title}（剩余 {len(SESSION.rows)} 行，保存改动后才写回表格）")
    return {"ok": True, **_list_state(), "removed": title}


def do_update(body: dict) -> dict:
    """改产品名称 / 摘要 / 描述 / 图标地址。"""

    row = SESSION.row_by_uid(body.get("uid"))
    if row is None:
        return {"ok": False, "error": "这条记录已不在列表里，请点「重新载入」"}

    title = str(body.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "产品名称不能为空 —— 后台拿它当模型标题，也是去重依据"}

    changed = []
    if title != row.title:
        changed.append(f"名称 {row.title} → {title}")
    row.title = title

    summary = str(body.get("summary") or "").strip()
    if summary != row.summary:
        changed.append("摘要")
    row.summary = summary

    description = str(body.get("description") or "").strip()
    if description != row.description:
        changed.append("描述")
    row.description = description

    icon_url = str(body.get("icon_url") or "").strip()
    if icon_url != row.icon_url:
        # 换了地址就作废本地图，避免拿着旧图去上架
        _discard_local_icon(row)
        row.icon_url = icon_url
        row.icon_path = None
        changed.append("图标地址")

    SESSION.dirty = True
    SESSION.log(f"已更新「{row.title}」：" + ("、".join(changed) if changed else "无变化"))
    return {"ok": True, **_list_state(), "changed": changed}


def _discard_local_icon(row: wb.SbcRow) -> None:
    """作废本地这张图：成品图删掉，原始下载**归档**（不删）。

    为什么原始图也要处理：只删成品图的话，下次 attach_local_icons 会拿旧的
    原始图重新生成一张出来，等于没换。

    为什么是归档而不是删：用户换了图之后想反悔、或者"一键修复图片"要重来，
    都得有原始图兜底 —— 直接删掉就永远找不回来了。归档到 icons_raw/_replaced/。

    ⚠️ 两处都是 `except Exception` 而不是 `except OSError`，这不是偷懒：
    删文件是**尽力而为**（紧接着 `image.save()` 会覆盖同名文件，删不掉也不影响换图，
    只是原始图留在原位）。而"删不掉"在真实机器上远不止 OSError 一种 ——
    杀毒 / EDR / 企业策略代理拦住删除时抛的类型五花八门。
    真踩过（2026-10-03）：本机的删除守卫拦了一下 `unlink()`，异常穿过
    `do_icon_upload`，**整个请求连响应都不回、日志一条没有**，前端只能看到"换图没反应" ——
    正是用户报的那个症状。所以这里必须兜住一切，绝不允许它把请求搞死。
    """

    stem = icon_stem(row)
    for ext in icon_extensions():
        stale = ICON_DIR / f"{stem}{ext}"
        if stale.is_file():
            try:
                stale.unlink()
            except Exception:  # noqa: BLE001 —— 见上面的 ⚠️
                pass

    archive = RAW_ICON_DIR / "_replaced"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for ext in icon_extensions():
        raw = RAW_ICON_DIR / f"{stem}{ext}"
        if not raw.is_file():
            continue
        try:
            archive.mkdir(parents=True, exist_ok=True)
            raw.replace(archive / f"{stem}.{stamp}{ext}")
        except Exception:  # noqa: BLE001 —— 见上面的 ⚠️
            pass


def do_icon_upload(body: dict) -> dict:
    """接收前端 base64 上传的图片，转成 PNG 存进 cache/icons。

    用 base64 走 JSON，而不是 multipart —— 纯标准库解析 multipart 又长又容易出错。
    这是本机回环通信，体积也不大（上限 6MB），没必要上 multipart。
    """

    row = SESSION.row_by_uid(body.get("uid"))
    if row is None:
        return {"ok": False, "error": "这条记录已不在列表里，请点「重新载入」"}

    raw = str(body.get("data") or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    if not raw:
        return {"ok": False, "error": "没有收到图片数据"}
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"图片数据解析失败：{exc}"}
    if not blob:
        return {"ok": False, "error": "图片内容为空"}
    if len(blob) > MAX_ICON_BYTES:
        return {"ok": False, "error": f"图片太大（{len(blob) // 1024}KB），上限 {MAX_ICON_BYTES // 1024 // 1024}MB"}

    try:
        image = Image.open(io.BytesIO(blob))
        image.load()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"这不是有效的图片文件：{exc}"}

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    if max(image.size) > MAX_ICON_PIXELS:
        image.thumbnail((MAX_ICON_PIXELS, MAX_ICON_PIXELS), Image.LANCZOS)

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    target = ICON_DIR / f"{icon_stem(row)}.png"

    # 换图之前先把旧图的字节读出来 —— _discard_local_icon 紧接着就把它删了。
    # 有这个 before，才能回答"为什么我明明换了图，画面上看着没变"：
    # 十有八九是文件选择器把上一次选中的文件又给你选了一遍（内容一模一样）。
    try:
        before = target.read_bytes() if target.is_file() else None
    except OSError:
        before = None

    _discard_local_icon(row)
    try:
        image.save(target, "PNG")
    except OSError as exc:
        return {"ok": False, "error": f"图片保存失败：{exc}"}

    try:
        after = target.read_bytes()
    except OSError:
        after = b""
    same_as_previous = bool(before) and before == after

    source = str(body.get("name") or "").strip()
    row.icon_path = target
    SESSION.dirty = True
    SESSION.log(
        f"已替换「{row.title}」的图片：{target.name}"
        f"（{target.stat().st_size // 1024}KB，{image.size[0]}×{image.size[1]}）"
        + (f"，来源 {source}" if source else "")
        + ("。⚠️ 内容和替换前那张一模一样，画面看着不会变（多半是又选中了同一张图）"
           if same_as_previous else "")
    )
    return {"ok": True, **_list_state(), "name": target.name,
            "size": target.stat().st_size, "width": image.size[0], "height": image.size[1],
            "same_as_previous": same_as_previous}


def do_fix_icons(body: dict) -> dict:
    """把采集下来的原始图重新修复一遍（裁透明边 → 放大 → 去噪/锐化 → 统一画布）。

    读的是 ``cache/icons_raw`` 里的原始下载，所以反复点也不会「修一次糊一次」。

    用户在界面上自己传的图**不在这里处理** —— 那是用户明确给的东西，原样上传。
    替换图片时还会连带清掉原始下载，所以这里也不可能把用户传的图覆盖回去。
    """

    RAW_ICON_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(
        p for p in RAW_ICON_DIR.iterdir() if p.is_file() and p.suffix.lower() in icon_extensions()
    )
    if not raw_files:
        return {"ok": False, "error": "还没有原始图标可修 —— 先在「采集」里拉一次数据（会自动下载图标）"}

    SESSION.log(f"开始修复 {len(raw_files)} 张原始图标（目标长边 {iconfix.TARGET_EDGE}px）……")
    done = _uploader().fix_all_icons(overwrite=True)

    # 修好的图挂回列表，否则界面缩略图还在用旧文件（URL 带 icon_rev，mtime 变了会自动刷新）
    attached = 0
    for row in SESSION.rows:
        hit = done.get(icon_stem(row))
        if hit and Path(hit).is_file():
            row.icon_path = Path(hit)
            attached += 1

    failed = len(raw_files) - len(done)
    SESSION.log(f"图标修复完成：成功 {len(done)} 张" + (f"，失败 {failed} 张" if failed else ""))
    return {
        "ok": True,
        **_list_state(),
        "fixed": len(done),
        "failed": failed,
        "attached": attached,
    }


# ---------------------------------------------------------------- ⑤ 后台商品图水印
#
# ⚠️ 和 ④ 那套**不是一回事**，别再合并：
#    ④ 是「本地待上架的图，上传前先加印」—— 影响的是**还没进后台**的图；
#    ⑤ 是「把已经在架上的商品图抓下来、加印、写回模型」—— 影响的是**前台正在卖的那些图**。
# 用户 2026-10-10 明确要求水印入口放 ⑤，所以 ④ 里那套开关 / 按钮已经撤掉，
# 但 watermark.py（水印样式本身）两边共用。


def _clean_mids(raw: Any) -> list[int]:
    """校验并去重模型 id 列表。

    **去重是有意的**：模型图全站点共用，同一模型的 3 个区服行在 ⑤ 里是 3 行，
    前端把 3 行都勾上会送来 3 个相同的 mid —— 不去重就会把同一张图加印 3 次、
    往后台写 3 次。
    """

    if not isinstance(raw, (list, tuple)):
        raise BadInput("mids 必须是数组")
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            mid = int(item)
        except (TypeError, ValueError):
            raise BadInput(f"模型 id 不是整数：{item!r}") from None
        if mid <= 0:
            raise BadInput(f"模型 id 必须是正整数：{mid}")
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    if len(out) > MAX_WATERMARK_MODELS:
        raise BadInput(f"一次最多处理 {MAX_WATERMARK_MODELS} 个模型，收到 {len(out)} 个 —— 请分批做")
    return out


def _fetch_remote_image(url: str) -> bytes:
    """下载一张后台商品图。b2c-static 是公开 CDN，不需要登录态。"""

    text = str(url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        raise ac.AdminContractError(f"图标地址不是 http(s) URL：{text!r}")
    req = urllib.request.Request(text, headers={"User-Agent": IMAGE_UA})
    with urllib.request.urlopen(req, timeout=60.0) as response:
        return response.read()


def _model_icon_info(mid: int) -> dict:
    """读一个模型当前的图：地址、附件 id，以及"本工具加过印没有"。

    ⚠️ **真实数据在 ``data.row``**（2026-10-15 实测）：``GET GoodsMould/edit`` 的
    顶层只有 ``code/data/msg/time`` —— 照顶层读 ``_format`` / ``icon`` 拿到的是空，
    于是水印**每一个模型都被判成"没有图标"而静默跳过**
    （用户报「新上架的 sbc 和 pack 水印没加」的真因就是这个）。
    """

    model = SESSION.client.get_model(mid)
    row = ac.AdminClient.model_row(model) or model
    fmt = row.get("_format")
    url = str(fmt.get("icon_format") or "") if isinstance(fmt, Mapping) else ""
    ext = row.get("_extend")
    own = str(ext.get("open_watermark") or "0") if isinstance(ext, Mapping) else "0"
    try:
        icon = int(row.get("icon") or 0)
    except (TypeError, ValueError):
        icon = 0
    rec = watermark_record_of(mid)
    return {
        "mid": mid,
        "icon": icon,
        "url": url,
        "title": str(row.get("title") or ""),
        "cid": row.get("cid"),
        "status": row.get("status"),
        # 后台自带的「图片水印」开关（上架时的一次性参数，见 evidence §3.2/§3.4）。
        # 非 '0' 说明前台那张图可能**已经有一层水印**了 —— 前端据此在确认框里提醒。
        "open_watermark": own,
        # 「本工具加过印」= 台账里记的 icon 恰好就是现在挂的这个。
        # 图被人工换掉后 icon 会变，这个标记自动失效 —— 正是我们要的语义。
        "watermarked": bool(rec) and rec == icon,
    }


def _icon_info_from_model_row(raw: Mapping[str, Any]) -> dict:
    """从**模型列表**的一行里取图信息。

    ⚠️ 列表行带 `icon`（附件 id）和 **`full_url`**（图地址），但**不带** `_format` /
    `_extend` —— 所以这一路拿不到「后台自带的图片水印」开关。要那个得走
    :func:`_model_icon_info`（逐个读详情）。列表这条路是给"一次问一批"用的。
    """

    try:
        mid = int(raw.get("id") or 0)
    except (TypeError, ValueError):
        mid = 0
    try:
        icon = int(raw.get("icon") or 0)
    except (TypeError, ValueError):
        icon = 0
    rec = watermark_record_of(mid)
    return {
        "mid": mid,
        "icon": icon,
        "url": str(raw.get("full_url") or ""),
        "title": str(raw.get("title") or ""),
        "cid": raw.get("cid"),
        "status": raw.get("status"),
        "watermarked": bool(rec) and rec == icon,
    }


def do_model_icons(body: dict) -> dict:
    """只读：批量取模型图信息，给 ⑤ 表格的「图片」列用。

    走的是**模型列表**（`GoodsMould/index`，按 cid 拉 2 次），不是逐个 `edit?id=`：
    列表行自带 `full_url`，一次请求就拿到整批模型的图地址；逐个读详情的话
    45 行就是 45 个请求，会把全局那把闸占住十几秒，用户这时点改价只会拿到 409。
    """

    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台，读不到商品图"}
    mids = _clean_mids(body.get("mids"))
    want = set(mids)
    icons: dict[str, dict] = {}
    for cid in (repricer.CID_SBC, repricer.CID_PACKS):
        page = SESSION.client.list_models(gid=ac.GID_FC27, cid=cid, limit=500)
        for raw in page.rows:
            try:
                mid = int(raw.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if mid in want:
                icons[str(mid)] = _icon_info_from_model_row(raw)
    missing = [m for m in mids if str(m) not in icons]
    SESSION.log(f"读取 {len(mids)} 个模型的现图：命中 {len(icons)} 个"
                + (f"，另有 {len(missing)} 个在 SBC/Packs 模型列表里没找到" if missing else ""))
    return {"ok": True, "icons": icons, "missing": missing}


def _model_cid_map(mids) -> dict[int, int]:
    """只读：把 mid 映射到它所在的**父类目** cid（SBC=9625 / Packs=9629）。

    为什么要单独问一遍：位置是**按类目**分的（用户 2026-10-10 指定
    「packs 的放这，sbc 的放这」，见 ``watermark.Style``），所以每个模型
    得知道自己是哪一类。而详情接口 ``GoodsMould/edit?id=`` 不保证回 ``cid``，
    模型列表（``GoodsMould/index``）的行是**一定带** ``cid`` 的 —— 和
    :func:`do_model_icons` 同一条路，一次批量只多打 2 个请求，
    比起后面逐张下载 + 上传可以忽略。

    查不到 cid 的模型（比如别的类目）就**不在返回的映射里** —— 调用方自己兜底。
    """

    want = {int(m) for m in mids if str(m).strip().lstrip("-").isdigit()}
    out: dict[int, int] = {}
    if not want:
        return out
    for cid in (repricer.CID_SBC, repricer.CID_PACKS):
        page = SESSION.client.list_models(gid=ac.GID_FC27, cid=cid, limit=500)
        for raw in page.rows:
            try:
                mid = int(raw.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if mid in want:
                out[mid] = cid
    return out


def _watermark_style(cid) -> Optional[object]:
    """按类目 cid 选落位口径；认不出来就返回 ``None``（走左上角那套实测比例）。"""

    try:
        key = int(cid)
    except (TypeError, ValueError):
        return None
    return {repricer.CID_SBC: watermark.STYLE_SBC,
            repricer.CID_PACKS: watermark.STYLE_PACKS}.get(key)


def do_watermark_models(body: dict) -> dict:
    """⑤「一键添加水印」：下载勾选行的**后台商品图** → 叠 MMOEXP 水印 → 写回模型。

    链路（每步都是实测过的接口，见 evidence/接口证据.md §3.4）::

        GET  goods.GoodsMould/index            -> 每个模型属于哪个类目（决定水印落哪）
        GET  goods.GoodsMould/edit?id=<mid>    -> _format.icon_format（当前图地址）
        GET  <icon_format>                     -> 原图字节
        （内存里 apply_watermark，**保持原始尺寸**）
        POST b2c-api/upload/file               -> 新附件 id
        POST goods.GoodsMould/edit {id, icon}  -> 换图（只发这一个业务字段）
        GET  goods.GoodsMould/edit?id=<mid>    -> 回读 icon，确认真的写进去了

    三条硬约束：

    1. **按 mid 去重** —— 模型图全站点/全区服共用，勾了同一模型的 3 行只该处理 1 次；
    2. **不套 iconfix** —— 那张图就是"前台要显示的样子"，裁透明边/放大/锐化会改变它的
       构图和尺寸，与"只换水印"这件事无关。水印按**原图尺寸**等比放；
    3. **幂等靠台账** —— 从图里看不出加过印没有，所以用**自己产出的附件 id** 当依据：
       台账里记的 icon 就是当前 icon ⇒ 这张图是本工具上次生成的，跳过。
       跳过是必须的：叠第二层水印不可逆，而且肉眼一眼能看出来。

    ⚠️ **位置按类目分**：SBC 和 Packs 各有一套落位口径（``watermark.STYLE_SBC`` /
    ``STYLE_PACKS``），是用户对参考截图画的红框定的。类目认不出来才退回左上角
    那套官方参考图的实测比例，并在日志里点名，免得悄悄画错地方。
    """

    if not SESSION.logged_in:
        return {"ok": False, "error": "尚未登录后台，不能改商品图"}

    mids = _clean_mids(body.get("mids"))
    if not mids:
        return {"ok": False, "error": "没有勾选任何行 —— 先在表格里勾选要处理的商品"}

    SESSION.log(f"一键添加水印：{len(mids)} 个模型（已按模型去重）")
    # 位置按类目分，所以先问一遍每个模型是哪一类（一次批量只多 2 个请求）。
    cid_map = _model_cid_map(mids)
    unknown_kind = [m for m in mids if m not in cid_map]
    if unknown_kind:
        SESSION.log(f"  ⚠️ 有 {len(unknown_kind)} 个模型没在 SBC / Packs 模型列表里找到"
                    f"（{unknown_kind[:3]}{' …' if len(unknown_kind) > 3 else ''}），"
                    f"这些走默认落位口径")
    results: list[dict] = []
    icons_out: dict[str, dict] = {}

    for mid in mids:
        item: dict[str, Any] = {"mid": mid}
        try:
            # ---- 1) 现图
            info = _model_icon_info(mid)
            item["title"] = info["title"]
            item["icon_before"] = info["icon"]
            if not info["url"]:
                item.update(status="skipped", reason="这个模型没有图标（icon_format 为空）")
                results.append(item)
                SESSION.log(f"  mid={mid}（{item['title']}）：跳过 —— 没有图标")
                continue
            if info["watermarked"]:
                item.update(status="skipped",
                            reason="现在挂的就是本工具上次生成的那张图，再加会叠第二层")
                results.append(item)
                SESSION.log(f"  mid={mid}（{item['title']}）：跳过 —— 这张图本工具已经加过印了")
                continue
            # 后台自带的「图片水印」是**上架时**的一次性参数（evidence §3.2）。它开着的话，
            # 前台那张图可能已经有一层水印了 —— 我们叠上去就是两层。这只警告、不拦：
            # 后台那个开关不代表它一定给这张图叠过，拦下来反而会让用户"点了没反应"。
            if info["open_watermark"] not in ("", "0", None):
                item["note"] = (f"该模型开着后台自带的「图片水印」（open_watermark="
                                f"{info['open_watermark']}）—— 前台可能已经有一层水印，请核一眼")
                SESSION.log(f"  ⚠️ mid={mid}：后台自带的图片水印开着"
                            f"（open_watermark={info['open_watermark']}），前台可能已有水印")

            # ---- 2) 下载 + 加印（内存里做，保持原尺寸）
            style = _watermark_style(cid_map.get(mid, info.get("cid")))
            if style is None:
                SESSION.log(f"  mid={mid}：认不出类目，水印按默认口径落位")
            blob = _fetch_remote_image(info["url"])
            with Image.open(io.BytesIO(blob)) as raw:
                raw.load()
                source = raw if raw.mode == "RGBA" else raw.convert("RGBA")
                marked = watermark.apply_watermark(source, style=style, log=SESSION.log)
            size = f"{marked.width}×{marked.height}"

            # ---- 3) 上传（临时文件用完就删）
            tmp_dir = CACHE_DIR / "_wm_upload"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp = tmp_dir / f"mid{mid}.png"
            try:
                marked.save(tmp, format="PNG", optimize=True)
                uploaded = SESSION.client.upload_image(tmp)
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            new_icon = uploaded.get("id")
            if new_icon in (None, "", 0, "0"):
                raise ac.AdminContractError(f"上传返回里没有附件 id：{dict(uploaded)}")
            new_icon = int(new_icon)

            # ---- 4) 写回 + 回读（写后必须回读，否则"上传成功但没换上去"看不出来）
            SESSION.client.edit_model(mid, icon=new_icon)
            after = _model_icon_info(mid)
            if after["icon"] != new_icon:
                raise ac.AdminContractError(
                    f"写回后回读到的 icon 是 {after['icon']}，不是刚上传的 {new_icon} —— 图没生效")
            record_watermark(mid, new_icon)
            icons_out[str(mid)] = after
            item.update(status="done", icon_after=new_icon, size=size, url_after=after["url"])
            item["title"] = after["title"] or info["title"]
            SESSION.log(f"  mid={mid}（{item['title']}）：图已换（{size}，新附件 {new_icon}）")
        except Exception as exc:  # noqa: BLE001 —— 一个模型失败不该中断整批
            item.update(status="error", error=f"{type(exc).__name__}: {exc}")
            SESSION.log(f"  mid={mid}：失败 —— {type(exc).__name__}: {exc}")
            results.append(item)
            if isinstance(exc, ac.AdminAuthError):
                SESSION.log("  登录已失效，停止处理后面的模型")
                break
            continue
        results.append(item)

    done = [r for r in results if r.get("status") == "done"]
    skip = [r for r in results if r.get("status") == "skipped"]
    bad = [r for r in results if r.get("status") == "error"]
    SESSION.log("一键添加水印完成：换图 %d 个%s%s%s"
                % (len(done),
                   f"，跳过 {len(skip)} 个" if skip else "",
                   f"，失败 {len(bad)} 个" if bad else "",
                   f"，未处理 {len(mids) - len(results)} 个" if len(results) < len(mids) else ""))
    return {
        "ok": True,
        "requested": len(mids),
        "changed": len(done),
        "skipped": len(skip),
        "failed": len(bad),
        "results": results,
        # 前端拿它直接刷新图片列，不必再问一遍
        "icons": icons_out,
    }


def do_prune_item_score(body: dict) -> dict:
    """清掉导入表里属于 Item Score 的历史行（筛选只管新增，不删旧行）。

    判定顺序：
    1. 先按**当前 futbin 列表页**判 —— 在列表里且只有 Item Score 的，删；
    2. 表里还有、但列表里已看不到的（多已过期），再逐条查**详情页**确认
       （详情页有 ``itemScoreIcon.png`` 就是单挑战）。查不到的一律保留，不猜。

    清理会直接改写磁盘上的导入表（带备份），所以先把内存里的未保存改动挡下来，
    避免清完再「保存改动」又把删掉的行写回去。
    """

    if SESSION.dirty:
        return {"ok": False, "error": "列表里有未保存的改动 —— 先「保存改动」或「重新载入」，再清理"}

    path = _workbook_path(body.get("path") or SESSION.rows_path or DEFAULT_XLSX)
    if not path.is_file():
        return {"ok": False, "error": f"导入表不存在：{path}"}

    try:
        kinds = fetch_sbc.fetch_sbc_types(
            max_pages=int(body.get("max_pages") or 5), log=SESSION.log
        )
    except Exception as exc:  # 网络/解析异常都要原样告诉用户，不吞
        return {"ok": False, "error": f"抓取 SBC 列表失败：{exc}"}

    removed = fetch_sbc.prune_item_score_rows(path, kinds, log=SESSION.log, verify_missing=True)
    result = do_reload({"path": str(path)})
    result["removed"] = len(removed)
    if not removed:
        result["message"] = "没有需要清理的 Item Score 行"
    return result


def do_save(body: dict) -> dict:
    """把当前列表写回导入表（覆盖前自动备份）。"""

    if not SESSION.rows:
        return {"ok": False, "error": "当前没有数据可保存"}
    path = _workbook_path(body.get("path") or SESSION.rows_path or DEFAULT_XLSX)
    target, backup = wb.save_rows(path, SESSION.rows)
    SESSION.rows_path = target
    SESSION.dirty = False
    SESSION.log(
        f"已保存 {len(SESSION.rows)} 行到 {target.name}"
        + (f"，原文件备份为 {backup.name}" if backup else "")
    )
    return {"ok": True, **_list_state(), "saved": len(SESSION.rows),
            "backup": str(backup) if backup else ""}


# ---- 预览 / 执行 ----


def _ensure_rows(body: dict) -> None:
    if not SESSION.rows:
        do_reload(body)


def _plan_now(body: dict):
    """预览 / 上架共用的规划。

    2026-10-15 起导入表里 SBC（cid 9971 / 10203）与 Packs（cid 10255）混在一张表，
    而 Uploader 的「后台已有模型 / 回读 / 上架站点」都按 cid 查 —— 所以按 cid
    分组、各组一个 Uploader 各规划各的，再合并成一份总 plan 给界面看。
    """

    rows = SESSION.rows
    _, per_coin = _price_inputs(body)
    markup = _strict_dec(body.get("markup"), str(pricing.DEFAULT_MARKUP), "加成")
    base_fee = _strict_dec(body.get("base_fee"), str(pricing.BASE_FEE), "固定手续费")
    skip_existing = bool(body.get("skip_existing", True))

    groups: dict[int, list[wb.SbcRow]] = {}
    for row in rows:
        groups.setdefault(int(row.cid or 0), []).append(row)

    # 跨类目同名索引（用户口径 B，2026-10-15）：SBC 的两个叶子都要看 ——
    # 后台 9971 里已有 ``X(Non-repeatable)`` 时，归 10203 的 ``X`` 不该再建一份。
    sbc_rows = any(int(c or 0) in (wb.DEFAULT_CID, wb.CID_SBC_PLAYERS) for c in groups)
    pack_rows = any(int(c or 0) in wb.PACKS_PRICE_CIDS for c in groups)
    index: dict[str, Mapping] = {}
    if skip_existing:
        if sbc_rows:
            index.update(uploader.build_title_index(
                SESSION.client, [wb.DEFAULT_CID, wb.CID_SBC_PLAYERS], log=SESSION.log))
        if pack_rows:
            index.update(uploader.build_title_index(
                SESSION.client, sorted(wb.PACKS_PRICE_CIDS), log=SESSION.log))

    plan = Plan()
    plans: dict[int, tuple[Uploader, Plan]] = {}
    for cid in sorted(groups):
        up = _uploader(cid, title_index=index)
        part = up.plan(
            groups[cid],
            per_coin=per_coin,
            markup=markup,
            base_fee=base_fee,
            skip_existing=skip_existing,
        )
        plans[cid] = (up, part)
        plan.ready.extend(part.ready)
        plan.duplicates.extend(part.duplicates)
        plan.invalid.extend(part.invalid)
    return rows, plans, plan


def _plan_summary(plan, rows) -> dict:
    checked_ready = [r for r in plan.ready if r.selected]
    checked_dup = [r for r in plan.duplicates if r.selected]
    return {
        "ready": len(plan.ready),
        "duplicates": len(plan.duplicates),
        "invalid": len(plan.invalid),
        "selected_ready": len(checked_ready),
        "selected_duplicate": len(checked_dup),
        # 勾选总数（预览日志用它）。之前这个键不存在，日志一打就 KeyError ——
        # 2026-10-15 加「按 cid 分组规划」时顺手补上。
        "selected": sum(1 for r in rows if r.selected),
        "total": len(rows),
    }


def do_preview(body: dict) -> dict:
    _ensure_rows(body)
    rows, plans, plan = _plan_now(body)
    info = _plan_summary(plan, rows)
    SESSION.log(
        f"预览：共 {info['total']} 行，勾选 {info['selected']} 条 → "
        f"可新增 {info['selected_ready']}、已存在 {info['selected_duplicate']}；"
        f"（全部行中无效 {info['invalid']}）"
    )
    return {"ok": True, **_list_state(), **info}


# ---- set_id 补齐（2026-10-15 用户口径：模型的「更多扩展属性」要带
#      set_id = futbin 详情页后缀数字；上架时新增的已随 payload 带上，
#      这里负责给**已有模型**补齐缺失的） ----


def _row_set_id(row: wb.SbcRow) -> Optional[str]:
    """从行的扩展属性列拿 set_id：显式 ``set_id=…`` 优先；
    旧 futbin 行的 ``sbc_id=纯数字``（当年的 futbin 后缀）镜像；都没有 → None。"""

    pairs: list[tuple[str, str]] = []
    for part in str(row.extend or "").replace("，", ",").split(","):
        key, _, value = part.strip().partition("=")
        pairs.append((key.strip(), value.strip()))
    for key, value in pairs:
        if key == "set_id" and value:
            return value
    for key, value in pairs:
        if key == "sbc_id" and value.isdigit():
            return value
    return None


def _locate_more(payload: Any) -> Optional[Mapping]:
    """get_model 响应里找 more 对象。

    ⚠️ 真实位置是 ``data.row.more``（2026-10-15 实测）——顶层那个 ``more`` 是
    表单默认值（空的），照着它读会以为"这个模型没有扩展属性"。
    """
    if not isinstance(payload, Mapping):
        return None
    row = ac.AdminClient.model_row(payload)
    if row is not None and isinstance(row.get("more"), Mapping):
        return row["more"]
    for candidate in (payload, payload.get("row")):
        if isinstance(candidate, Mapping) and isinstance(candidate.get("more"), Mapping):
            return candidate["more"]
    return None


def repair_set_ids(rows: list[wb.SbcRow]) -> dict:
    """给**已有模型**补缺失的 set_id（读模型 more.extend → 缺就追加 → 写回 → 回读）。

    护栏：行没有 model_id / 拿不到 set_id / 模型已有 set_id → 跳过；
    模型详情里找不到 more 结构 → 跳过并记日志（绝不猜结构盲写）。
    """
    fixed = skipped = failed = 0
    details: list[str] = []
    for row in rows:
        mid = row.model_id
        set_id = _row_set_id(row)
        if not mid or not set_id:
            skipped += 1
            continue
        try:
            more = _locate_more(SESSION.client.get_model(int(mid)))
            if more is None:
                failed += 1
                details.append(f"{row.title}：模型详情里找不到 more 结构，跳过")
                continue
            extend = more.get("extend") if isinstance(more.get("extend"), list) else []
            already = any(isinstance(i, Mapping) and
                          str(i.get("key", "")).strip().lower() == "set_id"
                          for i in extend)
            if already:
                skipped += 1
                continue
            new_more = dict(more)
            new_more["extend"] = list(extend) + [{"key": "set_id", "value": str(set_id)}]
            SESSION.client.edit_model_more(int(mid), new_more)
            after = _locate_more(SESSION.client.get_model(int(mid)))
            after_ids = [i.get("value") for i in ((after or {}).get("extend") or [])
                         if isinstance(i, Mapping) and str(i.get("key", "")).lower() == "set_id"]
            if set_id in [str(v) for v in after_ids]:
                fixed += 1
                details.append(f"{row.title}（模型 {mid}）：set_id={set_id} 已写入并回读一致")
            else:
                failed += 1
                details.append(f"{row.title}（模型 {mid}）：⚠️ 写后回读不一致，请人工核对")
        except Exception as exc:  # noqa: BLE001 —— 单个失败不拖垮整批
            failed += 1
            details.append(f"{row.title}：{type(exc).__name__}: {exc}")
            SESSION.log(f"补 set_id｜{row.title} 失败：{exc}")
    if fixed or failed:
        SESSION.log(f"补 set_id 完成：写入 {fixed}、已有跳过 {skipped}、失败 {failed}")
    return {"fixed": fixed, "skipped": skipped, "failed": failed, "details": details}


def _set_id_pass() -> dict:
    """补 set_id 这一趟 —— **有新增 / 没新增都要走**（2026-10-16 修）。

    以前它写在 do_execute 的末尾，而「没有可勾选/可新增的行」会提前 return ⇒
    模型已存在（= 最需要补 set_id 的情况）时永远补不上。
    """
    try:
        return repair_set_ids([r for r in SESSION.rows if r.model_id])
    except Exception as exc:  # noqa: BLE001 —— 补齐失败不影响上架结果本身
        SESSION.log(f"补 set_id 整体失败：{exc}")
        return {}


def do_execute(body: dict) -> dict:
    _ensure_rows(body)
    # 每一轮上架都从零开始记「本轮上架过哪些模型」（自动流程的水印只看这一份）
    SESSION.shelved_mids = []
    rows, plans, plan = _plan_now(body)
    info = _plan_summary(plan, rows)

    # 只处理「勾选 且 规划为可新增」的行，并按 cid 分组（每组一个 Uploader / 一个类目）
    todo_by_cid: dict[int, list[wb.SbcRow]] = {}
    for row in plan.ready:
        if row.selected:
            todo_by_cid.setdefault(int(row.cid or 0), []).append(row)

    total = sum(len(v) for v in todo_by_cid.values())
    if not total:
        SESSION.log("没有勾选任何可新增的行，未做任何写入；下面仍会补一遍 set_id。")
        return {"ok": True, "created": 0, "shelved": 0,
                "set_id": _set_id_pass(),
                **_list_state(), **info}

    created: list[wb.SbcRow] = []
    last_shelf: dict = {}
    SESSION.log(f"将处理 {total} 条（已勾选）：" + "、".join(
        r.title for rows_ in todo_by_cid.values() for r in rows_))
    for index, (cid, todo) in enumerate(sorted(todo_by_cid.items()), start=1):
        up = plans[cid][0]
        label = f"（类目 {cid}，第 {index}/{len(todo_by_cid)} 组）"
        SESSION.log(f"阶段 1/3：准备 {len(todo)} 个图标 {label}")
        up.download_icons(todo)
        SESSION.log(f"阶段 2/3：上传图标 + 新增模型 {label}")
        up.create_models(todo, dry_run=False)
        group_created = [r for r in todo if r.model_id]
        if group_created:
            SESSION.log(f"阶段 3/3：批量上架 {len(group_created)} 个模型 {label}")
            last_shelf = up.shelf_models([int(r.model_id) for r in group_created],
                                         dry_run=False)
            # 记下「本轮真正上架过」的模型 —— 自动流程的水印只加这些（用户口径 2026-10-15）
            for r in group_created:
                if int(r.model_id) not in SESSION.shelved_mids:
                    SESSION.shelved_mids.append(int(r.model_id))
        created.extend(group_created)
    if last_shelf:
        SESSION.log(f"上架接口返回：{last_shelf.get('msg') or last_shelf}")
    SESSION.log("执行完成，请到后台列表页核对（上架是异步任务，稍后刷新可见）")
    # set_id 补齐（用户口径 2026-10-15）：本轮新建的模型在 payload 里已带；
    # 这里再把**表里已有模型**缺 set_id 的一并补上（读模型 → 缺就追加 → 回读核对）。
    set_id_result: dict = _set_id_pass()
    return {
        "ok": True,
        "created": len(created),
        "shelved": len(created),
        "message": str(last_shelf.get("msg") or ""),
        "set_id": set_id_result,
        **_list_state(),
        **info,
    }


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "FC27SbcTool"

    def log_message(self, *args) -> None:  # 静音默认访问日志
        pass

    # ---- 工具 ----
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > 10 * 1024 * 1024:
            raise BadInput("请求大小超出限制")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            raise BadInput("请求必须是 JSON 对象") from None
        if not isinstance(body, dict):
            raise BadInput("请求必须是 JSON 对象")
        return body

    # ---- 路由 ----
    def _authorized(self, write=False) -> bool:
        # Nginx overwrites these headers with the verified portal identity.
        user = self.headers.get("X-SBC-User", "")
        role = self.headers.get("X-SBC-Role", "")
        SESSION.last_write_user = user
        if not user or role not in ("admin", "readonly"):
            self._json({"ok": False, "error": "请通过统一登录入口访问"}, 401)
            return False
        if write and role != "admin":
            self._json({"ok": False, "error": "此操作仅限现有管理员"}, 403)
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = _route_path(urlparse(self.path).path)
        if path == "/health":
            return self._json({"ok": True, "version": "sbc-security-20261015",
                               "busy": SESSION.busy, "running": AUTOMATION.status()["running"]})
        if not self._authorized(write=path not in ("/", "/index.html", "/api/status", "/api/auto")):
            return
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/status":
            return self._json({
                "ok": True,
                "portal_role": self.headers.get("X-SBC-Role"),
                "logged_in": SESSION.logged_in,
                "remembered": False,
                "busy": SESSION.busy,
                "scope": SESSION.last_scope,
                "areas": [{"aid": a, "name": n} for a, n in pricing.AREA_AIDS.items()],
                "default_aid": pricing.DEFAULT_AREA_AID,
                "markup": str(pricing.DEFAULT_MARKUP),
                "base_fee": str(pricing.BASE_FEE),
                # ⑤ 改价面板自己的口径（与 ③ 的 markup/base_fee 分开存）
                "reprice_markup": str(SESSION.reprice_settings.markup),
                "reprice_fee": str(SESSION.reprice_settings.fee),
                "default_xlsx": str(DEFAULT_XLSX),
                "rows_path": str(SESSION.rows_path),
                "row_count": len(SESSION.rows),
                "selected": SESSION.selected_count(),
                "dirty": SESSION.dirty,
            })
        if path == "/api/rows":
            return self._json({"ok": True, **_list_state(),
                               "count": len(SESSION.rows), "dirty": SESSION.dirty,
                               "selected": SESSION.selected_count()})
        if path == "/api/icon":
            query = parse_qs(urlparse(self.path).query)
            row = SESSION.row_by_uid((query.get("uid") or [""])[0])
            if row is None:
                return self._send(404, b"no such row", "text/plain")
            try:
                local = _ensure_icon(row)
            except Exception as exc:  # noqa: BLE001
                SESSION.log(f"取图失败（{row.title}）：{exc}")
                local = None
            if local is None:
                return self._send(404, b"no icon", "text/plain")
            return self._send(200, local.read_bytes(), _ctype_for(local))
        if path == "/api/log":
            query = parse_qs(urlparse(self.path).query)
            since = int((query.get("since") or ["0"])[0])
            lines, total = SESSION.take_logs(since)
            return self._json({"ok": True, "lines": lines, "total": total})
        if path == "/api/auto":
            # 只读：⑥ 自动化的设置与运行状态（前端 5 秒轮询，轻量、不占闸）
            return self._json({"ok": True, **AUTOMATION.status()})
        if path == "/api/download":
            query = parse_qs(urlparse(self.path).query)
            try:
                target = _workbook_path((query.get("path") or [str(DEFAULT_XLSX)])[0])
            except BadInput as exc:
                return self._json({"ok": False, "error": str(exc)}, 400)
            if not target.is_file() or target.suffix.lower() != ".xlsx":
                return self._json({"ok": False, "error": "文件不存在"}, 404)
            return self._send(200, target.read_bytes(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized(write=True):
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._json({"ok": False, "error": "仅接受 JSON 请求"}, 415)
        path = _route_path(urlparse(self.path).path)
        try:
            body = self._read_body()
        except (BadInput, ValueError) as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

        def run(func, *args, gate: bool = True) -> None:
            """``gate=False``：**不走「有任务正在执行」那道闸**，用于纯本地的轻量写。

            全应用只有一把 `SESSION.busy` 锁（采集 / 上架 / 站点列表 / 修复…共用）。
            对于「写一个布尔值到小 json」这种操作，占这把锁不但没必要，还会**踩到
            用户的正常操作顺序**：页面一载入就会发 `POST /api/sites` 拉站点列表
            （要联网、要几秒），这期间用户点一下某个复选框就会被闸掉，回执
            409「有任务正在执行，请稍候」→ 前端只好把刚点的勾弹回去。
            用户看到的是「点了没反应 / 勾了自己弹回去」（2026-10-10 实测复现）。

            ⚠️ 现在**没有调用点**了（那个"轻量本地写"的复选框随 ④ 的水印开关一起撤掉了）。
               保留这个参数是因为那条教训是通用的：**判断某个操作要不要占全局锁，
               看的是它会不会和别的任务抢资源，不是看它"写不写盘"。**
               以后再加"写一个小 json 的开关"，请直接用 `gate=False`，
               不要因为它写盘就默认占闸。
            """

            if gate:
                with SESSION.lock:
                    if SESSION.busy:
                        return self._json({"ok": False, "error": "有任务正在执行，请稍候"}, 409)
                    SESSION.busy = True
            try:
                self._json(func(*args))
            except BadInput as exc:
                SESSION.log(f"输入不合法：{exc}")
                self._json({"ok": False, "error": str(exc)}, 400)
            except ac.AdminAuthError as exc:
                self._json({"ok": False, "error": f"登录失效：{exc}"}, 401)
            except Exception as exc:  # noqa: BLE001
                SESSION.log(traceback.format_exc())
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            finally:
                # ⚠️ 只清自己立的旗。gate=False 时不能碰 busy ——
                #    那会把另一个真在跑的重任务放行，两道任务就并发了。
                if gate:
                    with SESSION.lock:
                        SESSION.busy = False

        if path == "/api/pricing":
            def pricing_call() -> dict:
                coin = _refresh_coin(int(body.get("aid") or pricing.DEFAULT_AREA_AID))
                SESSION.log(f"{coin.area} 单价 {coin.unit_price_per_1k}/1K（100K=${coin.price_per_100k}）")
                return {"ok": True, "aid": coin.aid, "area": coin.area,
                        "unit_price_per_1k": str(coin.unit_price_per_1k),
                        "price_per_100k": str(coin.price_per_100k)}
            return run(pricing_call)
        if path == "/api/readonly":
            return run(do_readonly_check)
        if path == "/api/goods":
            return run(do_goods_list, body)
        if path == "/api/sites":
            return run(do_sites)
        if path == "/api/rates":
            return run(do_fetch_rates, body)
        if path == "/api/settings/save":
            return run(do_save_settings, body)
        if path == "/api/reprice":
            return run(do_reprice, body)
        if path == "/api/permcheck":
            return run(do_permcheck, body)
        if path == "/api/fetch":
            return run(do_fetch, body)
        if path == "/api/fetch_packs":
            return run(do_fetch_packs, body)
        if path == "/api/delist":
            # 真写后台（把过期模型的「状态」点灭），必须占闸
            return run(do_delist, body)
        if path == "/api/auto":
            # 只读：自动化设置 + 运行状态。轻量读，不占闸
            return self._json({"ok": True, **AUTOMATION.status()})
        if path == "/api/auto/save":
            # 写一个小 json 的轻量操作：不走全局闸（否则采集/改价跑着时改不了定时）
            return run(do_auto_save, body, gate=False)
        if path == "/api/auto/run":
            # ⚠️ gate=False：这条**只负责把任务丢进后台线程**，**不能占全局闸** ——
            #    占了自己就会被任务线程的 _acquire_busy 看到"用户正在操作"而原地推迟
            #    （2026-10-15 实测：手动点「立即运行」永远跑不起来，日志只留一行"推迟"）。
            #    真正的并发保护在 Automation._acquire_busy 里（占了才跑）。
            return run(do_auto_run, body, gate=False)
        if path == "/api/preview":
            return run(do_preview, body)
        if path == "/api/execute":
            return run(do_execute, body)
        if path == "/api/rows/reload":
            return run(do_reload, body)
        if path == "/api/rows/select":
            return run(do_select, body)
        if path == "/api/rows/delete":
            return run(do_delete, body)
        if path == "/api/rows/update":
            return run(do_update, body)
        if path == "/api/rows/icon":
            return run(do_icon_upload, body)
        if path == "/api/icons/fix":
            return run(do_fix_icons, body)
        if path == "/api/models/icons":
            # 只读（GET 模型详情），但仍然占闸 —— 它一次会打十几个后台请求，
            # 和采集抢同一个登录态与连接池，没必要并发。
            return run(do_model_icons, body)
        if path == "/api/models/watermark":
            # ⚠️ 真写后台：下载图 → 上传新附件 → 改模型 icon。必须占闸（默认 gate=True）。
            return run(do_watermark_models, body)
        if path == "/api/rows/prune_item_score":
            return run(do_prune_item_score, body)
        if path == "/api/rows/save":
            return run(do_save, body)
        if path == "/api/packs":
            return self._json({"ok": False,
                               "error": "packs 采集已并入 /api/fetch_packs（FUTGenie 源）"}, 400)
        return self._json({"ok": False, "error": "not found"}, 404)


# ================================================================= #
# ⑥ 自动化：步骤胶水（2026-10-15）
#
# 每一步都调用「用户手点那个按钮」的同一条链路 —— 自动化做的必须等于
# 用户手点的，两边行为一旦分叉就是两套系统。设置在 output/auto_settings.json。
# ================================================================= #


def _auto_settings_load() -> auto_flow.AutoSettings:
    return auto_flow.AutoSettings(AUTO_SETTINGS).load()


def _step_fetch_sbc() -> dict:
    """① 开始采集 SBC（FUT.GG，唯一闸门 = 金币价 > 10000）。"""
    st = _auto_settings_load()
    return do_fetch({"min_coins": int(st.data.get("min_coins") or 10000)})


def _step_fetch_packs() -> dict:
    """①b 采集 Packs（FUTGenie，只收右上角有倒计时的）。"""
    return do_fetch_packs({})


def _step_execute() -> dict:
    """② 上架（全部勾选行按 cid 分组；后台已存在的同名模型自动跳过）。"""
    st = _auto_settings_load()
    body: dict = {}
    if st.data.get("markup"):
        body["markup"] = st.data["markup"]
    if st.data.get("fee"):
        body["base_fee"] = st.data["fee"]
    return do_execute(body)


def _step_pull_goods() -> dict:
    """③ 拉取后台各区现价（站点 0 ALL、全类目）。"""
    return do_goods_list({"kind": "all", "site": "0"})


def _step_watermark() -> dict:
    """④ 一键添加水印：**只加本轮新上架的那几个模型**（用户口径 2026-10-15）。

    取的是上架步骤（③）记下的 ``SESSION.shelved_mids`` —— 本轮真正上架过的模型；
    本轮没有新上架的就直接跳过（不再全量扫）。

    ⚠️ 为什么不再按"拉取到的全部模型 + 表里有 model_id 的行"来加：
    ① 上架是**异步任务**，紧接着的「拉取现价」常看不到刚建好的模型，全量扫会漏；
    ② 全量扫还会去动**手工建的商品 / 已下架的商品**，超出"给本轮新品加印"的范围。
    """
    mids: list[int] = []
    seen: set[int] = set()
    for mid in getattr(SESSION, "shelved_mids", []) or []:
        if mid and mid not in seen:
            seen.add(mid)
            mids.append(int(mid))
    if not mids:
        return {"ok": True, "watermarked": 0,
                "message": "本轮没有新上架的模型，跳过水印"}
    watermarked = 0
    skipped = 0
    for start in range(0, len(mids), MAX_WATERMARK_MODELS):
        chunk = mids[start:start + MAX_WATERMARK_MODELS]
        part = do_watermark_models({"mids": chunk})
        if not part.get("ok") or part.get("failed") or len(part.get("results", [])) != len(chunk):
            return {**part, "ok": False, "error": "水印步骤存在失败或未确认结果，停止后续步骤"}
        # ⚠️ 计数键是 ``changed``（不是 processed/watermarked）——
        #    写错键会让步骤详情永远显示「水印 0」，看着像没干活（2026-10-15 踩到）。
        watermarked += int(part.get("changed") or 0)
        skipped += int(part.get("skipped") or 0)
    return {"ok": True, "watermarked": watermarked, "skipped": skipped,
            "message": f"本轮新上架 {len(mids)} 个模型"
                       f"（台账幂等：已加印的自动跳过）"}


#: 每金币价缓存「新鲜」的上限（秒）。
#: 云端直连 MMOEXP 是 403，只能吃本机推上来的缓存（见 push_price_to_cloud.py），
#: 所以「是不是缓存」不能当失败判据，要看**多新**。
RATE_CACHE_FRESH_SECONDS = 30 * 60


def _step_fetch_rates() -> dict:
    """⑤ 按 MMOEXP 取回最新每金币价（force=true 恒定真联网）。

    ``overwrite_own=False``：界面弹窗问的那句"要不要连单独设过的行一起覆盖"，
    无人值守时按**不覆盖**处理 —— 手改过的价是用户的决定，自动化不能悄悄冲掉。
    """
    result = do_fetch_rates({"force": True, "overwrite_own": False})
    if result.get("from_cache"):
        # 云端（数据中心 IP）访问 MMOEXP 是 403 —— 永远拿不到"刚联网取回"。
        # 所以判定不能只看"是不是缓存"，要看**缓存多新**：
        # 新鲜（≤30 分钟）= 本机刚用 push_price_to_cloud.py 推上来的，可用；
        # 明显过期 = 真的没有本轮价，拦住不往下改价（宁可不改，不用旧价改）。
        age = result.get("age_seconds")
        if age is not None and int(age) <= RATE_CACHE_FRESH_SECONDS:
            return {**result, "ok": True,
                    "message": f"用本机推上来的每金币价（{int(int(age) / 60)} 分钟前取的；"
                               f"云端直连 MMOEXP 被 403 挡）"}
        return {**result, "ok": False,
                "error": f"未取得本轮最新金币价（手上这份是 {int(int(age or 0) / 60)} 分钟前的旧缓存），"
                         f"停止自动改价"}
    return result


def _step_fill_coins() -> dict:
    """⑥ 用采集的金币价：按**归一化标题**把采集表的金币数填进在售行并持久化。

    ⚠️ **必须剥掉 (Non-repeatable) 后缀再比**（用户口径 2026-10-15）：
    后台模型叫 ``TOTW Upgrade(Non-repeatable)``、采集表里是 ``TOTW Upgrade`` ——
    直接比原始标题**一个都对不上**，那些非 Players 的 SBC 就永远用不上采集金币价。
    """
    by_title: dict[str, int] = {}
    for row in SESSION.rows:
        if row.title and row.coins:
            by_title.setdefault(uploader.normalize_title(row.title), int(row.coins))
    items: list[dict] = []
    for goods_row in SESSION.goods_rows:
        coins = by_title.get(uploader.normalize_title(goods_row.title or ""))
        if coins and goods_row.model_id:
            items.append({"model_id": goods_row.model_id,
                          "title": goods_row.title, "coins": coins})
    if not items:
        return {"ok": True, "filled": 0, "message": "没有匹配到任何采集金币价"}
    result = do_save_settings({"items": items})
    if result.get("ok"):
        result["filled"] = len(items)
        result["message"] = f"按标题匹配（忽略 (Non-repeatable) 后缀）并写入 {len(items)} 个模型的金币数"
    return result


def _step_reprice() -> dict:
    """⑦ 改价：全部亮行按引擎算目标价（金币数=采集的、每金币价=刚取的、口径=设置里的）。"""
    if not SESSION.goods_rows:
        return {"ok": False, "error": "还没有拉取后台现价，改不了"}
    items = [{"goods_id": row.goods_id} for row in SESSION.goods_rows]
    return do_reprice({"items": items})


def _step_delist() -> dict:
    return do_delist({})


def do_auto_save(body: dict) -> dict:
    """保存 ⑥ 自动化的开关与定时。轻量写（不占全局闸）。"""
    st = _auto_settings_load()
    changed = st.update(body)
    st.save()
    if changed["changed"]:
        # 记「改成了什么值」+「谁改的」—— 排查"开关莫名被关"全靠这一行（2026-10-16 加）
        detail = "、".join(f"{k}={st.data.get(k)!r}" for k in changed["changed"])
        who = str(getattr(SESSION, "last_write_user", "") or "").strip()
        SESSION.log(f"自动化设置已保存：{detail}" + (f"（操作者 {who}）" if who else ""))
    else:
        SESSION.log("自动化设置已保存（无变化）")
    return {"ok": True, **AUTOMATION.status(), **changed}


def do_auto_run(body: dict) -> dict:
    """手动触发一轮（后台线程跑，前端轮询 /api/auto 看进度）。"""
    kind = str(body.get("kind") or "pipeline").strip().lower()
    if kind == "delist":
        return AUTOMATION.run_delist(trigger="manual")
    if kind != "pipeline":
        return {"ok": False, "error": f"kind 只能是 pipeline / delist，收到 {kind!r}"}
    return AUTOMATION.run_pipeline(trigger="manual")


AUTOMATION = auto_flow.Automation(AUTO_SETTINGS)
AUTOMATION.bind({
    "fetch_sbc": _step_fetch_sbc,
    "fetch_packs": _step_fetch_packs,
    "execute": _step_execute,
    "pull_goods": _step_pull_goods,
    "watermark": _step_watermark,
    "fetch_rates": _step_fetch_rates,
    "fill_coins": _step_fill_coins,
    "reprice": _step_reprice,
    "delist": _step_delist,
    "log": SESSION.log,
    "session": SESSION,
})


PAGE = (
    '<!DOCTYPE html>\n'
    '<html lang="zh-CN">\n'
    '<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<title>FC27 SBC 上架工具</title>\n'
    '<style>\n'
    '  :root {\n'
    '    --bg:#f5f7fa; --card:#ffffff; --line:#dde3ea; --text:#16202c;\n'
    '    --muted:#61708a; --accent:#1d6fb8; --ok:#0f7b4f; --warn:#b45309; --danger:#b3261e;\n'
    '  }\n'
    '  * { box-sizing:border-box; }\n'
    '  body { margin:0; background:var(--bg); color:var(--text);\n'
    '         font:14px/1.6 "Microsoft YaHei UI","Segoe UI",system-ui,sans-serif; }\n'
    '  header { background:#fff; border-bottom:1px solid var(--line); padding:12px 20px;\n'
    '           display:flex; align-items:center; gap:14px; flex-wrap:wrap;\n'
    '           position:sticky; top:0; z-index:5; }\n'
    '  header h1 { font-size:16px; font-weight:500; margin:0; }\n'
    '  .badge { font-size:12px; padding:2px 9px; border-radius:10px; border:1px solid var(--line); color:var(--muted); }\n'
    '  .badge.on { color:var(--ok); border-color:#9fd3bb; background:#eaf6f0; }\n'
    '  main { padding:16px 20px 40px; max-width:1280px; }\n'
    '  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;\n'
    '          padding:14px 16px; margin-bottom:14px; }\n'
    '  .card h2 { font-size:14px; font-weight:500; margin:0 0 10px; color:#0d3b5c; }\n'
    '  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }\n'
    '  label { color:var(--muted); font-size:13px; }\n'
    '  input, select { padding:6px 8px; border:1px solid var(--line); border-radius:6px;\n'
    '                  font:13px "Consolas","Microsoft YaHei UI",monospace; background:#fff; color:var(--text); }\n'
    '  input.w-sm { width:80px; } input.w-md { width:130px; } input.w-lg { width:100%; }\n'
    '  /* 缺「每金币价」的行标红：这一列不填就算不出目标价 */\n'
    '  input.need { border-color:var(--warn); background:#fffaf0; }\n'
    '  input.need::placeholder { color:var(--warn); opacity:.85; }\n'
    '  /* 手续费被逐行单独设过的格子加个淡底，一眼能和「沿用全局值」的行区分开 */\n'
    '  input.own { border-color:var(--accent); background:#f2f8ff; font-weight:600; }\n'
    '  /* 「自己设的值恰好等于某个区服默认价」—— 十有八九是老版本「保存」把自动带出的\n'
    '     值冻成了手改值（见 GoodsRow.rate_auto）。只做**视觉**标记，绝不据此自动改数据：\n'
    '     判据只是"相等"，用户真手填成同一个值也会命中。 */\n'
    '  input.own.frozen { border-color:var(--danger); background:#fff5f5; }\n'
    '  .frozen-tag { color:var(--danger); font-weight:600; }\n'
    '  table.grid th .th-sub { font-weight:400; color:var(--muted); font-size:11px; }\n'
    '  button { padding:7px 14px; border:1px solid var(--line); border-radius:6px; background:#fff;\n'
    '           color:var(--text); cursor:pointer; font:13px "Microsoft YaHei UI",sans-serif; }\n'
    '  button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }\n'
    '  button:disabled { opacity:.5; cursor:not-allowed; }\n'
    '  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }\n'
    '  button.primary:hover:not(:disabled) { background:#155a97; color:#fff; }\n'
    '  button.danger { background:var(--danger); border-color:var(--danger); color:#fff; }\n'
    '  button.danger:hover:not(:disabled) { background:#8d1d17; color:#fff; }\n'
    '  #captcha { border:1px solid var(--line); border-radius:6px; vertical-align:middle; cursor:pointer; }\n'
    '  table { width:100%; border-collapse:collapse; font-size:13px; }\n'
    '  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }\n'
    '  th { color:var(--muted); font-weight:500; background:#fafbfd; position:sticky; top:0; }\n'
    '  .scroll { max-height:340px; overflow:auto; border:1px solid var(--line); border-radius:8px; }\n'
    '  .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--danger); }\n'
    '  #log { font:12px/1.55 Consolas,monospace; white-space:pre-wrap; background:#101820; color:#d6e2ef;\n'
    '         border-radius:8px; padding:12px; height:240px; overflow:auto; margin:0; }\n'
    '  .hint { color:var(--muted); font-size:12px; }\n'
    '  .split { display:grid; grid-template-columns:1fr 1fr; gap:14px; }\n'
    '  @media (max-width:1000px){ .split { grid-template-columns:1fr; } }\n'
    '\n'
    '  /* ---- 列表：勾选 / 缩略图 / 行内操作 ---- */\n'
    '  button.mini { padding:3px 9px; font-size:12px; border-radius:5px; }\n'
    '  table.grid td:first-child, table.grid th:first-child { width:36px; text-align:center; }\n'
    '  .thumb { width:36px; height:36px; object-fit:contain; border:1px solid var(--line);\n'
    '           border-radius:5px; background:#fff; display:block; }\n'
    '  /* ⑤ 表格的「图片」列：显示这一行所属模型**当前挂在后台**的那张图。\n'
    '     同一模型的多行会显示同一张图 —— 这是**有意的**，它就是在告诉用户\n'
    '     "这几行共用一张图，加一次水印它们一起变"。 */\n'
    '  .rp-pic { width:52px; height:52px; object-fit:contain; border:1px solid var(--line);\n'
    '            border-radius:5px; background:#fff; display:block; }\n'
    '  .rp-pic-cell { display:flex; flex-direction:column; align-items:center; gap:3px; }\n'
    '  .rp-pic-tag { font-size:11px; line-height:1.3; white-space:nowrap; }\n'
    '  .rp-pic-tag.done { color:var(--ok); font-weight:600; }\n'
    '  .rp-pic-tag.warn { color:var(--warn); }\n'
    '  .thumb.missing { display:flex; align-items:center; justify-content:center;\n'
    '                   color:#b9c2d0; font-size:10px; border-style:dashed; }\n'
    '  tr.sel-off { background:#fafbfd; }\n'
    '  tr.sel-off td:not(:first-child) { opacity:.5; }\n'
    '  tbody tr:hover { background:#f4f8fc; }\n'
    '  #dirty { font-weight:500; }\n'
    '\n'
    '  /* ---- 编辑弹窗 ---- */\n'
    '  .mask { position:fixed; inset:0; background:rgba(16,24,32,.45); display:none;\n'
    '          align-items:center; justify-content:center; z-index:50; padding:20px; }\n'
    '  .mask.on { display:flex; }\n'
    '  .dialog { background:#fff; border-radius:12px; width:min(760px,100%); max-height:92vh;\n'
    '            overflow:auto; padding:18px 20px; box-shadow:0 18px 50px rgba(0,0,0,.24); }\n'
    '  .dialog h3 { margin:0 0 4px; font-size:15px; font-weight:500; color:#0d3b5c; }\n'
    '  .dialog .sub { color:var(--muted); font-size:12px; margin-bottom:14px; }\n'
    '  .dlg-body { display:grid; grid-template-columns:190px 1fr; gap:18px; }\n'
    '  @media (max-width:720px){ .dlg-body { grid-template-columns:1fr; } }\n'
    '  .dlg-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:16px;\n'
    '                 border-top:1px solid var(--line); padding-top:12px; }\n'
    '  .field { margin-bottom:10px; }\n'
    '  .field > label { display:block; margin-bottom:4px; }\n'
    '  .field input, .field textarea { width:100%; }\n'
    '  textarea { padding:6px 8px; border:1px solid var(--line); border-radius:6px;\n'
    '             font:13px "Microsoft YaHei UI",sans-serif; background:#fff; color:var(--text);\n'
    '             resize:vertical; }\n'
    '  .preview-box { border:1px dashed var(--line); border-radius:8px; padding:8px;\n'
    '                 text-align:center; background:#fafbfd; min-height:132px;\n'
    '                 display:flex; align-items:center; justify-content:center; }\n'
    '  .preview-box img { max-width:100%; max-height:160px; border-radius:6px; display:block; }\n'
    '  .preview-box .ph { color:#b9c2d0; font-size:12px; }\n'
    '  .drop { border:1px dashed var(--line); border-radius:8px; padding:10px; text-align:center;\n'
    '          margin-top:8px; background:#fff; cursor:pointer; font-size:12px; color:var(--muted); }\n'
    '  .drop:hover { border-color:var(--accent); color:var(--accent); }\n'
    '  .drop input { display:none; }\n'
    '  /* ---------- ⑥ 自动化面板 ---------- */\n'
    '  .auto-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr));\n'
    '               gap:14px; margin-top:6px; }\n'
    '  .auto-box { border:1px solid var(--line); border-radius:10px; padding:14px 16px;\n'
    '              background:linear-gradient(180deg,#fbfdff, #f4f7fb); }\n'
    '  .auto-head { display:flex; align-items:center; gap:10px; margin-bottom:10px; }\n'
    '  .auto-head b { font-size:15px; }\n'
    '  .auto-state { margin-left:auto; font-size:12px; padding:2px 10px; border-radius:999px;\n'
    '                background:#eef2f7; color:var(--muted); border:1px solid var(--line); }\n'
    '  .auto-state.on { background:#e7f6ee; color:var(--ok); border-color:#bfe6d2; }\n'
    '  .auto-state.busy { background:#fff5e6; color:var(--warn); border-color:#f0dcb0; }\n'
    '  .auto-state.err { background:#fdeeee; color:var(--danger); border-color:#f0c4c4; }\n'
    '  /* 开关 */\n'
    '  .auto-toggle { position:relative; display:inline-block; width:40px; height:22px; flex:none; }\n'
    '  .auto-toggle input { opacity:0; width:0; height:0; }\n'
    '  .auto-slider { position:absolute; cursor:pointer; inset:0; border-radius:999px;\n'
    '                 background:#cfd8e3; transition:.18s; }\n'
    '  .auto-slider:before { content:""; position:absolute; height:16px; width:16px;\n'
    '                        left:3px; top:3px; background:#fff; border-radius:50%;\n'
    '                        transition:.18s; box-shadow:0 1px 3px rgba(0,0,0,.25); }\n'
    '  .auto-toggle input:checked + .auto-slider { background:var(--accent); }\n'
    '  .auto-toggle input:checked + .auto-slider:before { transform:translateX(18px); }\n'
    '  .auto-toggle input:focus-visible + .auto-slider { outline:2px solid var(--accent); outline-offset:2px; }\n'
    '  /* 步骤时间线 */\n'
    '  .auto-steps { margin:10px 0 4px; display:flex; flex-direction:column; gap:4px; }\n'
    '  .auto-step { display:flex; align-items:center; gap:8px; font-size:12.5px;\n'
    '               padding:3px 8px; border-radius:6px; }\n'
    '  .auto-step .dot { width:8px; height:8px; border-radius:50%; background:#cfd8e3; flex:none; }\n'
    '  .auto-step.ok   { background:#f2faf5; } .auto-step.ok   .dot { background:var(--ok); }\n'
    '  .auto-step.fail { background:#fdf1f1; color:var(--danger); } .auto-step.fail .dot { background:var(--danger); }\n'
    '  .auto-step.run  { background:#fff7ea; color:var(--warn); }\n'
    '  .auto-step.run  .dot { background:var(--warn); animation:autoblink 1s infinite; }\n'
    '  .auto-step .d { color:var(--muted); margin-left:auto; text-align:right; }\n'
    '  @keyframes autoblink { 50% { opacity:.35; } }\n'
    '  .hint-inline { color:var(--muted); margin-left:6px; }\n'
    '  .w-xs { width:64px; }\n'
    '</style>\n'
    '</head>\n'
    '<body>\n'
    '<header>\n'
    '  <h1>FC27 SBC 上架工具</h1>\n'
    '  <span id="state" class="badge">未登录</span>\n'
    '  <span class="hint" id="scope"></span>\n'
    '  <span style="flex:1"></span>\n'
    '</header>\n'
    '\n'
    '<main>\n'
    '  <div class="card">\n'
    '    <h2>① 后台会话</h2>\n'
    '    <p class="hint">后台会话由 FS 统一管理，当前状态见顶部指示。</p>\n'
    '    <button onclick="api(\'/api/readonly\',{}).then(show)">后台只读检查</button>\n'
    '  </div>\n'
    '\n'
    '  <div class="split">\n'
    '    <div class="card">\n'
    '      <h2>② 采集 SBC / Packs</h2>\n'
    '      <div class="row">\n'
    '        <label>金币价下限</label><input id="min_coins" class="w-sm" value="10000">\n'
    '      </div>\n'
    '      <div class="row">\n'
    '        <label><input type="checkbox" id="append" checked> 追加到已有表</label>\n'
    '        <label><input type="checkbox" id="sync_live" checked>\n'
    '          和采集站对齐（删掉已下架的旧行、刷新在架行的金币价）</label>\n'
    '      </div>\n'
    '      <div class="row">\n'
    '        <label><input type="checkbox" id="fill_text">\n'
    '          自动填产品摘要/描述（默认留空，勾选后沿用旧规则）</label>\n'
    '      </div>\n'
    '      <div class="row">\n'
    '        <label>输出文件</label><input id="xlsx" class="w-lg">\n'
    '      </div>\n'
    '      <div class="row">\n'
    '        <button class="primary" onclick="doFetch()">开始采集 SBC（FUT.GG）</button>\n'
    '        <button class="primary" onclick="doFetchPacks()">采集 Packs（FUTGenie）</button>\n'
    '      </div>\n'
    '      <div class="hint"><b>SBC 源 = fut.gg</b>（2026-10-15 起）：<b>全种类都采</b>\n'
    '        （Players / Upgrades / Challenges / Foundations），\n'
    '        <b>唯一的闸门是金币价 &gt; 下限</b>（保留<b>比它贵</b>的，想收便宜的把下限调小）。\n'
    '        图 / 名字 / 金币价全部取 fut.gg。详情链接带 <b>players</b> 的归类到\n'
    '        <b>10203 SBC Players</b>，其余归 <b>9971 Upgrade</b>。<br>\n'
    '        <b>Packs 源 = futgenie.gg</b>：只收列表页<b>右上角有倒计时</b>的 pack\n'
    '        （还在架上架中的），进详情页采<b>全名</b>与<b>精确金币价</b>，\n'
    '        归 <b>10255 In-Game Packs</b>（上架不收手续费）。<br>\n'
    '        采集同时会和采集站<b>对齐</b>：已下架的行删掉、还在架的行刷新 ——\n'
    '        SBC 行与 Packs 行<b>各管各的</b>，旧 futbin 行首次会按标题收编进来。<br>\n'
    '        图标会自动修复：下载后<b>自动裁掉透明边、放大到 400×400 并锐化</b>，\n'
    '        原始图另存在 cache/icons_raw 不动。</div>\n'
    '    </div>\n'
    '\n'
    '    <div class="card">\n'
    '      <h2>③ 计价</h2>\n'
    '      <div class="row">\n'
    '        <label>游戏区服</label>\n'
    '        <select id="area"></select>\n'
    '        <button onclick="refreshPrice()">按 MMOEXP 刷新</button>\n'
    '      </div>\n'
    '      <div class="row">\n'
    '        <label>金币单价</label><input id="unit_price" class="w-md"><span class="hint">USD / 1K 金币</span>\n'
    '      </div>\n'
    '      <div class="row">\n'
    '        <label>加成</label><input id="markup" class="w-sm">\n'
    '        <label>固定手续费</label><input id="base_fee" class="w-sm">\n'
    '        <label><input type="checkbox" id="skip_existing" checked> 跳过已存在</label>\n'
    '      </div>\n'
    '      <div class="hint">单价 = (金币 × 每金币价 + 手续费) × 加成，价源：mmoexp.com/ajax/goods</div>\n'
    '    </div>\n'
    '  </div>\n'
    '\n'
    '  <div class="card">\n'
    '    <h2>④ 上架 · 可逐条勾选 / 改标题 / 换图 / 删除</h2>\n'
    '    <div class="row">\n'
    '      <label>导入表</label><input id="import_path" class="w-lg">\n'
    '      <button onclick="reloadRows()">重新载入</button>\n'
    '      <button onclick="downloadTable()">下载表格</button>\n'
    '      <button id="fix_btn" onclick="fixIcons()" title="裁掉透明边 → 放大到 400×400 → 去噪锐化。可反复点，始终从原始图重算。">一键修复图片</button>\n'
    '      <button id="prune_btn" onclick="pruneItemScore()" title="按当前 futbin 列表判定类型，删掉导入表里「只有 Item Score」的历史行（改写前自动备份）。">清理 Item Score 行</button>\n'
    '      <button id="save_btn" class="primary" onclick="saveRows()" disabled>保存改动</button>\n'
    '      <span class="hint" id="dirty"></span>\n'
    '    </div>\n'
    '    <div class="row">\n'
    '      <button onclick="selectAll(true)">全选</button>\n'
    '      <button onclick="selectAll(false)">全不选</button>\n'
    '      <span class="hint" id="counts">未载入</span>\n'
    '      <span style="flex:1"></span>\n'
    '      <button onclick="doPreview()">预览（不改后台）</button>\n'
    '      <button class="danger" onclick="doExecute()">上架已勾选</button>\n'
    '    </div>\n'
    '    <div class="hint" style="margin-bottom:6px">\n'
    '      只有 <b>勾选</b> 的行会被上架；点「改标题/图」可改产品名称和图片，点「删除」把这条从列表去掉。\n'
    '      改完记得点「保存改动」写回导入表（覆盖前会自动备份一份）。<br>\n'
    '      图片在采集时会<b>自动修复</b>；想按新尺寸重做一遍就点「一键修复图片」（始终从原始图重算，不会越修越糊）。<br>\n'
    '      给<b>已经在架上的商品</b>换带水印的图，不在这一节 —— 见 ⑤ 按区改价里的「<b>一键添加水印</b>」。\n'
    '    </div>\n'
    '    <div class="hint" id="plan"></div>\n'
    '    <div class="scroll" style="margin-top:10px">\n'
    '      <table class="grid">\n'
    '        <thead><tr>\n'
    '          <th><input type="checkbox" id="check_all" onclick="selectAll(this.checked)" title="全选 / 全不选"></th>\n'
    '          <th>图</th><th>产品名称</th><th>金币价</th><th>单价</th>\n'
    '          <th>状态</th><th>模型 ID</th><th>操作</th>\n'
    '        </tr></thead>\n'
    '        <tbody id="rows"><tr><td colspan="8" class="hint">还没有数据，先「重新载入」或采集</td></tr></tbody>\n'
    '      </table>\n'
    '    </div>\n'
    '  </div>\n'
    '\n'
    '  <div class="card">\n'
    '    <h2>⑤ 按区改价 · SBC / Packs</h2>\n'
    '    <div class="row">\n'
    '      <label title="这是**全局**值。表格里每一行都能单独覆盖它。">加成<span class="hint">全局</span></label>\n'
    '      <input id="rp_markup" class="w-sm" value="1.1" onchange="rpMarkupChanged()"\n'
    '             title="**全局**加成本（价格倍数）：所有没在表格里单独设过的行都用它。想给某一行单独定，直接改表格里「加成」列那一格。&#10;SBC：(金币 × 每金币价 + 手续费) × 加成；Packs：(金币 × 每金币价) × 加成">\n'
    '      <label title="这是**全局**值。表格里每一行 SBC 都能单独覆盖它。">手续费<span class="hint">全局</span></label>\n'
    '      <input id="rp_fee" class="w-sm" value="0.24" onchange="rpFeeChanged()"\n'
    '             title="**全局**每份固定手续费：所有没在表格里单独设过的 SBC 都用它；Packs 恒计 0。想给某一个 SBC 单独定，直接改表格里「手续费」列那一格。">\n'
    '      <label>站点</label>\n'
    '      <select id="rp_site" title="后台在售表按站点铺开：一个产品 × 18 站点 × 3 区服 = 54 行，所以必须选定站点">\n'
    '        <option value="0">0 ALL（改价用）</option>\n'
    '      </select>\n'
    '      <label>类目</label>\n'
    '      <select id="rp_mode">\n'
    '        <option value="all">SBC + Packs（9625 / 9629，含底下所有叶子）</option>\n'
    '        <option value="sbc">只要 SBC（9625，含 SBC Players / Upgrade）</option>\n'
    '        <option value="pack">只要 Packs（9629，含 In-Game Packs）</option>\n'
    '      </select>\n'
    '      <button id="rp_load" class="primary" onclick="rpLoad()">拉取后台各区现价</button>\n'
    '      <button id="rp_wm" class="primary" onclick="rpWatermark()"\n'
    '              title="把**勾选行**的后台商品图抓下来、叠上 MMOEXP 水印、写回产品模型（真的换前台那张图）。\n'
    '· 入口就是后台的：产品管理 → 产品模型管理 → 游戏 1327 FC27 → 类目 9625/9629 → 编辑 → 图标。\n'
    '· **只处理勾选的行**；按「模型」去重 —— 模型图是全站点共用的，勾同一模型的 3 行只处理 1 次。\n'
    '· 已经加过印的会被跳过（工具认自己上次传上去的那个附件 id），不会叠第二层。\n'
    '· 后台会顺手把这些模型的「上架时间」刷成当前时刻 —— 后台自己在界面里改图也一样。">一键添加水印</button>\n'
    '      <button onclick="rpSaveSettings()">保存金币数/每金币价/手续费/加成</button>\n'
    '    </div>\n'
    '    <div class="hint" style="margin-bottom:6px">\n'
    '      价格口径（<b>SBC 与 Packs 不一样</b>）：\n'
    '      <br>\n'
    '      · <b>SBC</b>：<b>目标价 = (金币数 × 每金币价 + 手续费) × 加成</b>\n'
    '      <br>\n'
    '      · <b>Packs</b>：<b>目标价 = (金币数 × 每金币价) × 加成</b>（不收手续费）\n'
    '      <br>\n'
    '      手续费默认 <b>0.24</b>，在乘法之后、加成之前加 —— 是 <code>(金币×每金币价 + 0.24) × 加成</code>，\n'
    '      不是 <code>金币×每金币价×加成 + 0.24</code>。\n'
    '      <br>\n'
    '      <b>手续费可以逐行改</b>：顶部那个框是 <b>全局值</b>（所有没单独设过的 SBC 都用它），\n'
    '      表格里「手续费」列 <b>每一行 SBC 都能单独覆盖</b> —— 改哪行就哪行生效，旁边会标 <b>「已单独设」</b>；\n'
    '      把那一格清空 = 取消单独设置，回落全局值。<b>Packs 恒不计手续费</b>，那一格不可编辑。\n'
    '      <br>\n'
    '      <b>加成也可以逐行改</b>：顶部那个框同样是 <b>全局值</b>，表格里「加成」列\n'
    '      <b>每一行都能单独覆盖</b>（这一格 <b>不像手续费那样分 SBC / Packs</b> —— 两类都乘加成）。\n'
    '      改哪行就哪行生效，旁边会标 <b>「已单独设」</b>；把那一格清空 = 取消单独设置，回落全局值。\n'
    '      <b>加成必须大于 0</b>（填 0 会让目标价直接变成 0），不想加成请填 <b>1</b>。\n'
    '      <br>\n'
    '      <b>金币数</b>：该 SBC 在游戏里要花多少金币（点「用采集的金币价」按产品名带出，Packs 没有 futbin 数据需手填）。\n'
    '      <br>\n'
    '      <b>每金币价</b>：金币的市场单价。点 <b>「按 MMOEXP 取回最新每金币价」</b> 按区服自动填\n'
    '      （和 ③ 计价面板同一个来源；<b>每次点都真联网取最新，不读缓存</b>），\n'
    '      也可以逐行手改；两者都可保存。\n'
    '      <br>\n'
    '      表格里现价下面那行是<b>后台当前合多少每金币</b>（= 现价 ÷ 每份数量 ÷ 金币数），\n'
    '      <b>只用于对比</b> —— 拿它当输入的话金币数会被约掉，所以不参与计算。\n'
    '      <br>\n'
    '      <b>只列出状态亮的行</b>（状态灭的已直接隐藏，日志里会写隐藏了几条）。\n'
    '      站点默认 <b>0 ALL</b>（与后台页面一致）：每个产品只出 3 行（PC / Xbox / PS5）。\n'
    '      选具体站点则改该站点自己的价格；选「全部站点」会把 18 个站点铺开 —— 同一产品会出现 54 行，看起来像重复，一般不用。\n'
    '      <br>\n'
    '      <b>图片列</b> 显示的是这个产品<b>当前挂在后台</b>的那张图（就是这个模型前台在用的图）。\n'
    '      <b>勾选</b>要处理的行，再点 <b>「一键添加水印」</b>：工具把图抓下来叠上 MMOEXP 水印，\n'
    '      再<b>写回产品模型</b> —— <b>前台真的会换图</b>（不是只换本地那份）。\n'
    '      同一模型的多行会显示同一张图（模型图<b>全站点共用</b>），所以勾 3 行也只处理 1 次；\n'
    '      已经加过印的会自动跳过，<b>不会叠第二层</b>。\n'
    '    </div>\n'
    '    <div class="row">\n'
    '      <button id="rp_getrate" class="primary" onclick="rpFetchRates()"\n'
    '              title="按区服（PS5 / Xbox / PC）从 MMOEXP 取**最新**每金币价，填进「每金币价」列并重算目标价。\n'
    '· 每次点击都真联网，**不读 30 分钟缓存** —— 所以拿到的就是当前的行情。\n'
    '· 你手改过的行不会被覆盖；若那些值其实是被老版本「保存」冻住的，弹窗里选「确定」可连它们一起覆盖。\n'
    '· 断网时会退回上次取到的价，并在弹窗里写明「联网失败 + 那是哪次取的」—— 绝不拿旧价冒充最新价。">按 MMOEXP 取回最新每金币价</button>\n'
    '      <button onclick="rpFillCoins()" title="把采集结果里同名的金币价填到各行的金币数输入框">用采集的金币价</button>\n'
    '      <button onclick="rpRecalc()">重算目标价</button>\n'
    '      <button onclick="rpPermCheck()" title="只读检查：当前登录账号的角色里有没有改价要用的权限节点（goods/goods/edit）。改价报 401 时先点这个。">权限自检</button>\n'
    '      <span style="flex:1"></span>\n'
    '      <span class="hint" id="rp_counts">未拉取</span>\n'
    '      <button class="danger" onclick="rpApply()">改价（只改亮的行）</button>\n'
    '    </div>\n'
    '    <div class="hint" id="rp_plan"></div>\n'
    '    <div class="scroll" style="margin-top:10px">\n'
    '      <table class="grid">\n'
    '        <thead><tr>\n'
    '          <th><input type="checkbox" id="rp_all" onclick="rpSelectAll(this.checked)" title="全选 / 全不选"></th>\n'
    '          <th>产品名称</th>\n'
    '          <th>图片<br><span class="th-sub">后台现图</span></th>\n'
    '          <th>类目<br><span class="th-sub">cid</span></th>\n'
    '          <th>站点<br><span class="th-sub">site_id</span></th>\n'
    '          <th>区服</th>\n'
    '          <th>每份数量</th><th>现价<br><span class="th-sub">反推每金币价</span></th>\n'
    '          <th>金币数<br><span class="th-sub">可填可存</span></th>\n'
    '          <th>每金币价<br><span class="th-sub">可填可存</span></th>\n'
    '          <th>手续费<br><span class="th-sub">SBC 可逐行改</span></th>\n'
    '          <th>加成<br><span class="th-sub">可逐行改</span></th><th>目标价</th>\n'
    '        </tr></thead>\n'
    '        <tbody id="rp_rows"><tr><td colspan="13" class="hint">还没有数据，先「拉取后台各区现价」</td></tr></tbody>\n'
    '      </table>\n'
    '    </div>\n'
    '\n'
    '    <div class="card">\n'
    '      <h2>⑥ 自动化 · 定时采集改价 / 自动下架</h2>\n'
    '      <div class="auto-grid">\n'
    '        <div class="auto-box" id="auto_pipeline_box">\n'
    '          <div class="auto-head">\n'
    '            <label class="auto-toggle" title="点击开关"><input type="checkbox" id="auto_enabled" onchange="autoSave({enabled: this.checked})">\n'
    '              <span class="auto-slider"></span></label>\n'
    '            <b>自动采集改价</b>\n'
    '            <span class="auto-state" id="auto_pipeline_state">已停用</span>\n'
    '          </div>\n'
    '          <div class="row">\n'
    '            <label>每天</label>\n'
    '            <input type="time" id="auto_run_at" value="01:00" class="w-sm" onchange="autoSave({run_at: this.value})">\n'
    '            <label>执行</label>\n'
    '            <button onclick="autoRun(\'pipeline\')">立即运行一轮</button>\n'
    '          </div>\n'
    '          <div class="row">\n'
    '            <label>上架计价</label>\n'
    '            <label class="hint-inline">加成</label><input id="auto_markup" class="w-xs" placeholder="默认 1.1" onchange="autoSave({markup: this.value})">\n'
    '            <label class="hint-inline">手续费</label><input id="auto_fee" class="w-xs" placeholder="默认 0.24" onchange="autoSave({fee: this.value})">\n'
    '          </div>\n'
    '          <div class="auto-steps" id="auto_steps"></div>\n'
    '          <div class="hint">到点自动执行整条链：<b>① 采集 SBC（FUT.GG）→ ② 采集 Packs（FUTGenie）→\n'
    '            ③ 上架 → ④ 拉取后台各区现价 → ⑤ 一键添加水印 → ⑥ 按 MMOEXP 取回最新每金币价 →\n'
    '            ⑦ 用采集的金币价 → ⑧ 改价</b>。\n'
    '            上架时后台已存在的同名模型自动跳过（含另一 SBC 类目里带 (Non-repeatable) 的旧版）；\n'
    '            <b>水印只加本轮新上架的那几个模型</b>（台账幂等，已加印的自动跳过）；\n'
    '            取每金币价<b>不覆盖</b>你单独手改过的行；改价只动「状态亮的」行。\n'
    '            你正在用工具时（面板忙）会自动推迟，不会抢锁。</div>\n'
    '        </div>\n'
    '        <div class="auto-box" id="auto_delist_box">\n'
    '          <div class="auto-head">\n'
    '            <label class="auto-toggle" title="点击开关"><input type="checkbox" id="auto_delist_enabled" onchange="autoSave({delist_enabled: this.checked})">\n'
    '              <span class="auto-slider"></span></label>\n'
    '            <b>自动下架</b>\n'
    '            <span class="auto-state" id="auto_delist_state">已停用</span>\n'
    '          </div>\n'
    '          <div class="row">\n'
    '            <label>每天</label>\n'
    '            <input type="time" id="auto_delist_at" value="01:00" class="w-sm" onchange="autoSave({delist_at: this.value})">\n'
    '            <label>执行</label>\n'
    '            <button onclick="delistDryRun()">预览（不下架）</button>\n'
    '            <button onclick="autoRun(\'delist\')">立即比对下架</button>\n'
    '          </div>\n'
    '          <div class="row" style="align-items:flex-start">\n'
    '            <label title="每行一个标题，支持 * 通配；写在这里的模型永不自动下架">永不自动下架</label>\n'
    '            <textarea id="auto_delist_protect" rows="3" class="w-lg"\n'
    '                      placeholder="每行一个标题，支持 * 通配（例：ManCity11-* / Premium Season Pass）"\n'
    '                      onchange="autoSave({delist_protect: this.value})"></textarea>\n'
    '          </div>\n'
    '          <div class="row">\n'
    '            <label>添加</label>\n'
    '            <input id="auto_protect_new" class="w-md"\n'
    '                   placeholder="商品标题（支持 * 通配，如 ManCity11-* ）"\n'
    '                   onkeydown="if(event.key===\'Enter\'){event.preventDefault();autoProtectAdd();}">\n'
    '            <button onclick="autoProtectAdd()">加入名单</button>\n'
    '            <span class="hint" id="auto_protect_count"></span>\n'
    '          </div>\n'
    '          <div class="auto-steps" id="auto_delist_steps"></div>\n'
    '          <!-- 最近运行历史：页面日志只留 600 行（约半天）就被冲掉了，回看昨天的执行结果靠这里 -->\n'
    '          <details style="margin-top:10px">\n'
    '            <summary class="hint" style="cursor:pointer;user-select:none">\n'
    '              <b>最近运行</b> <span id="auto_hist_sum">（还没有记录）</span>\n'
    '            </summary>\n'
    '            <div id="auto_hist" class="auto-steps" style="margin-top:6px"><span class="hint">还没有运行历史</span></div>\n'
    '            <div class="hint">采集改价 / 自动下架各算一轮；页面日志只保留最近 600 条，更早的就看这里。</div>\n'
    '          </details>\n'
    '          <div class="hint">拿<b>本轮采集到的 SBC 与 Packs</b> 和<b>后台拉取的模型</b>（产品模型管理 ·\n'
    '            游戏 1327 · 类目 9625 / 9629）按标题比对：<b>没采到的 = 过期</b>，\n'
    '            程序把它的「状态」开关<b>点灭下架</b>。比对时会<b>剥掉 (Non-repeatable) 后缀</b>、\n'
    '            不分类目 —— 后台任一 SBC 类目里有同名就算「还在产」；\n'
    '            <b>手工建的商品请写进上面的「永不自动下架」</b>；\n'
    '            模型列表没拉全时拒绝执行；每个下架都会回读核对。<br>\n'
    '            点「预览（不下架）」可以先看名单再决定 —— 预览一个字节都不写后台。</div>\n'
    '        </div>\n'
    '      </div>\n'
    '    </div>\n'
    '  </div>\n'
    '\n'
    '  <div class="card">\n'
    '    <h2>操作日志</h2>\n'
    '    <pre id="log"></pre>\n'
    '  </div>\n'
    '</main>\n'
    '\n'
    '<div class="mask" id="mask">\n'
    '  <div class="dialog">\n'
    '    <h3>编辑这条 SBC</h3>\n'
    '    <div class="sub" id="dlg_sub"></div>\n'
    '    <div class="dlg-body">\n'
    '      <div>\n'
    '        <div class="preview-box"><img id="dlg_img" alt="" style="display:none"><div class="ph" id="dlg_ph">无图片</div></div>\n'
    '        <div class="drop" onclick="document.getElementById(\'dlg_file\').click()">\n'
    '          点击从本机选一张图（上传后自动转 PNG）\n'
    '          <input type="file" id="dlg_file" accept="image/*" onchange="uploadIcon(this)">\n'
    '        </div>\n'
    '        <div class="hint" style="margin-top:8px">改了「图标地址」会作废已有的本机图；两者只能有一个生效 —— 本机图优先。</div>\n'
    '      </div>\n'
    '      <div>\n'
    '        <div class="field"><label>产品名称（必填）</label><input id="dlg_title"></div>\n'
    '        <div class="field"><label>图标地址</label><input id="dlg_icon_url" placeholder="https://..."></div>\n'
    '        <div class="field"><label>产品摘要</label><textarea id="dlg_summary" rows="2"></textarea></div>\n'
    '        <div class="field"><label>产品描述</label><textarea id="dlg_desc" rows="3"></textarea></div>\n'
    '      </div>\n'
    '    </div>\n'
    '    <div class="dlg-actions">\n'
    '      <button onclick="closeDialog()">取消</button>\n'
    '      <button class="primary" onclick="submitDialog()">保存这条</button>\n'
    '    </div>\n'
    '  </div>\n'
    '</div>\n'
    '\n'
    '<script>\n'
    '// 云端部署时的 URL 前缀（本地为空串）。所有 API 调用都经 api() / BASE 拼接。\n'
    'const BASE = __BASE_PREFIX__;\n'
    '</script>\n'
    '<script>\n'
    'let logSince = 0, status = null, ROWS = [];\n'
    '\n'
    '// 统一登录过期时，nginx 会把请求 302 到登录页 ⇒ 前端拿到的是 HTML。\n'
    '// 以前只报「响应不是 JSON」，谁看都懵（2026-10-16 用户反馈）。\n'
    'let __loginExpiredShownAt = 0;\n'
    'function showLoginExpired() {\n'
    "  const bar = document.getElementById('login_expired_bar');\n"
    "  if (bar) { bar.style.display = 'block'; return; }\n"
    "  const el = document.createElement('div');\n"
    "  el.id = 'login_expired_bar';\n"
    "  el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#b3261e;'\n"
    "    + 'color:#fff;padding:10px 14px;font-size:14px;text-align:center;cursor:pointer;'\n"
    "    + 'box-shadow:0 2px 8px rgba(0,0,0,.35)';\n"
    "  el.textContent = '⚠️ 统一登录已过期（请求被转到登录页）—— 点这里重新登录';\n"
    '  el.onclick = () => { location.href = location.pathname; };\n'
    '  document.body.appendChild(el);\n'
    '  if (Date.now() - __loginExpiredShownAt > 60000) {\n'
    '    __loginExpiredShownAt = Date.now();\n'
    "    addLocal('[错误] 统一登录已过期：点顶部红条或刷新页面重新登录'\n"
    "             + '（登录时勾「记住我」可 30 天免登录）');\n"
    '  }\n'
    '}\n'
    '\n'
    'async function api(path, body) {\n'
    '  const res = await fetch(BASE + path, {\n'
    "    method: 'POST', headers: {'Content-Type':'application/json'},\n"
    '    body: JSON.stringify(body || {})\n'
    '  });\n'
    "  const ctype = (res.headers.get('content-type') || '');\n"
    "  if (!ctype.includes('json')) {\n"
    '    // 不是 JSON：八成被重定向到统一登录页了（会话过期 / 未登录）\n'
    '    showLoginExpired();\n'
    "    return {ok: false, error: '统一登录已过期，请刷新页面重新登录'};\n"
    '  }\n'
    "  const data = await res.json().catch(() => ({ok:false, error:'响应不是 JSON'}));\n"
    "  if (!data.ok && data.error) addLocal('[错误] ' + data.error);\n"
    '  return data;\n'
    '}\n'
    '\n'
    'function addLocal(text) {\n'
    "  const box = document.getElementById('log');\n"
    '  const d = new Date();\n'
    "  const pad = n => String(n).padStart(2, '0');\n"
    '  const stamp = `[${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}] `;\n'
    "  box.textContent += (box.textContent ? '\\n' : '') +\n"
    "    String(text).split('\\n').map(l => stamp + l).join('\\n');\n"
    '  box.scrollTop = box.scrollHeight;\n'
    '}\n'
    '\n'
    'function show(data) {\n'
    '  if (!data) return;\n'
    "  if (data.scope) document.getElementById('scope').textContent = data.scope.split('\\n')[0];\n"
    "  if (typeof data.selected_ready === 'number') {\n"
    "    document.getElementById('plan').textContent =\n"
    '      `已勾选 ${data.selected} / 共 ${data.count ?? data.total} 条 → ` +\n'
    '      `可新增 ${data.selected_ready}、后台已存在 ${data.selected_duplicate}；` +\n'
    '      `(全部行中可新增 ${data.ready}、已存在 ${data.duplicates}、无效 ${data.invalid})`;\n'
    '  }\n'
    '  if (data.rows) renderRows(data.rows);\n'
    "  if (data.path) document.getElementById('import_path').value = data.path;\n"
    "  if (typeof data.dirty === 'boolean') setDirty(data.dirty);\n"
    "  if (typeof data.selected === 'number' && !data.rows) updateCounts(data.selected);\n"
    '}\n'
    '\n'
    'function setDirty(dirty) {\n'
    "  const btn = document.getElementById('save_btn');\n"
    '  btn.disabled = !dirty;\n'
    "  const tag = document.getElementById('dirty');\n"
    "  tag.className = dirty ? 'hint warn' : 'hint';\n"
    "  tag.textContent = dirty ? '● 有未保存的改动（还没写回导入表）' : '已与导入表一致';\n"
    '}\n'
    '\n'
    'function updateCounts(selected) {\n'
    '  const total = ROWS.length;\n'
    "  document.getElementById('counts').textContent = `已勾选 ${selected} / 共 ${total} 条`;\n"
    "  const head = document.getElementById('check_all');\n"
    '  head.checked = total > 0 && selected === total;\n'
    '  head.indeterminate = selected > 0 && selected < total;\n'
    '}\n'
    '\n'
    'const esc = s => String(s ?? \'\').replace(/[&<>"\']/g,\n'
    '  c => ({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[c]));\n'
    '\n'
    'function statusClass(s) {\n'
    "  s = String(s || '');\n"
    "  if (s.includes('失败') || s.includes('无效')) return 'bad';\n"
    "  if (s.includes('已存在')) return 'warn';\n"
    "  if (s.includes('新增') || s.includes('上架')) return 'ok';\n"
    "  return '';\n"
    '}\n'
    '\n'
    'function imgFail(el) { el.outerHTML = \'<span class="thumb missing">无图</span>\'; }\n'
    '\n'
    'function renderRows(rows) {\n'
    '  ROWS = rows || [];\n'
    "  const body = document.getElementById('rows');\n"
    '  if (!ROWS.length) {\n'
    '    body.innerHTML = \'<tr><td colspan="8" class="hint">没有数据，先「重新载入」或采集</td></tr>\';\n'
    '    updateCounts(0);\n'
    '    return;\n'
    '  }\n'
    '  body.innerHTML = ROWS.map(r => {\n'
    '    const uid = esc(r.uid);\n'
    '    const thumb = r.has_icon\n'
    '      ? `<img class="thumb" loading="lazy" alt="" src="${BASE}/api/icon?uid=${encodeURIComponent(r.uid)}&t=${esc(r.icon_rev)||0}" onerror="imgFail(this)">`\n'
    '      : \'<span class="thumb missing">无图</span>\';\n'
    '    return `<tr class="${r.selected ? \'\' : \'sel-off\'}">\n'
    '      <td><input type="checkbox" ${r.selected ? \'checked\' : \'\'} onchange="toggleRow(\'${uid}\', this.checked)"></td>\n'
    '      <td>${thumb}</td>\n'
    '      <td>${esc(r.title)}${r.remark ? \' <span class="hint">\' + esc(r.remark) + \'</span>\' : \'\'}${r.local_icon ? \' <span class="hint">·本机图</span>\' : \'\'}</td>\n'
    "      <td>${r.coins ?? ''}</td>\n"
    "      <td>${r.price ? '$' + esc(r.price) : ''}</td>\n"
    '      <td class="${statusClass(r.status)}">${esc(r.status)}</td>\n'
    '      <td>${esc(r.model_id)}</td>\n'
    '      <td style="white-space:nowrap">\n'
    '        <button class="mini" onclick="openDialog(\'${uid}\')">改标题/图</button>\n'
    '        <button class="mini danger" onclick="deleteRow(\'${uid}\')">删除</button>\n'
    '      </td>\n'
    '    </tr>`;\n'
    "  }).join('');\n"
    '  updateCounts(ROWS.filter(r => r.selected).length);\n'
    '}\n'
    '\n'
    '// ---- 勾选 ----\n'
    'async function selectAll(value) {\n'
    "  show(await api('/api/rows/select', { all: value }));\n"
    '}\n'
    'async function toggleRow(uid, checked) {\n'
    "  const data = await api('/api/rows/select', { uid: uid, selected: checked });\n"
    '  if (!data.ok) { renderRows(ROWS); return; }\n'
    '  renderRows(data.rows);\n'
    '  setDirty(data.dirty);\n'
    '}\n'
    '\n'
    '// ---- 删除 ----\n'
    'async function deleteRow(uid) {\n'
    '  const row = ROWS.find(r => r.uid === uid);\n'
    "  const name = row ? row.title : '这条';\n"
    '  if (!confirm(`把「${name}」从待上架列表里删掉？\\n\\n只影响当前列表，点「保存改动」后才会写回导入表。`)) return;\n'
    "  show(await api('/api/rows/delete', { uid: uid }));\n"
    '}\n'
    '\n'
    '// ---- 编辑弹窗 ----\n'
    "let editingUid = '';\n"
    '\n'
    'function openDialog(uid) {\n'
    '  const row = ROWS.find(r => r.uid === uid);\n'
    '  if (!row) return;\n'
    '  editingUid = uid;\n'
    "  document.getElementById('dlg_sub').textContent =\n"
    "    `SBC ID ${row.sbc_id || '-'} · 金币价 ${row.coins ?? '-'} · 单价 ${row.price ? '$' + row.price : '-'}` +\n"
    "    (row.model_id ? ` · 模型 ID ${row.model_id}` : '');\n"
    "  document.getElementById('dlg_title').value = row.title || '';\n"
    "  document.getElementById('dlg_icon_url').value = row.icon_url || '';\n"
    "  document.getElementById('dlg_summary').value = row.summary || '';\n"
    "  document.getElementById('dlg_desc').value = row.description || '';\n"
    "  document.getElementById('dlg_file').value = '';\n"
    '  setDialogImage(row.has_icon\n'
    '    ? `/api/icon?uid=${encodeURIComponent(uid)}&t=${row.icon_rev || Date.now()}`\n'
    "    : '');\n"
    "  document.getElementById('mask').classList.add('on');\n"
    '}\n'
    '\n'
    'function setDialogImage(src) {\n'
    "  const img = document.getElementById('dlg_img'), ph = document.getElementById('dlg_ph');\n"
    "  if (src) { img.src = src; img.style.display = 'block'; ph.style.display = 'none'; }\n"
    "  else { img.removeAttribute('src'); img.style.display = 'none'; ph.style.display = 'block'; }\n"
    "  img.onerror = () => { img.style.display = 'none'; ph.style.display = 'block'; };\n"
    '}\n'
    '\n'
    'function closeDialog() {\n'
    "  document.getElementById('mask').classList.remove('on');\n"
    "  editingUid = '';\n"
    '}\n'
    '\n'
    'async function submitDialog() {\n'
    "  const data = await api('/api/rows/update', {\n"
    '    uid: editingUid,\n'
    "    title: document.getElementById('dlg_title').value,\n"
    "    icon_url: document.getElementById('dlg_icon_url').value,\n"
    "    summary: document.getElementById('dlg_summary').value,\n"
    "    description: document.getElementById('dlg_desc').value\n"
    '  });\n'
    '  if (!data.ok) return;\n'
    '  renderRows(data.rows);\n'
    '  setDirty(data.dirty);\n'
    '  closeDialog();\n'
    '}\n'
    '\n'
    '// ---- 上传本机图片 ----\n'
    '//\n'
    "// ⚠️ 这里那个 `input.value = ''` 必须在**任何 await 之前**、并且**无论成败**都要执行。\n"
    '//    2026-10-03 用户报「上架载入的产品不能更换图片了 / 选了图但画面上没变」，\n'
    '//    根因就是它被放在了最后一行、只在成功分支上：\n'
    '//      · 上传失败（超过 6MB、不是有效图片、服务端报错）会在 `return` 处提前退出，\n'
    '//        value 留在那儿不清；\n'
    '//      · 浏览器对 <input type="file"> 的规矩是：**值没变就不触发 change**。\n'
    '//      · 于是用户"再选一次同一张图重试" → 连 change 都不触发 → 界面一动不动，\n'
    '//        服务端日志里连一条记录都没有 —— 看起来就是"换图功能坏了"。\n'
    '//    现在：进函数先把 value 清掉，后面出什么事都不影响下一次选择能触发。\n'
    'async function uploadIcon(input) {\n'
    '  const file = input.files && input.files[0];\n'
    "  input.value = '';\n"
    '\n'
    '  if (!file) return;\n'
    "  const kb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB');\n"
    '  if (file.size > 6 * 1024 * 1024) {\n'
    '    addLocal(`[错误] 「${file.name}」${kb(file.size)}，超过 6MB 上限，请先压缩再传`);\n'
    '    return;\n'
    '  }\n'
    '  addLocal(`[本地] 正在上传 ${file.name}（${kb(file.size)}）…`);\n'
    '\n'
    '  let dataUrl;\n'
    '  try {\n'
    '    dataUrl = await new Promise((resolve, reject) => {\n'
    '      const fr = new FileReader();\n'
    '      fr.onload = () => resolve(fr.result);\n'
    "      fr.onerror = () => reject(new Error('浏览器读不出这个文件'));\n"
    '      fr.readAsDataURL(file);\n'
    '    });\n'
    '  } catch (err) {\n'
    '    addLocal(`[错误] 读取「${file.name}」失败：${err.message}`);\n'
    '    return;\n'
    '  }\n'
    '\n'
    "  const res = await api('/api/rows/icon', { uid: editingUid, data: dataUrl, name: file.name });\n"
    '  if (!res.ok) { addLocal(`[错误] 「${file.name}」上传失败，图片没有换掉`); return; }\n'
    '\n'
    '  renderRows(res.rows);\n'
    '  setDirty(res.dirty);\n'
    '  setDialogImage(`/api/icon?uid=${encodeURIComponent(editingUid)}&t=${Date.now()}`);\n'
    '  // 回执里写上"你选的那个文件名"，并且当新图和旧图字节完全一样时明确说一句 ——\n'
    '  // 用户最常见的困惑就是"我选了图啊"，其实选中的还是上一张。\n'
    '  addLocal(`[本地] 已上传 ${file.name} → ${res.name}（${kb(res.size)}，${res.width}×${res.height}）` +\n'
    "    (res.same_as_previous ? '。⚠️ 和替换前那张一模一样，画面看着不会变' : ''));\n"
    '}\n'
    '\n'
    '// ---- 图标修复 ----\n'
    'async function fixIcons() {\n'
    "  const btn = document.getElementById('fix_btn');\n"
    "  btn.disabled = true; btn.textContent = '修复中…';\n"
    '  try {\n'
    "    const data = await api('/api/icons/fix', {});\n"
    '    if (data.ok) {\n'
    '      renderRows(data.rows);\n'
    '      addLocal(`[本地] 图片已修复 ${data.fixed} 张` +\n'
    "        (data.attached ? `，挂回 ${data.attached} 条` : '') +\n"
    "        (data.failed ? `，失败 ${data.failed} 张` : '') +\n"
    "        '（裁透明边 → 放大 → 锐化，原始图保留在 cache/icons_raw）');\n"
    '    }\n'
    '  } finally {\n'
    "    btn.disabled = false; btn.textContent = '一键修复图片';\n"
    '  }\n'
    '}\n'
    '\n'
    '// ---- 清理 Item Score 行 ----\n'
    'async function pruneItemScore() {\n'
    "  if (!confirm('按当前 futbin 列表判定类型，删掉导入表里「只有 Item Score」的行？\\n导入表会先备份一份。')) return;\n"
    "  const btn = document.getElementById('prune_btn');\n"
    "  btn.disabled = true; btn.textContent = '清理中…';\n"
    '  try {\n'
    "    const data = await api('/api/rows/prune_item_score', {\n"
    "      path: document.getElementById('import_path').value\n"
    '    });\n'
    '    if (data.ok) {\n'
    '      renderRows(data.rows);\n'
    '      setDirty(false);\n'
    '      addLocal(data.message ? `[本地] ${data.message}`\n'
    '        : `[本地] 已清理 ${data.removed} 条 Item Score 行（导入表已备份）`);\n'
    '    }\n'
    '  } finally {\n'
    "    btn.disabled = false; btn.textContent = '清理 Item Score 行';\n"
    '  }\n'
    '}\n'
    '\n'
    '// ---- 保存 ----\n'
    'async function saveRows() {\n'
    "  if (!confirm('把当前列表（含勾选、改过的标题/图片、删掉的行）写回导入表？\\n原文件会先备份一份。')) return;\n"
    "  const data = await api('/api/rows/save', { path: document.getElementById('import_path').value });\n"
    '  if (data.ok) {\n'
    '    setDirty(false);\n'
    "    addLocal(`[本地] 已保存 ${data.saved} 行` + (data.backup ? `，备份：${data.backup.split(/[\\\\\\\\/]/).pop()}` : ''));\n"
    '  }\n'
    '}\n'
    '\n'
    'async function reloadRows() {\n'
    "  if (!document.getElementById('save_btn').disabled &&\n"
    "      !confirm('重新载入会丢弃还没保存的改动，继续吗？')) return;\n"
    "  const data = await api('/api/rows/reload', { path: document.getElementById('import_path').value });\n"
    '  if (data.ok) { show(data); setDirty(false); }\n'
    '}\n'
    '\n'
    'async function refreshStatus() {\n'
    '  try {\n'
    "    status = await fetch(BASE + '/api/status').then(r => r.json());\n"
    '  } catch (e) { return; }\n'
    "  const badge = document.getElementById('state');\n"
    "  if (status.portal_role !== 'admin') {\n"
    "    badge.textContent = '只读访问 · 操作仅限现有管理员';\n"
    "    document.querySelectorAll('button,input,select,textarea').forEach(el => { el.disabled = true; });\n"
    '    return;\n'
    '  }\n'
    '  if (status.logged_in) {\n'
    "    badge.textContent = status.remembered ? '已登录（已记住，重启免登录）' : '已登录（会话仅在内存）';\n"
    '  } else {\n'
    "    badge.textContent = status.remembered ? '未登录（有保存的登录态）' : '未登录';\n"
    '  }\n'
    "  badge.className = 'badge' + (status.logged_in ? ' on' : '');\n"
    "  const sel = document.getElementById('area');\n"
    '  if (!sel.options.length) {\n'
    "    status.areas.forEach(a => sel.add(new Option(a.aid + ' ' + a.name, a.aid)));\n"
    '    sel.value = status.default_aid;\n'
    "    document.getElementById('markup').value = status.markup;\n"
    "    document.getElementById('base_fee').value = status.base_fee;\n"
    "    document.getElementById('xlsx').value = status.default_xlsx;\n"
    "    document.getElementById('import_path').value = status.rows_path || status.default_xlsx;\n"
    '  }\n'
    "  if (status.scope) document.getElementById('scope').textContent = status.scope.split('\\n')[0];\n"
    '  // ⑤ 面板的「加成 / 全局手续费」也要跟服务端对齐。\n'
    '  // 之前这两个框是写死的 1.1 / 0.24：保存过 1.2 之后一刷新页面就变回 1.1，\n'
    '  // 而表格里每行显示的是**服务端解析出来的生效值** —— 两边对不上，\n'
    '  // 用户会以为「保存没生效」（改全局手续费尤其明显）。\n'
    '  // 只在**初始化那一次**回填，之后不覆盖 —— 用户可能正在改。\n'
    '  if (!RP_CFG_SYNCED && status.reprice_fee != null) {\n'
    '    RP_CFG_SYNCED = true;\n'
    "    const mkBox = document.getElementById('rp_markup');\n"
    "    const feeBox = document.getElementById('rp_fee');\n"
    '    if (mkBox) mkBox.value = status.reprice_markup;\n'
    '    if (feeBox) feeBox.value = status.reprice_fee;\n'
    '  }\n'
    '  // 服务端的"未保存"状态是权威的，轮询时同步一下按钮\n'
    "  if (typeof status.dirty === 'boolean') setDirty(status.dirty);\n"
    '  // 登录后自动补一次站点下拉（只补一次，避免轮询反复重建）\n'
    '  if (status.logged_in && !SITES_LOADED) {\n'
    '    SITES_LOADED = true;\n'
    '    rpLoadSites();\n'
    '  }\n'
    '}\n'
    '\n'
    'async function pollLog() {\n'
    '  try {\n'
    "    const data = await fetch(BASE + '/api/log?since=' + logSince).then(r => r.json());\n"
    '    if (data.lines && data.lines.length) {\n'
    "      const box = document.getElementById('log');\n"
    "      box.textContent += (box.textContent ? '\\n' : '') + data.lines.join('\\n');\n"
    '      box.scrollTop = box.scrollHeight;\n'
    '    }\n'
    '    logSince = data.total ?? logSince;\n'
    '  } catch (e) { /* 服务重启忽略 */ }\n'
    '}\n'
    '\n'
    'async function doFetch() {\n'
    "  const data = await api('/api/fetch', {\n"
    "    path: document.getElementById('xlsx').value,\n"
    "    min_coins: document.getElementById('min_coins').value,\n"
    "    fill_text: document.getElementById('fill_text').checked,\n"
    "    append: document.getElementById('append').checked,\n"
    "    sync_live: document.getElementById('sync_live').checked\n"
    '  });\n'
    '  if (data.ok) {\n'
    "    document.getElementById('import_path').value = data.path || document.getElementById('import_path').value;\n"
    "    document.getElementById('xlsx').value = data.path || document.getElementById('xlsx').value;\n"
    '    show(data);\n'
    '    setDirty(false);\n'
    '    // 采到 0 行时最容易懵：把「闸门挡掉多少 / 对齐动了谁」摊开说清楚\n'
    '    const s = data.stats || {};\n'
    '    const gates = [];\n'
    '    if (s.no_price) gates.push(`无金币价 ${s.no_price} 个`);\n'
    '    if (s.min_coins) gates.push(`金币价 ≤ 下限 ${s.min_coins} 个`);\n'
    '\n'
    '    // 「和采集站对齐」的结果必须摊开说 —— 自动删了用户的行却不告诉他，\n'
    '    // 他会以为工具偷偷弄丢了他的数据。\n'
    '    const y = data.sync || {};\n'
    '    const syncLines = [];\n'
    '    if (y.dropped && y.dropped.length) {\n'
    "      syncLines.push(`已下架、删掉 ${y.dropped.length} 行：${y.dropped.join('、')}`);\n"
    '    }\n'
    '    if (y.adopted && y.adopted.length) {\n'
    "      syncLines.push(`按标题收编旧 futbin 行 ${y.adopted.length} 行：${y.adopted.slice(0, 6).join('、')}${y.adopted.length > 6 ? ' 等' : ''}`);\n"
    '    }\n'
    '    if (y.refreshed && y.refreshed.length) {\n'
    "      const names = y.refreshed.slice(0, 6).map(r => r[0]).join('、');\n"
    "      syncLines.push(`刷新了 ${y.refreshed.length} 行的金币价/到期/分类：${names}${y.refreshed.length > 6 ? ' 等' : ''}`);\n"
    '    }\n'
    '    if (y.kept_blind) {\n'
    '      syncLines.push(`⚠️ 列表没抓完整，${y.kept_blind} 行「不在列表里」的**保留**未删（怕误删）`);\n'
    '    }\n'
    '\n'
    '    const lines = [];\n'
    '    if (gates.length) {\n'
    "      lines.push('被挡掉的：');\n"
    "      gates.forEach(g => lines.push('· ' + g));\n"
    "      lines.push('');\n"
    "      lines.push('⚠️ 唯一的闸门是「金币价下限」，保留的是**比它贵**的，想收便宜的把下限调小。');\n"
    '    }\n'
    '    if (syncLines.length) {\n'
    "      if (lines.length) lines.push('');\n"
    "      lines.push('和采集站对齐：');\n"
    "      syncLines.forEach(l => lines.push('· ' + l));\n"
    "      lines.push('');\n"
    "      lines.push('（旧行删掉后，同名的新一期 SBC 才能进表 —— 否则会被「按产品名称去重」挡住。）');\n"
    '    }\n'
    '    if (lines.length) {\n'
    "      alert(`扫描 ${s.scanned ?? '?'} 个 SBC，通过 ${s.passed ?? data.added ?? 0} 个（Players ${s.players ?? 0} / 其余 ${s.upgrades ?? 0}）。\\n\\n` + lines.join('\\n'));\n"
    '    }\n'
    '  }\n'
    '}\n'
    '\n'
    'async function doFetchPacks() {\n'
    "  const data = await api('/api/fetch_packs', {\n"
    "    path: document.getElementById('xlsx').value,\n"
    "    fill_text: document.getElementById('fill_text').checked,\n"
    "    append: document.getElementById('append').checked,\n"
    "    sync_live: document.getElementById('sync_live').checked\n"
    '  });\n'
    '  if (data.ok) {\n'
    "    document.getElementById('import_path').value = data.path || document.getElementById('import_path').value;\n"
    "    document.getElementById('xlsx').value = data.path || document.getElementById('xlsx').value;\n"
    '    show(data);\n'
    '    setDirty(false);\n'
    '    const s = data.stats || {};\n'
    '    const y = data.sync || {};\n'
    '    const lines = [];\n'
    "    lines.push(`FUTGenie 列表 ${s.scanned + s.no_time ?? '?'} 个 pack，右上角有倒计时的 ${s.scanned ?? '?'} 个，采到金币价的 ${s.passed ?? data.added ?? 0} 个。`);\n"
    '    if (s.no_time) lines.push(`跳过（无倒计时，不在架上架中） ${s.no_time} 个`);\n'
    '    if (s.no_price) lines.push(`跳过（详情里拿不到金币价） ${s.no_price} 个`);\n'
    '    if (s.detail_error) lines.push(`详情抓取失败 ${s.detail_error} 个`);\n'
    '    if (y.dropped && y.dropped.length) {\n'
    "      lines.push('');\n"
    "      lines.push(`已过期、删掉 ${y.dropped.length} 行：${y.dropped.join('、')}`);\n"
    '    }\n'
    '    if (y.refreshed && y.refreshed.length) {\n'
    '      lines.push(`刷新了 ${y.refreshed.length} 行`);\n'
    '    }\n'
    "    alert(lines.join('\\n'));\n"
    '  }\n'
    '}\n'
    '\n'
    'async function refreshPrice() {\n'
    "  const data = await api('/api/pricing', { aid: Number(document.getElementById('area').value) });\n"
    "  if (data.ok) document.getElementById('unit_price').value = data.unit_price_per_1k;\n"
    '}\n'
    '\n'
    'function priceBody() {\n'
    '  return {\n'
    "    aid: Number(document.getElementById('area').value),\n"
    "    unit_price: document.getElementById('unit_price').value,\n"
    "    markup: document.getElementById('markup').value,\n"
    "    base_fee: document.getElementById('base_fee').value,\n"
    "    skip_existing: document.getElementById('skip_existing').checked,\n"
    "    path: document.getElementById('import_path').value\n"
    '  };\n'
    '}\n'
    '\n'
    "async function doPreview() { show(await api('/api/preview', priceBody())); }\n"
    '\n'
    'async function doExecute() {\n'
    '  if (ROWS.length && !ROWS.some(r => r.selected)) {\n'
    "    alert('一条都没勾选。先在上面的表格里勾选要上架的 SBC。');\n"
    '    return;\n'
    '  }\n'
    "  if (!confirm('即将对【已勾选】的 SBC 执行：新增产品模型 + 站点全选(17) + 服务区全选(3)。\\n' +\n"
    "               '上架后商品会对顾客可见、可下单。\\n\\n确定继续吗？')) return;\n"
    "  show(await api('/api/execute', priceBody()));\n"
    '}\n'
    '\n'
    'function downloadTable() {\n'
    "  const path = document.getElementById('import_path').value;\n"
    "  location.href = BASE + '/api/download?path=' + encodeURIComponent(path);\n"
    '}\n'
    '\n'
    '// ---------------------- ⑤ 按区改价 ----------------------\n'
    'let GGOODS = [];       // 后台拉回来的在售行\n'
    'let RP_SEL = new Set(); // 勾选的 goods_id\n'
    'let SITES_LOADED = false;\n'
    '// ⑤ 面板的「加成 / 全局手续费」是否已经从 /api/status 回填过一次。\n'
    '// 只回填一次：之后用户可能正在框里改，轮询不该把它冲掉。\n'
    'let RP_CFG_SYNCED = false;\n'
    '\n'
    '// ---- 「图片」列 + 一键添加水印 ----\n'
    '// RP_ICON[mid] = {icon, url, title, watermarked} —— 这个模型**当前挂在后台**的图。\n'
    '// 按**模型**缓存：同一模型的 3 个区服行共用一条，不重复问后台。\n'
    'let RP_ICON = {};\n'
    '// 正在拉取中，防抖 —— renderRp() 会被频繁调用，不能每渲染一次就发一轮请求。\n'
    'let RP_ICONS_BUSY = false;\n'
    '// 拉取期间又来了一批 mid：排这儿，等这一轮回来再拉（否则它们会永远停在「…」上）。\n'
    'let RP_ICONS_QUEUE = [];\n'
    '// 一键添加水印正在跑：避免连点两下（第二下会在刚加好的图上再叠一层）。\n'
    'let RP_WM_BUSY = false;\n'
    '\n'
    'function rpNum(v) { const n = parseFloat(v); return isFinite(n) ? n : null; }\n'
    '\n'
    '// 每金币价通常小到 1e-4 量级，用 8 位小数显示（与后端 implied_per_coin 同口径）\n'
    'function rpRate(v) {\n'
    '  const n = rpNum(v);\n'
    "  return n === null ? '' : String(n);\n"
    '}\n'
    '\n'
    '// 由「现价 ÷ num ÷ 金币数」反推后台当前合多少每金币 —— 纯对比展示\n'
    'function rpImplied(r) {\n'
    '  const price = rpNum(r.price), num = rpNum(r.num) || 1, coins = rpNum(r.coins);\n'
    "  if (price === null || coins === null || coins === 0) return '';\n"
    '  return (price / (num || 1) / coins).toFixed(8);\n'
    '}\n'
    '\n'
    '// 本行实际用到的固定手续费：只有 SBC 加，Packs 恒为 0（与后端 fee_applies 同规则）\n'
    "function rpFeeApplies(r) { return r.kind === 'SBC'; }\n"
    '\n'
    '// 这一行的手续费是不是「被单独设过」（服务端持久化的，或本次会话在表格里改的）。\n'
    '// 和 rpRateIsOwn 一样的用途：改**全局**手续费时只该刷新没被单独设过的行。\n'
    'function rpFeeIsOwn(r) {\n'
    '  if (!rpFeeApplies(r)) return false;\n'
    '  return !!(r.fee_own || r.fee_edited);\n'
    '}\n'
    '\n'
    '// 本行**实际**用的手续费：\n'
    '//   被单独设过 / 表格里填了值 -> 用那一格的值\n'
    '//   否则                     -> 回落顶部那个全局框（空则 0.24）\n'
    '// 注意这是「生效值」，与后端 GoodsRow.fee_applied 同一口径。\n'
    'function rpFeeOf(r) {\n'
    '  if (!rpFeeApplies(r)) return 0;\n'
    '  const own = rpNum(r.fee);\n'
    '  if (own !== null) return own;\n'
    "  const f = rpNum(document.getElementById('rp_fee').value);\n"
    '  return f === null ? 0.24 : f;\n'
    '}\n'
    '\n'
    '// 改「全局手续费」：只有**没被单独设过**的 SBC 行跟着变。\n'
    '// 单独设过的行（fee_own / fee_edited）必须原样留着 —— 否则用户给某个 SBC\n'
    '// 特意定的费会被顺手冲掉，而且他自己不会发现。\n'
    'function rpFeeChanged() {\n'
    "  const v = document.getElementById('rp_fee').value;\n"
    '  GGOODS.forEach(r => {\n'
    '    if (rpFeeApplies(r) && !rpFeeIsOwn(r)) r.fee = v;\n'
    '    rpRecalcOne(r);\n'
    '  });\n'
    '  renderRp(); rpPlan();\n'
    '}\n'
    '\n'
    '// —— 加成（逐行可覆盖，2026-10-06 起）——\n'
    '// 与手续费同一套机制，只有两点不同：\n'
    '//   ① 加成**不分类目**：SBC / Packs 都乘它，所以这里没有 rpFeeApplies 那种判断；\n'
    '//   ② 合法值必须 > 0（0 会让目标价直接变 0 = 白送），后端也是这么拦的。\n'
    '//\n'
    '// 这一行的加成是不是「被单独设过」（服务端持久化的，或本次会话在表格里改的）。\n'
    '// 和 rpFeeIsOwn 一样：改**全局**加成时只该刷新没被单独设过的行。\n'
    'function rpMarkupIsOwn(r) { return !!(r.markup_own || r.markup_edited); }\n'
    '\n'
    '// 本行**实际**用的加成：\n'
    '//   单独设过 / 表格里填了值 -> 用那一格的值\n'
    '//   否则                   -> 回落顶部那个全局框（空则 1.1）\n'
    '// 注意这是「生效值」，与后端 GoodsRow.markup 同一口径。\n'
    'function rpMarkupOf(r) {\n'
    '  const own = rpNum(r.markup);\n'
    '  if (own !== null) return own;\n'
    "  const m = rpNum(document.getElementById('rp_markup').value);\n"
    '  return m === null ? 1.1 : m;\n'
    '}\n'
    '\n'
    '// 改「全局加成」：只有**没被单独设过**的行跟着变。\n'
    '// 单独设过的行（markup_own / markup_edited）必须原样留着 —— 否则用户给某一行\n'
    '// 特意定的倍数会被顺手冲掉，而且他自己不会发现（和手续费那个坑一模一样）。\n'
    'function rpMarkupChanged() {\n'
    "  const v = document.getElementById('rp_markup').value;\n"
    '  GGOODS.forEach(r => {\n'
    '    if (!rpMarkupIsOwn(r)) r.markup = v;\n'
    '    rpRecalcOne(r);\n'
    '  });\n'
    '  renderRp(); rpPlan();\n'
    '}\n'
    '\n'
    'function rpSelectAll(on) {\n'
    '  RP_SEL = new Set();\n'
    '  if (on) GGOODS.forEach(r => { if (r.live) RP_SEL.add(r.goods_id); });\n'
    '  renderRp();\n'
    '}\n'
    '\n'
    'function rpToggle(id, on) {\n'
    '  if (on) RP_SEL.add(id); else RP_SEL.delete(id);\n'
    '  renderRp();\n'
    '}\n'
    '\n'
    'function rpSetCoins(id, v) {\n'
    '  const row = GGOODS.find(r => r.goods_id === id);\n'
    '  if (row) { row.coins = v; rpRecalcOne(row); }\n'
    '  renderRp();\n'
    '}\n'
    '\n'
    'function rpSetRate(id, v) {\n'
    '  const row = GGOODS.find(r => r.goods_id === id);\n'
    '  if (row) {\n'
    '    row.rate = v;\n'
    '    // 本次会话手改过 —— 之后的「按 MMOEXP 带出」不许把它盖掉\n'
    '    row.rate_edited = true;\n'
    '    rpRecalcOne(row);\n'
    '  }\n'
    '  renderRp();\n'
    '}\n'
    '\n'
    '// 逐行改手续费。清空（空串）不是「当成 0」，而是「取消单独设置、回落全局值」——\n'
    '// 这是两个完全不同的定价结果，所以这里原样保留空串，由 rpFeeOf 去回落。\n'
    'function rpSetFee(id, v) {\n'
    '  const row = GGOODS.find(r => r.goods_id === id);\n'
    '  if (row) {\n'
    '    row.fee = v;\n'
    '    // 本次会话手改过 —— 之后改全局手续费不许把它盖掉\n'
    '    row.fee_edited = true;\n'
    '    rpRecalcOne(row);\n'
    '  }\n'
    '  renderRp(); rpPlan();\n'
    '}\n'
    '\n'
    '// 逐行改加成。清空（空串）不是「当成 0」，而是「取消单独设置、回落全局值」——\n'
    '// 与 rpSetFee 同一口径：这里原样保留空串，由 rpMarkupOf 去回落。\n'
    '// （加成填 0 本身是非法值，后端会拒；清空才是"取消覆盖"。）\n'
    'function rpSetMarkup(id, v) {\n'
    '  const row = GGOODS.find(r => r.goods_id === id);\n'
    '  if (row) {\n'
    '    row.markup = v;\n'
    '    // 本次会话手改过 —— 之后改全局加成不许把它盖掉\n'
    '    row.markup_edited = true;\n'
    '    rpRecalcOne(row);\n'
    '  }\n'
    '  renderRp(); rpPlan();\n'
    '}\n'
    '\n'
    '// 这一行的每金币价是不是「用户自己的值」（手改的），而不是 MMOEXP 带出的默认值。\n'
    '//   rate_own    —— 服务端记录的：逐产品手改过（持久化的）\n'
    '//   rate_edited —— 本次会话里在表格里改过（还没保存）\n'
    '// 两者取或。重新带出行情时，自己的值不动，带出的值才刷新。\n'
    'function rpRateIsOwn(r) { return !!(r.rate_own || r.rate_edited); }\n'
    '\n'
    '// SBC  : 目标价 = (金币数 × 每金币价 + 手续费) × 加成\n'
    '// Packs: 目标价 = (金币数 × 每金币价)          × 加成      ← 手续费恒为 0\n'
    '// 注意用的是 r.rate（外部给的市场每金币价），**不是** r.per_coin（那是反推的对比值）。\n'
    '// 拿 per_coin 当输入会让金币数在公式里被约掉，这是之前「重算没反应」的根因。\n'
    '//\n'
    '// 加成走 rpMarkupOf(row) —— **不是**直接读顶部那个全局框。\n'
    '// 逐行加成（表格「加成」列）就靠这一行生效；读全局框的话，用户单独给某一行\n'
    '// 设了 1.5，画面上显示 1.5、算出来却是全局 1.3，你确认的价和提交的价就是两个数。\n'
    'function rpRecalcOne(row) {\n'
    '  const coins = rpNum(row.coins);\n'
    '  const rate = rpNum(row.rate);\n'
    '  const markup = rpMarkupOf(row);\n'
    '  // ⚠️ **绝对不要**在这里写 `row.markup = String(markup)`。\n'
    '  //    那一格存的是**用户填的原文**（可能是空串 = "取消单独设置"），\n'
    '  //    写回生效值就把空串冲成了全局值 —— 保存时发出去的是 "1.1" 而不是 ""，\n'
    '  //    后端于是给它存下一个 1.1 的覆盖值，这一行就永久冻在 1.1 上，\n'
    '  //    之后再改全局加成它都不动了（和 rate 被"保存"冻住是同一个病）。\n'
    '  //    手续费那边是靠"只写 fee_applied、不碰 fee"绕开的，这里同理：\n'
    '  //    生效值由 rpMarkupOf() 现算，输入框读 r.markup 原文，两者各管一头。\n'
    '  row.fee_applied = String(rpFeeOf(row));\n'
    "  if (coins === null || rate === null) { row.target = ''; return; }\n"
    '  // 手续费在乘法之后、加成之前加\n'
    '  row.target = ((coins * rate + rpFeeOf(row)) * markup).toFixed(2);\n'
    '}\n'
    '\n'
    'function rpRecalc() {\n'
    '  GGOODS.forEach(r => rpRecalcOne(r));\n'
    '  renderRp();\n'
    '  rpPlan();\n'
    '}\n'
    '\n'
    'async function rpLoadSites() {\n'
    '  try {\n'
    "    const d = await api('/api/sites', {});\n"
    '    if (!d.ok) return;\n'
    "    const sel = document.getElementById('rp_site');\n"
    "    const cur = sel.value || '0';\n"
    '    sel.innerHTML = \'<option value="0">0 ALL（改价用）</option>\' +\n'
    '      (d.sites || []).filter(s => s.id !== 0)\n'
    '        .map(s => `<option value="${s.id}">${s.id} · ${esc(s.name)}</option>`).join(\'\') +\n'
    '      \'<option value="all">全部站点（慢，会重复）</option>\';\n'
    '    sel.value = cur;\n'
    '  } catch (e) { /* 静默：站点列表拿不到不影响手填 */ }\n'
    '}\n'
    '\n'
    '// 权限自检：只读。回答「改价报 401 到底是缺哪个权限节点」。\n'
    'async function rpPermCheck() {\n'
    '  let d;\n'
    '  try {\n'
    "    d = await api('/api/permcheck', {});\n"
    '  } catch (e) {\n'
    "    alert('权限自检失败：' + e.message);\n"
    '    return;\n'
    '  }\n'
    "  if (!d.ok) { alert(d.error || '权限自检失败'); return; }\n"
    '\n'
    "  let msg = `账号：${d.username}（${d.nickname || '—'}）\\n` +\n"
    "            `是否超级管理员：${d.super ? '是（不受权限节点限制）' : '否'}\\n` +\n"
    '            `角色被授予的规则节点：${d.rule_count} 个\\n\\n`;\n'
    '  (d.checks || []).forEach(c => {\n'
    "    msg += `${c.has ? '✅' : '❌'} ${c.rule}\\n` +\n"
    '           `     用途：${c.what}\\n` +\n'
    "           (c.has ? (c.why ? `     说明：${c.why}\\n` : '')\n"
    '                  : `     该去哪勾：${c.where}\\n`);\n'
    '  });\n'
    "  msg += '\\n';\n"
    '  if (d.can_reprice) {\n'
    "    msg += '结论：改价权限齐全。若仍报 401，请把弹窗里的原始报文发出来。';\n"
    '  } else {\n'
    "    msg += '结论：缺上面的 ❌ 节点，所以改价会一直 401。\\n\\n' +\n"
    "           '改价要的是 goods/goods/edit（就是「产品管理」页行内那个「编辑」按钮）。\\n' +\n"
    "           '让有最高权限的同事在「权限管理 → 菜单规则」里给「产品管理」授权「编辑」，\\n' +\n"
    "           '或者直接换一个 super 账号登录本工具 —— 后者代码一行都不用改。\\n\\n' +\n"
    "           '⚠️ 若在权限管理里**找不到**「编辑」这一项：说明后台规则表里没建，\\n' +\n"
    "           '   那就只能让最高权限账号补建，或换 super 账号。';\n"
    '  }\n'
    '  alert(msg);\n'
    '}\n'
    '\n'
    'async function rpLoad() {\n'
    "  const btn = document.getElementById('rp_load');\n"
    "  btn.disabled = true; btn.textContent = '拉取中…';\n"
    '  try {\n'
    "    const kind = document.getElementById('rp_mode').value;\n"
    "    const site = document.getElementById('rp_site').value;\n"
    "    const d = await api('/api/goods', { kind, site });\n"
    "    if (!d.ok) { alert(d.error || '拉取失败'); return; }\n"
    '    GGOODS = d.rows || [];\n'
    '    RP_SEL = new Set();\n'
    '    GGOODS.forEach(r => rpRecalcOne(r));\n'
    '    renderRp(); rpPlan();\n'
    '    // 图片列：现问一遍后台。fresh=true —— 重新拉了就该反映后台**现在**的图，\n'
    '    // 而不是上一次拉取时缓存的那张（别人可能已经改过图了）。\n'
    '    rpLoadIcons(GGOODS.map(r => r.model_id), { fresh: true });\n'
    "    const sbc = GGOODS.filter(r => r.kind === 'SBC').length;\n"
    "    const pack = GGOODS.filter(r => r.kind === 'Packs').length;\n"
    '    const titles = new Set(GGOODS.map(r => r.title)).size;\n'
    '    // 「几个模型」这一项对水印很关键：模型图按模型共用，勾 3 行往往只对应 1 个模型。\n'
    '    const models = new Set(GGOODS.map(r => r.model_id).filter(Boolean)).size;\n'
    '    const noRate = GGOODS.filter(r => rpNum(r.rate) === null).length;\n'
    "    document.getElementById('rp_counts').textContent =\n"
    '      `${titles} 个产品 / ${GGOODS.length} 行（SBC ${sbc} / Packs ${pack}，${models} 个模型）` +\n'
    "      (noRate ? ` · ${noRate} 行缺每金币价` : '');\n"
    '    // 一行都没拿到每金币价时，直说下一步该干嘛，别让人对着「—」猜\n'
    '    if (noRate === GGOODS.length && GGOODS.length) {\n'
    "      alert('已拉到在售行，但还没有「每金币价」，所以目标价算不出来。\\n\\n' +\n"
    "            '点「按 MMOEXP 取回最新每金币价」自动填，或直接在表格里手填。');\n"
    '    }\n'
    '  } finally {\n'
    "    btn.disabled = false; btn.textContent = '拉取后台各区现价';\n"
    '  }\n'
    '}\n'
    '\n'
    '// 拉一批模型的现图（按模型去重，只问还没问过的）。\n'
    '// ⚠️ 别在 renderRp() 里调它 —— renderRp 在改一个格子时就会跑一遍。\n'
    'async function rpLoadIcons(mids, opts) {\n'
    '  if (opts && opts.fresh) RP_ICON = {};\n'
    '  const need = [...new Set(mids)].filter(m => m && !(m in RP_ICON));\n'
    '  if (!need.length) return;\n'
    '  if (RP_ICONS_BUSY) { RP_ICONS_QUEUE.push(...need); return; }\n'
    '  RP_ICONS_BUSY = true;\n'
    '  try {\n'
    "    const d = await api('/api/models/icons', { mids: need });\n"
    '    if (d.ok) {\n'
    '      Object.entries(d.icons || {}).forEach(([k, v]) => { RP_ICON[Number(k)] = v; });\n'
    '      (d.missing || []).forEach(m => { RP_ICON[Number(m)] = { unknown: true }; });\n'
    '    } else {\n'
    '      need.forEach(m => { RP_ICON[Number(m)] = { unknown: true }; });\n'
    '    }\n'
    '  } catch (e) {\n'
    '    // 读不到就标「?」，别让图片列永远停在「…」上 —— 那看起来像还在加载。\n'
    '    need.forEach(m => { RP_ICON[Number(m)] = { unknown: true }; });\n'
    '  } finally {\n'
    '    RP_ICONS_BUSY = false;\n'
    '    renderRp();\n'
    '    const queued = RP_ICONS_QUEUE;\n'
    '    RP_ICONS_QUEUE = [];\n'
    '    if (queued.length) rpLoadIcons(queued);\n'
    '  }\n'
    '}\n'
    '\n'
    '// ⑤「一键添加水印」——把**勾选行**的后台商品图抓下来加印、再写回产品模型。\n'
    '//\n'
    '// 行为上的两条刻意设计：\n'
    '//\n'
    '// 1. **只处理勾选的行**，一行没勾就什么都不做并说明原因（不默认"全表"）。\n'
    '//    理由和「改价」一致：这个动作会**真的改前台图**，不能有"我以为是别人的锅"。\n'
    '// 2. 点下去先弹确认框，把**影响范围**摊开讲：模型图是**全站点共用**的，\n'
    '//    勾 3 行很可能只对应 1 个模型，而那个模型在 18 个站点 × 3 个区服的图**一起换**。\n'
    '//    不写清楚，用户会以为"我只改了这 3 行"。\n'
    'async function rpWatermark() {\n'
    '  if (RP_WM_BUSY) return;\n'
    '  if (!GGOODS.length) {\n'
    "    alert('表格里还没有行。\\n\\n先点「拉取后台各区现价」把在售商品拉出来，再勾选要处理的商品行。');\n"
    '    return;\n'
    '  }\n'
    '  const sel = GGOODS.filter(r => RP_SEL.has(r.goods_id));\n'
    '  if (!sel.length) {\n'
    "    alert('还没有勾选任何行。\\n\\n这个按钮**只处理勾选的行** —— 先在上面的表格里勾选要换图的商品，' +\n"
    "          '再点「一键添加水印」。');\n"
    '    return;\n'
    '  }\n'
    '  const mids = [...new Set(sel.map(r => r.model_id).filter(Boolean))];\n'
    '  if (!mids.length) {\n'
    "    alert('勾选的行里没有模型 ID，换不了图。\\n\\n这个按钮改的是「产品模型」上的图标，' +\n"
    "          '行上没有模型 ID 就没地方写。');\n"
    '    return;\n'
    '  }\n'
    '\n'
    '  const already = mids.filter(m => (RP_ICON[m] || {}).watermarked).length;\n'
    "  let msg = '把勾选行的**后台商品图**抓下来、叠上 MMOEXP 水印，再写回产品模型。\\n' +\n"
    "            '（入口就是后台的：产品管理 → 产品模型管理 → 编辑 → 图标）\\n\\n' +\n"
    '            `勾选 ${sel.length} 行 → 涉及 ${mids.length} 个产品模型。\\n\\n` +\n'
    '            `⚠️ 模型图是**全站点共用**的：这 ${mids.length} 个模型在**所有站点、所有区服**` +\n'
    "            '的在售行都会一起换图。\\n' +\n"
    "            '⚠️ 后台会把这些模型的「上架时间」刷成当前时刻（后台自己在界面里改图也一样）。\\n' +\n"
    "            '⚠️ 前台**真的会换图**，不是只换工具里那份。\\n';\n"
    "  msg += 'ℹ️ 水印位置按类目分：SBC 一套、Packs 一套（2026-10-10 指定的两个落点）。\\n';\n"
    '  if (already) {\n'
    '    msg += `\\n其中 ${already} 个模型显示「已加印」—— 服务端会把它们跳过，不会叠第二层。\\n`;\n'
    '  }\n'
    "  if (!confirm(msg + '\\n继续吗？')) return;\n"
    '\n'
    "  const btn = document.getElementById('rp_wm');\n"
    '  RP_WM_BUSY = true;\n'
    "  btn.disabled = true; btn.textContent = '加水印中…';\n"
    '  try {\n'
    "    const d = await api('/api/models/watermark', { mids });\n"
    "    if (!d.ok) { alert(d.error || '加水印失败'); return; }\n"
    '    // 服务端把换完之后的图信息一起带回来了，直接刷图片列，不用再问一遍后台\n'
    '    Object.entries(d.icons || {}).forEach(([k, v]) => { RP_ICON[Number(k)] = v; });\n'
    '    renderRp();\n'
    '    const lines = (d.results || []).map(r => {\n'
    "      const t = `mid ${r.mid}` + (r.title ? `（${r.title}）` : '');\n"
    "      if (r.status === 'done') {\n"
    "        return `✅ ${t}：已换图（${r.size || '—'}` +\n"
    "               (r.icon_before ? `，附件 ${r.icon_before} → ${r.icon_after}` : '') + '）' +\n"
    "               (r.note ? `\\n      ⚠️ ${r.note}` : '');\n"
    '      }\n'
    "      if (r.status === 'skipped') return `⏭️ ${t}：跳过 —— ${r.reason || ''}`;\n"
    "      return `❌ ${t}：失败 —— ${r.error || ''}`;\n"
    '    });\n'
    '    const shown = lines.slice(0, 20);\n'
    '    const more = lines.length > shown.length\n'
    '      ? `\\n… 还有 ${lines.length - shown.length} 条，详情见下面的「操作日志」。`\n'
    "      : '';\n"
    '    alert(`一键添加水印完成。\\n\\n共请求 ${d.requested} 个模型：换图 ${d.changed} 个，` +\n'
    "          `跳过 ${d.skipped} 个，失败 ${d.failed} 个。\\n\\n` + shown.join('\\n') + more);\n"
    '  } finally {\n'
    '    RP_WM_BUSY = false;\n'
    "    btn.disabled = false; btn.textContent = '一键添加水印';\n"
    '  }\n'
    '}\n'
    '\n'
    '// ---- 「永不自动下架」名单（⑥ 的 delist_protect）的状态与操作 ----\n'
    '// 为什么要能一键加入：Pack 会周期性换批次，SBC 也有同名旧版；\n'
    '// 光靠 ⑥ 里手打标题太容易漏字，⑤ 表里看到哪个商品要保就直接点一下（用户 2026-10-16 要求）。\n'
    'var RP_PROTECT = [];\n'
    '\n'
    'function rpProtectPatterns() {\n'
    "  return RP_PROTECT.map(p => normTitle(String(p || ''))).filter(Boolean);\n"
    '}\n'
    '\n'
    'function rpIsProtected(title) {\n'
    '  const t = normTitle(title);\n'
    '  if (!t) return false;\n'
    '  return rpProtectPatterns().some(pat => {\n'
    "    if (pat.indexOf('*') < 0) return t === pat;\n"
    "    const re = new RegExp('^' + pat.split('*')\n"
    "      .map(x => x.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')).join('.*') + '$');\n"
    '    return re.test(t);\n'
    '  });\n'
    '}\n'
    '\n'
    'function rpProtectCell(r) {\n'
    "  if (!r.title) return '';\n"
    '  if (rpIsProtected(r.title)) {\n'
    '    return \' <span class="rp-pic-tag done" title="已在「永不自动下架」名单里，自动下架不会动它">🚫 不下架</span>\';\n'
    '  }\n'
    '  return ` <button class="rp-mini" data-t="${esc(r.title)}" title="把这个商品加入「永不自动下架」名单 —— 自动下架永远不会灭它"\n'
    '    onclick="rpProtect(this.dataset.t)">🚫</button>`;\n'
    '}\n'
    '\n'
    '// 把某个商品加进「永不自动下架」名单（服务端存 list，前端只是追加）\n'
    'async function rpProtect(title) {\n'
    '  if (!title) return;\n'
    "  if (rpIsProtected(title)) { alert('这个商品已经在「永不自动下架」名单里了。'); return; }\n"
    "  if (!confirm('把「' + title + '」加入「永不自动下架」名单？\\n\\n加了之后：自动下架**永远不会**灭它。')) return;\n"
    "  const cur = await fetch(BASE + '/api/auto').then(r => r.json()).catch(() => null);\n"
    '  const list = (((cur && cur.ok && cur.settings && cur.settings.delist_protect) || []).slice());\n'
    '  if (!list.some(x => normTitle(x) === normTitle(title))) list.push(title);\n'
    "  const data = await api('/api/auto/save', { delist_protect: list });\n"
    '  if (!data || !data.ok) return;\n'
    '  RP_PROTECT = list;\n'
    "  const ta = document.getElementById('auto_delist_protect');\n"
    "  if (ta) ta.value = list.join('\\n');\n"
    '  rpProtectCount();\n'
    '  autoRender(data); show(data);\n'
    "  addLocal('已把「' + title + '」加入永不自动下架名单（当前 ' + list.length + ' 条）');\n"
    '  renderRp();\n'
    '}\n'
    '\n'
    '// ⑥ 面板里手填一条（支持 * 通配）\n'
    'async function autoProtectAdd() {\n'
    "  const box = document.getElementById('auto_protect_new');\n"
    "  const raw = ((box && box.value) || '').trim();\n"
    "  if (!raw) { alert('先填一个标题（支持 * 通配，例：ManCity11-* ）。'); return; }\n"
    "  const ta = document.getElementById('auto_delist_protect');\n"
    "  const lines = ((ta && ta.value) || '').split('\\n').map(s => s.trim()).filter(Boolean);\n"
    '  if (lines.some(x => x.toLowerCase() === raw.toLowerCase())) {\n'
    "    alert('「' + raw + '」已经在名单里了。');\n"
    '    return;\n'
    '  }\n'
    '  lines.push(raw);\n'
    "  if (ta) ta.value = lines.join('\\n');\n"
    "  if (box) box.value = '';\n"
    "  await autoSave({ delist_protect: lines.join('\\n') });\n"
    "  addLocal('已加入「永不自动下架」：' + raw + '（当前 ' + lines.length + ' 条）');\n"
    '  rpProtectCount();\n'
    "  if (typeof renderRp === 'function' && GGOODS.length) renderRp();\n"
    '}\n'
    '\n'
    'function rpProtectCount() {\n'
    "  const el = document.getElementById('auto_protect_count');\n"
    "  if (el) el.textContent = RP_PROTECT.length ? `名单 ${RP_PROTECT.length} 条` : '名单为空';\n"
    '}\n'
    '\n'
    'function renderRp() {\n'
    "  const tb = document.getElementById('rp_rows');\n"
    '  if (!GGOODS.length) {\n'
    '    tb.innerHTML = \'<tr><td colspan="13" class="hint">没有匹配的在售行</td></tr>\';\n'
    '    return;\n'
    '  }\n'
    '  tb.innerHTML = GGOODS.map(r => {\n'
    "    const checked = RP_SEL.has(r.goods_id) ? 'checked' : '';\n"
    '    // 图片列：这个模型**当前挂在后台**的图（就是前台在卖的那张）。\n'
    '    // 同一个模型的多行会显示同一张图 —— 这是**有意的**：它就是在讲\n'
    '    // "这几行共用一张图，加一次水印它们一起变"。\n'
    '    const info = r.model_id ? RP_ICON[r.model_id] : null;\n'
    '    let picCell;\n'
    '    if (!r.model_id) {\n'
    '      picCell = \'<span class="hint">无模型</span>\';\n'
    '    } else if (!info) {\n'
    '      picCell = \'<span class="hint">…</span>\';\n'
    '    } else if (info.unknown) {\n'
    '      picCell = \'<span class="hint" title="在 SBC / Packs 的模型列表里没找到这个 mid，读不到它的图">?</span>\';\n'
    '    } else if (!info.url) {\n'
    '      picCell = \'<span class="hint">无图</span>\';\n'
    '    } else {\n'
    '      picCell = \'<div class="rp-pic-cell">\' +\n'
    '        `<img class="rp-pic" src="${esc(info.url)}" alt="" loading="lazy"` +\n'
    '        ` title="${esc(info.title || r.title)} —— 点「一键添加水印」会换掉这张">` +\n'
    '        (info.watermarked\n'
    '          ? \'<span class="rp-pic-tag done">已加印</span>\'\n'
    '          : \'<span class="rp-pic-tag">未加印</span>\') +\n'
    "        '</div>';\n"
    '    }\n'
    '    const implied = rpImplied(r);\n'
    "    const price = r.price ? r.price : '—';\n"
    '    // 类目：粗体是**定价口径**（SBC / Packs），小字是**具体类目**（cid + 名字）。\n'
    '    // 两个都要显示：SBC 父类目 9625 底下现在有 9971 Upgrade 和 10203 SBC Players\n'
    '    // 两个叶子，光看 cid 数字没人分得清；而定价/手续费只看 kind，所以也不能只显示名字。\n'
    "    const cidTail = `${r.cid ?? ''}${r.cid_name ? ' ' + r.cid_name : ''}`.trim();\n"
    '    const kindTag = r.kind\n'
    '      ? `<span style="font-weight:600">${esc(r.kind)}</span><br><span class="hint">${esc(cidTail)}</span>`\n'
    '      : `<span class="hint">${esc(cidTail) || \'—\'}</span>`;\n'
    '    const siteTag = (r.site_id === 0 || r.site_id === null)\n'
    "      ? '<b>ALL</b>' : String(r.site_id ?? '—');\n"
    '    // 每金币价：单独设过的行加蓝底 + 标记 —— 让用户一眼看出"这行不会跟着行情走"。\n'
    '    // 这正是 2026-09-29「强制刷新后 PC 价还是旧值」那个问题的可视化解药：\n'
    '    // 以前的表格看不出哪些行被逐产品值挡住了，用户只能看到"点了没反应"。\n'
    '    //\n'
    '    // r.rate_auto（服务端算的：自己的值恰好等于某个区服默认价）多半是老版本「保存」\n'
    '    // 冻下来的，单独用红底标「疑似被冻住」—— 但**只标不动**，改不改由用户点确认决定。\n'
    '    const rateOwn = rpRateIsOwn(r);\n'
    '    const frozen = rateOwn && r.rate_auto;\n'
    "    const rateCls = r.rate ? ('w-md' + (rateOwn ? ' own' : '') + (frozen ? ' frozen' : ''))\n"
    "                           : 'w-md need';\n"
    '    const rateCell = `<input class="${rateCls}" value="${esc(r.rate ?? \'\')}" placeholder="每金币价"\n'
    '           title="目标价里的「每金币价」。点上面「按 MMOEXP 取回最新每金币价」自动填，也可手改。${rateOwn ? \'⚠️ 这一行被单独设过，取最新价时默认不会覆盖它 —— 想让它跟着行情走，清空这一格再点「保存」，或点「按 MMOEXP 取回最新每金币价」在弹窗里选「确定」。\' : \'\'}${frozen ? \' 这一格的值和区服默认价一模一样，很可能是老版本「保存」把自动带出的值冻住了。\' : \'\'}"\n'
    '           onchange="rpSetRate(${r.goods_id}, this.value)">` +\n'
    '      (rateOwn\n'
    '        ? \'<br><span class="hint">已单独设\' +\n'
    '          (frozen ? \' <span class="frozen-tag">·疑似被冻住</span>\' : \'\') + \'</span>\'\n'
    "        : '');\n"
    '    // 手续费：SBC 给一个**可逐行编辑**的格子。值就是这一行的生效值；\n'
    '    // 单独设过的打「已单独设」标记（改全局手续费时它不会被冲掉）。\n'
    '    // 清空那一格 = 取消单独设置，回落顶部全局值 —— placeholder 里写着回落目标，方便看。\n'
    '    const feeOwn = rpFeeIsOwn(r);\n'
    '    const feeCell = rpFeeApplies(r)\n'
    '      ? `<input class="w-sm${feeOwn ? \' own\' : \'\'}" value="${esc(r.fee)}"\n'
    '           placeholder="${esc(String(rpFeeOf(r)))}"\n'
    '           title="这一行的手续费。改它就只改这一行；清空 = 取消单独设置，回落顶部的全局值"\n'
    '           onchange="rpSetFee(${r.goods_id}, this.value)">` +\n'
    '        (feeOwn ? \'<br><span class="hint">已单独设</span>\' : \'\')\n'
    '      : (r.kind ? \'<span class="hint">不计</span>\' : \'<span class="hint">?</span>\');\n'
    '    // 加成：**每一行**都能单独改（不像手续费只有 SBC 那一格可编辑 —— 加成不分类目，\n'
    '    // Packs 也乘它）。单独设过的打「已单独设」标记，改全局加成时不会被冲掉。\n'
    '    // 清空那一格 = 取消单独设置，回落顶部全局加成 —— placeholder 里写着回落目标。\n'
    '    const markupOwn = rpMarkupIsOwn(r);\n'
    '    const markupCell = `<input class="w-sm${markupOwn ? \' own\' : \'\'}" value="${esc(r.markup ?? \'\')}"\n'
    '           placeholder="${esc(String(rpMarkupOf(r)))}"\n'
    '           title="这一行的加成（价格倍数）。改它就只改这一行；清空 = 取消单独设置，回落顶部的全局加成。&#10;目标价 = (金币数 × 每金币价 + 手续费) × 加成（Packs 不含手续费）。必须大于 0，不加成请填 1。"\n'
    '           onchange="rpSetMarkup(${r.goods_id}, this.value)">` +\n'
    '      (markupOwn ? \'<br><span class="hint">已单独设</span>\' : \'\');\n'
    '    return `<tr>\n'
    '      <td><input type="checkbox" ${checked}\n'
    '           onchange="rpToggle(${r.goods_id}, this.checked)"></td>\n'
    '      <td>${esc(r.title)}</td>\n'
    '      <td>${picCell}</td>\n'
    '      <td>${kindTag}</td>\n'
    '      <td>${siteTag}</td>\n'
    '      <td>${esc(r.area)}</td>\n'
    "      <td>${r.num ?? '—'}</td>\n"
    '      <td>${esc(price)}<br><span class="hint">${implied || \'—\'}</span></td>\n'
    '      <td><input class="w-sm" value="${esc(r.coins ?? \'\')}" placeholder="金币"\n'
    '           onchange="rpSetCoins(${r.goods_id}, this.value)"></td>\n'
    '      <td>${rateCell}</td>\n'
    '      <td>${feeCell}</td>\n'
    '      <td>${markupCell}</td>\n'
    "      <td><b>${esc(r.target || '—')}</b>${rpProtectCell(r)}</td>\n"
    '    </tr>`;\n'
    "  }).join('');\n"
    '}\n'
    '\n'
    'function rpPlan() {\n'
    '  const sel = GGOODS.filter(r => RP_SEL.has(r.goods_id));\n'
    '  const ready = sel.filter(r => r.target);\n'
    '  const missing = sel.filter(r => !r.target);\n'
    '  const lackRate = missing.filter(r => rpNum(r.rate) === null).length;\n'
    '  const lackCoins = missing.length - lackRate;\n'
    '  const sbcN = sel.filter(r => rpFeeApplies(r)).length;\n'
    '  const packN = sel.length - sbcN;\n'
    '  const ownFee = sel.filter(r => rpFeeIsOwn(r)).length;\n'
    "  const globalFee = rpNum(document.getElementById('rp_fee').value) ?? 0.24;\n"
    '  // 每金币价里"自己的值"有几行、其中几行看着就是被"保存"冻下来的。\n'
    '  // 这两句是给「强制刷新后价不变」那个问题兜底的可见性 —— 不报出来，\n'
    '  // 用户永远不知道点了没反应是因为表格里躺着 11 行自己设过的价。\n'
    '  const ownRateN = sel.filter(r => rpRateIsOwn(r)).length;\n'
    '  const frozenN = sel.filter(r => rpRateIsOwn(r) && r.rate_auto).length;\n'
    "  let tail = '';\n"
    '  if (lackRate) tail += `；${lackRate} 行缺每金币价`;\n'
    '  if (lackCoins) tail += `；${lackCoins} 行缺金币数`;\n'
    "  let rateNote = '';\n"
    '  if (frozenN) {\n'
    '    rateNote = ` · ⚠️ ${frozenN} 行每金币价疑似被冻住（点「按 MMOEXP 取回最新每金币价」→ 选「确定」可清掉）`;\n'
    '  } else if (ownRateN) {\n'
    '    rateNote = ` · ${ownRateN} 行每金币价单独设过，不跟行情走`;\n'
    '  }\n'
    '  // 加成也报一句：单独设过的行不跟顶部全局框走，不报出来用户会以为"改了没反应"。\n'
    '  const ownMarkupN = sel.filter(r => rpMarkupIsOwn(r)).length;\n'
    "  const globalMarkup = rpNum(document.getElementById('rp_markup').value) ?? 1.1;\n"
    '  const markupNote = ownMarkupN\n'
    '    ? ` · ${ownMarkupN} 行加成单独设过（其余用全局 ${globalMarkup}）`\n'
    '    : ` · 加成全用全局 ${globalMarkup}`;\n'
    "  document.getElementById('rp_plan').textContent =\n"
    '    `已勾选 ${sel.length} 行（其中可改价 ${ready.length} 行）` +\n'
    '    ` · SBC ${sbcN} 行含手续费（${ownFee} 行单独设、${sbcN - ownFee} 行用全局 ${globalFee}），` +\n'
    '    `Packs ${packN} 行不计` +\n'
    "    (tail ? tail + '，会被跳过' : '') + markupNote + rateNote;\n"
    '}\n'
    '\n'
    '// 取回**最新**每金币价并带进表格。\n'
    '//\n'
    '// ⚠️ 这里**只有一条路，而且永远 force**（跳过 30 分钟缓存）—— 2026-09-29 用户要求\n'
    '// 把「按 MMOEXP 带出每金币价」和「强制刷新最新价」合成一个按钮。\n'
    '//\n'
    '// 为什么干脆不留"用缓存"这个选项：原来那个"带出"按钮默认读缓存，缓存命中时\n'
    '// **根本不联网**却照样弹「已按 MMOEXP 取回 N 个区服」—— 用户据此当成最新价，\n'
    '// 实测同一天 PC 就差了 5.5%。一个按钮如果会给出旧值、又长得像新值，它迟早骗人。\n'
    '// 现在界面上没有任何"看起来像最新、其实是缓存"的入口 —— 点一次就是真联网取一次。\n'
    '//\n'
    '// 唯一会拿到旧值的情况是**联网失败**：那时服务端退回上次缓存，并在响应里给\n'
    '// from_cache / source / warning。这里必须如实弹出来（写「联网失败，退回某次的价」），\n'
    '// **绝不能**再说「已取回最新每金币价」—— 缓存不是错，错在不吭声。\n'
    'async function rpFetchRates() {\n'
    "  const btn = document.getElementById('rp_getrate');\n"
    "  const orig = btn ? btn.textContent : '';\n"
    "  if (btn) { btn.disabled = true; btn.textContent = '联网取最新价中…'; }\n"
    '  try {\n'
    '    if (!GGOODS.length) {\n'
    "      alert('表格里还没有行。\\n\\n先点「拉取后台各区现价」把在售商品拉出来，' +\n"
    "            '再点这个按钮取回每金币价 —— 行情是按区服套到那些行上的。');\n"
    '      return;\n'
    '    }\n'
    '\n'
    '    // 被「单独设过」的行默认不动。但这里必须**问一次**要不要连它们一起覆盖 ——\n'
    '    // 因为这些值有两种来源，代码分不出来：\n'
    '    //   ① 用户自己手填的       -> 覆盖了就丢了，得让用户自己决定；\n'
    '    //   ② 老版本「保存」把**自动带出的区服默认值**一起存进 by_model/by_title 造成的\n'
    '    //      -> 它的优先级高于区服默认值，于是这个产品的价**永远刷不动**\n'
    '    //         （2026-09-29 用户报「强制刷新后 PC 价是 141，表格里不变」就是这个）。\n'
    '    // 后端再给一个 rate_auto 线索（值恰好等于某个区服默认价），让用户敢下决心。\n'
    '    let overwriteOwn = false;\n'
    '    const ownRows = GGOODS.filter(r => rpRateIsOwn(r));\n'
    '    if (ownRows.length) {\n'
    '      const titles = [...new Set(ownRows.map(r => r.title))];\n'
    '      const suspect = [...new Set(ownRows.filter(r => r.rate_auto).map(r => r.title))];\n'
    '      const tail = suspect.length\n'
    "        ? `\\n\\n其中 ${suspect.length} 个产品的值和**区服默认价完全一样**（${suspect.slice(0, 4).join('、')}` +\n"
    '          `${suspect.length > 4 ? \' 等\' : \'\'}）—— 基本可以确定是老版本「保存」把自动带出的值存成了"手改值"，` +\n'
    '          `正是它们挡住了新行情。`\n'
    "        : '';\n"
    '      overwriteOwn = confirm(\n'
    '        `有 ${ownRows.length} 行（${titles.length} 个产品）的「每金币价」是**单独设过**的，` +\n'
    '        `取最新价时默认不动它们：\\n\\n` +\n'
    "        titles.slice(0, 10).map(t => '· ' + t).join('\\n') +\n"
    "        (titles.length > 10 ? `\\n… 另外 ${titles.length - 10} 个` : '') +\n"
    '        `\\n\\n要不要**连这些行一起覆盖**成最新行情？\\n` +\n'
    '        `· 确定 = 覆盖（这些行的单独设置会被清掉，回到按区服默认值）\\n` +\n'
    '        `· 取消 = 保留它们，只刷新其余行` + tail\n'
    '      );\n'
    '    }\n'
    '\n'
    '    // 恒定 force=true —— 见函数头注释：界面上不再有"读缓存"这条路。\n'
    "    const d = await api('/api/rates', { force: true, overwrite_own: overwriteOwn });\n"
    "    if (!d.ok) { alert(d.error || '取每金币价失败'); return; }\n"
    '\n'
    '    // 服务端已把默认值写进设置（by_aid）。这里负责把**表格里的行**跟着刷新。\n'
    '    const byAid = {};\n'
    '    (d.rates || []).forEach(x => { byAid[String(x.aid)] = x.per_coin; });\n'
    '\n'
    '    let updated = 0, filled = 0, kept = 0, noAid = 0, overwrote = 0;\n'
    '    GGOODS.forEach(r => {\n'
    '      const fresh = byAid[String(r.aid)];\n'
    '      const own = rpRateIsOwn(r);\n'
    '      // 「单独设过」的行只在**用户明确选了覆盖**（且这个区服真的取到新价）时才动。\n'
    '      // 注意不能用 `own && !overwriteOwn` 之外的判断 —— 选了覆盖却还按 own 跳过，\n'
    '      // 用户会觉得"点了确定还是没反应"（服务端那边已经清掉了逐产品值，两边会不一致）。\n'
    '      if (own && !(overwriteOwn && fresh)) {\n'
    '        kept++;                                  // 手改值，别动\n'
    '      } else if (fresh) {\n'
    '        if (own) overwrote++;                    // 原本单独设过，这次被盖掉了\n'
    '        else if (r.rate) updated++; else filled++;   // 覆盖旧的带出值 / 补上空的\n'
    '        r.rate = fresh;\n'
    '        // 覆盖之后它就不再是"我的/单独设的值"了，两个标记都要清 ——\n'
    '        // rate_edited 不清的话，下次「保存」又会被当成手改值发出去，重新冻一遍。\n'
    '        r.rate_own = false;\n'
    '        r.rate_edited = false;\n'
    '        r.rate_auto = false;\n'
    '      } else {\n'
    '        noAid++;                                 // 这个区服没取到价\n'
    '      }\n'
    '      // 每行都要重算 —— 旧实现写成 `if (r.rate) return;`，\n'
    '      // 结果「有值的行」连目标价都不重算，用户看到的就是「点了没反应」。\n'
    '      rpRecalcOne(r);\n'
    '    });\n'
    '    renderRp(); rpPlan();\n'
    '\n'
    '    const n = (d.rates || []).length;\n'
    "    const list = (d.rates || []).map(x => `${x.area}\u3000${x.per_coin}`).join('\\n');\n"
    '    // from_cache 现在**只会**在联网失败时出现（服务端 except 分支退回缓存）。\n'
    '    // 所以这里的措辞必须是"失败了、这是旧价"，而不是"已取回最新"。\n'
    '    const head = d.from_cache\n'
    "      ? `⚠️ 联网取最新价失败，退回「${d.source || '上次缓存'}」的 ${n} 个区服价`\n"
    '      : `已按 MMOEXP 取回 ${n} 个区服的**最新**每金币价`;\n'
    '    // 被挡住的行要**说清楚是哪几个**，否则用户只会看到"点了没反应"。\n'
    '    const keptNote = kept\n'
    '      ? `\\n\\n⚠️ 有 ${kept} 行被"单独设过"的每金币价挡住了，这次没动它们（表格里那几格是蓝底、标着「已单独设」）。` +\n'
    '        `\\n   如果它们本该跟着行情走，重新点一次这个按钮，在弹窗里选「确定」就会连它们一起覆盖。`\n'
    "      : '';\n"
    '    alert(`${head}：\\n\\n${list}\\n\\n` +\n'
    '          `表格里：更新 ${updated} 行、新填 ${filled} 行` +\n'
    "          (overwrote ? `、覆盖了 ${overwrote} 行原本单独设过的` : '') +\n"
    "          (noAid ? `、${noAid} 行没匹配到区服` : '') +\n"
    '          `。\\n\\n目标价已重算。想留住这次的值，点「保存」。` +\n'
    '          (d.cleared && d.cleared.length\n'
    '            ? `\\n\\n已清掉 ${d.cleared.length} 个产品的"单独设置"，它们回到**按区服默认值**。`\n'
    "            : '') +\n"
    '          keptNote +\n'
    "          (d.warning ? `\\n\\n⚠️ ${d.warning}` : ''));\n"
    '  } finally {\n'
    '    if (btn) { btn.disabled = false; btn.textContent = orig; }\n'
    '  }\n'
    '}\n'
    '\n'
    '// 标题归一化：剥掉 (Non-repeatable) 后缀 + 小写 + 压缩空白。\n'
    '// ⚠️ 后台模型叫「TOTW Upgrade(Non-repeatable)」、采集表里叫「TOTW Upgrade」——\n'
    '//    不归一化就一个都对不上（用户口径 2026-10-15）。\n'
    '// 标题归一化：剥掉尾部「重复规则」括号后缀（与后端 uploader.strip_repeat_suffix 同口径）。\n'
    '// (Non-repeatable) / (Repeatable:1;3-day Refresh) / （Repeatable: Unlimited）都算；\n'
    '// 名字里不含 repeat 的括号（如 (Player Pick)）不动。\n'
    'function stripRepeatSuffix(t) {\n'
    "  let s = String(t || '').trim();\n"
    '  for (let i = 0; i < 5; i++) {\n'
    "    const next = s.replace(/\\s*[（(][^（()）]*repeat[^（()）]*[)）]\\s*$/i, '').trim();\n"
    '    if (next === s) break;\n'
    '    s = next;\n'
    '  }\n'
    '  return s;\n'
    '}\n'
    '\n'
    'function normTitle(t) {\n'
    "  return stripRepeatSuffix(t).toLowerCase().replace(/\\s+/g, ' ').trim();\n"
    '}\n'
    '\n'
    'async function rpFillCoins() {\n'
    "  const d = await fetch(BASE + '/api/rows').then(r => r.json()).catch(() => null);\n"
    '  if (!d || !d.ok || !d.rows || !d.rows.length) {\n'
    "    alert('还没有采集数据。先去 ② 采集，或手工填写金币数。');\n"
    '    return;\n'
    '  }\n'
    '  const byTitle = {};\n'
    '  d.rows.forEach(r => { if (r.coins) byTitle[normTitle(r.title)] = r.coins; });\n'
    '  let hit = 0;\n'
    '  GGOODS.forEach(r => {\n'
    '    const key = normTitle(r.title);\n'
    '    if (byTitle[key]) { r.coins = byTitle[key]; rpRecalcOne(r); hit++; }\n'
    '  });\n'
    '  renderRp(); rpPlan();\n'
    '  const noRate = GGOODS.filter(r => r.coins && rpNum(r.rate) === null).length;\n'
    '  alert(`按标题匹配到 ${hit} 行的金币数。` +\n'
    "        (noRate ? `\\n\\n还有 ${noRate} 行缺「每金币价」，点「按 MMOEXP 取回最新每金币价」就能出目标价。` : '') +\n"
    '        `\\n\\n点「保存金币数/每金币价/手续费/加成」可持久化。`);\n'
    '}\n'
    '\n'
    'async function rpSaveSettings() {\n'
    "  const markup = document.getElementById('rp_markup').value;\n"
    '  // fee 也要一并落盘 —— 只发 markup/coins/rate 的话，改了手续费点保存会「存了个寂寞」\n'
    "  const fee = document.getElementById('rp_fee').value;\n"
    '  // ⚠️ rate / fee / markup 都**只发被单独设过的行**，绝不能无条件全发。\n'
    '  //\n'
    '  // 为什么（2026-09-29 用户报「点了强制刷新最新价，PC 价是 141 但下面不变」）：\n'
    "  // 老版本这里写的是 `rate: r.rate || ''` —— 无条件全发。于是**每一行**（包括表格里\n"
    '  // 自动带出来的区服默认价）都被写进 by_model / by_title，而这两级的优先级**高于**\n'
    '  // by_aid。结果这些产品从此被判成"手改过"：\n'
    '  //   · 「按 MMOEXP 带出 / 强制刷新」一律被 own_rate() 挡住（服务端日志表现：\n'
    '  //     「已带出 3 个区服的每金币价…其中 0 行用上了默认值」）；\n'
    '  //   · 行情怎么变，表格里那个价都不动 —— 就是用户看到的"点了没反应"。\n'
    '  // 实测：11 个产品的 by_model[].rate 全是 0.0001324（= PS5/Xbox 默认值），\n'
    "  // 而 by_aid['21589']（PC）是 0.000141，rate_for(mid, title, aid=21589) 却返回 0.0001324。\n"
    '  //\n'
    '  // 判据：rpRateIsOwn / rpFeeIsOwn（服务端 rate_own / fee_own + 本次会话\n'
    '  // rate_edited / fee_edited）。**没带字段 = 后端一行都不动**。\n'
    '  // 金币数不受影响：它是用户为每个产品填的，不存在"自动带出"这一层，所以照旧全发。\n'
    '  //\n'
    "  // 注：`rate: ''`（清空那一格）是**有意义的**——后端 set_rate(rate=None) 会把这行的\n"
    '  //     逐产品值删掉、回落到按区服默认值。所以手填过的行想"解冻"，\n'
    '  //     清空那一格再保存就行，不必非得重新联网取价。\n'
    '  const items = GGOODS.map(r => {\n'
    "    const it = { model_id: r.model_id, title: r.title, coins: r.coins || '' };\n"
    "    if (rpRateIsOwn(r)) it.rate = r.rate || '';\n"
    "    if (rpFeeIsOwn(r)) it.fee = (r.fee === null || r.fee === undefined) ? '' : String(r.fee);\n"
    '    // 加成同理：只发**单独设过**的行。无条件全发的话，每点一次保存就把所有行\n'
    '    // 钉死在当时的全局加成上，之后再改全局框就再也刷不动了 —— 和上面 rate 那个\n'
    '    // 「价格被冻住」是同一个病，只是换了个字段。\n'
    "    if (rpMarkupIsOwn(r)) it.markup = (r.markup === null || r.markup === undefined) ? '' : String(r.markup);\n"
    '    return it;\n'
    '  });\n'
    "  const d = await api('/api/settings/save', { markup, fee, items });\n"
    "  if (!d.ok) { alert(d.error || '保存失败'); return; }\n"
    '\n'
    '  // 保存后服务端就有这些行的"自己的值"了 —— 把服务端标记同步到本地。\n'
    '  // 不同步的话同一批数据再点一次保存，rpRateIsOwn 还是只看 rate_edited，虽然也对，\n'
    '  // 但刷新页面后标记会来回跳，看着像"没存上"。\n'
    '  GGOODS.forEach(r => {\n'
    '    if (rpRateIsOwn(r)) r.rate_own = true;\n'
    '    if (rpFeeIsOwn(r)) r.fee_own = true;\n'
    '    if (rpMarkupIsOwn(r)) r.markup_own = true;\n'
    '  });\n'
    '  renderRp();\n'
    '\n'
    '  // 回执要说清「哪些行不会跟着行情走」—— 否则用户改完价就再也想不起这些蓝格子了。\n'
    '  const ownRows = GGOODS.filter(r => rpRateIsOwn(r));\n'
    '  const frozenN = GGOODS.filter(r => rpRateIsOwn(r) && r.rate_auto).length;\n'
    '  // 单独设过加成的行也要报：它们同样"不跟全局框走"，用户改完全局加成发现这几行\n'
    '  // 没动，会以为工具坏了（和每金币价那个「点了没反应」是同一类误会）。\n'
    '  const ownMarkupN = GGOODS.filter(r => rpMarkupIsOwn(r)).length;\n'
    '  let tail = frozenN\n'
    '    ? `\\n\\n⚠️ 另有 ${frozenN} 行的每金币价和区服默认价一模一样，几乎可以肯定是老版本「保存」` +\n'
    '      `把自动带出的值冻住了（表格里红底标着「疑似被冻住」）。\\n` +\n'
    '      `   点「按 MMOEXP 取回最新每金币价」，在弹窗里选「确定」就能清掉它们、换成最新行情。`\n'
    '    : (ownRows.length\n'
    '        ? `\\n\\n有 ${ownRows.length} 行的每金币价是"单独设的"（表格里蓝底「已单独设」），` +\n'
    '          `行情刷新默认不会动它们。`\n'
    "        : '');\n"
    '  if (ownMarkupN) {\n'
    '    tail += `\\n\\n有 ${ownMarkupN} 行的**加成**是单独设的（表格「加成」列标着「已单独设」），` +\n'
    '            `改顶部那个全局加成框不会动它们。\\n` +\n'
    '            `   要让某一行跟着全局走：把那一格清空再点「保存金币数/每金币价/手续费/加成」。`;\n'
    '  }\n'
    '  alert(`已保存（加成 ${d.markup}，全局手续费 ${d.fee}，`\n'
    '        + `${d.saved} 条金币数、${d.rate_rows || 0} 条单独设的每金币价`\n'
    "        + (d.fee_rows ? `、${d.fee_rows} 行单独设的手续费` : '')\n"
    "        + (d.markup_rows ? `、${d.markup_rows} 行单独设的加成` : '') + `）` + tail);\n"
    '}\n'
    '\n'
    'async function rpApply() {\n'
    '  const sel = GGOODS.filter(r => RP_SEL.has(r.goods_id) && r.live && r.target);\n'
    '  if (!sel.length) {\n'
    '    const picked = GGOODS.filter(r => RP_SEL.has(r.goods_id) && r.live);\n'
    "    let why = '没有可改价的行。';\n"
    '    if (!picked.length) {\n'
    "      why += '请先勾选要改的「亮」行。';\n"
    '    } else {\n'
    '      const noRate = picked.filter(r => rpNum(r.rate) === null).length;\n'
    '      const noCoins = picked.filter(r => rpNum(r.coins) === null).length;\n'
    "      why += '勾选的行还算不出目标价：';\n"
    '      if (noRate) why += `\\n· ${noRate} 行缺「每金币价」（点「按 MMOEXP 带出」）`;\n'
    '      if (noCoins) why += `\\n· ${noCoins} 行缺「金币数」（点「用采集的金币价」）`;\n'
    '    }\n'
    '    alert(why);\n'
    '    return;\n'
    '  }\n'
    "  const lines = sel.slice(0, 12).map(r => `${r.title} / ${r.area}：${r.price || '—'} → ${r.target}`).join('\\n');\n"
    "  const more = sel.length > 12 ? `\\n… 另外 ${sel.length - 12} 行` : '';\n"
    '  if (!confirm(`即将改价 ${sel.length} 行（只改状态亮的）：\\n\\n${lines}${more}\\n\\n确定继续吗？`)) return;\n'
    '  const items = sel.map(r => ({ goods_id: r.goods_id, price: r.target, coins: r.coins }));\n'
    '  // fee 必须一起发：不发的话后端会回落到「已保存的」手续费，\n'
    '  // 而上面弹窗里的目标价是按输入框里的值算的 —— 你确认的和真正提交的会是两个数。\n'
    "  const d = await api('/api/reprice', {\n"
    "    markup: document.getElementById('rp_markup').value,\n"
    "    fee: document.getElementById('rp_fee').value,\n"
    '    items\n'
    '  });\n'
    "  if (!d.ok) { alert(d.error || '改价失败'); return; }\n"
    '\n'
    '  let msg = `改价完成：成功 ${d.changed} / 共 ${d.total} 行`;\n'
    '  if (d.blocked) {\n'
    '    // 2026-09-28 更正：老代码走的是 goods.Goods/singleEdit —— 那是**错的门**\n'
    '    // （不含 price；规则表里也没建该节点，日志记成「产品管理-Unknown(singleedit)」，\n'
    '    //  非 super 恒 401）。现在的改价走 goods.Goods/edit（实测 code=1 修改成功），\n'
    '    // 当前账号有 goods/goods/edit。\n'
    '    //\n'
    '    // 所以这里**不能**再照抄老文案说"你去勾单值编辑就好"—— 那是条死路。\n'
    '    // 也不能反过来咬定"就是权限问题"：真撞上 401，先把实况查出来再说。\n'
    '    msg = `⛔ 一行都没改成功。\\n\\n${d.error}\\n\\n` +\n'
    '          `**这不是价格算错。** 改价打的是「产品管理」页行内「编辑」的接口\\n` +\n'
    '          `（POST /admin/goods.Goods/edit），它要的是权限节点 goods/goods/edit。\\n` +\n'
    '          `当前账号的这个节点没勾上，或者这个账号被后台拒了。\\n\\n` +\n'
    '          `请点 ⑤ 面板的「权限自检」（只读）—— 它会直接告诉你：\\n` +\n'
    '          `   账号是谁 / 是不是 super / goods/goods/edit 到底有没有。\\n` +\n'
    '          `   · 显示 ❌ 没有 → 让有最高权限的同事在「权限管理 → 菜单规则」里\\n` +\n'
    '          `     给「产品管理」授权「编辑」，或者直接用 super 账号登录本工具。\\n` +\n'
    '          `   · 显示 ✅ 有 → 那就不是权限，把上面这段原文发我。\\n\\n` +\n'
    '          `已中止，后面 ${(d.detail || []).filter(x => !x.ok).length - 1} 行没有再去打后台。`;\n'
    '  }\n'
    '  // ⚠️ 失败原因一定要弹出来。以前只弹「成功 0 / 共 27 行」，\n'
    '  // 后端每行的错误（比如「You have no permission」）全在 d.detail 里没显示，\n'
    '  // 用户只能来问人。\n'
    '  const fails = (d.detail || []).filter(x => !x.ok);\n'
    '  if (fails.length && !d.blocked) {\n'
    '    const byReason = new Map();\n'
    '    fails.forEach(x => {\n'
    "      const why = (x.error || `后台 code=${x.code} ${x.msg || ''}`).trim();\n"
    '      byReason.set(why, (byReason.get(why) || 0) + 1);\n'
    '    });\n'
    '    msg += `\\n\\n失败 ${fails.length} 行，原因：`;\n'
    '    [...byReason.entries()].slice(0, 5).forEach(([why, n]) => {\n'
    '      msg += `\\n· ${n} 行：${why}`;\n'
    '    });\n'
    "    const first = fails.slice(0, 5).map(x => `  ${x.label} → ${x.price}`).join('\\n');\n"
    '    msg += `\\n\\n例如：\\n${first}`;\n'
    '    if (fails.length > 5) msg += `\\n  … 另外 ${fails.length - 5} 行`;\n'
    '  }\n'
    '  if (d.skipped && d.skipped.length) {\n'
    "    msg += `\\n\\n跳过 ${d.skipped.length} 行：\\n` + d.skipped.slice(0, 10).join('\\n');\n"
    '  }\n'
    '  alert(msg);\n'
    '  rpLoad();\n'
    '}\n'
    '\n'
    '// ---------------------- 启动 ----------------------\n'
    '// 点弹窗遮罩空白处 / 按 Esc 关闭\n'
    "document.getElementById('mask').addEventListener('click', e => {\n"
    "  if (e.target.id === 'mask') closeDialog();\n"
    '});\n'
    "document.addEventListener('keydown', e => {\n"
    "  if (e.key === 'Escape') closeDialog();\n"
    '});\n'
    '\n'
    '// 启动时如果服务端已经有列表，直接显示（刷新页面不丢）\n'
    '(async () => {\n'
    "  const data = await fetch(BASE + '/api/rows').then(r => r.json()).catch(() => null);\n"
    '  if (data && data.ok) { renderRows(data.rows); setDirty(data.dirty); }\n'
    '})();\n'
    '\n'
    'refreshStatus();\n'
    'autoLoad();\n'
    '// 切回这个标签页时重新拉一次设置 —— 页面开着的时候别处改过就会错位\n'
    "document.addEventListener('visibilitychange', function () {\n"
    '  if (!document.hidden) autoLoad();\n'
    '});\n'
    'setInterval(pollLog, 1200);\n'
    'setInterval(refreshStatus, 5000);\n'
    'setInterval(autoPoll, 5000);\n'
    '\n'
    '// ---------------------- ⑥ 自动化 ----------------------\n'
    '\n'
    'let autoWasRunning = null;\n'
    '\n'
    'function _autoStepRow(s) {\n'
    "  const cls = s.state === 'run' ? 'run' : (s.state === 'ok' ? 'ok' : (s.state === 'fail' ? 'fail' : ''));\n"
    '  return `<div class="auto-step ${cls}"><span class="dot"></span>${esc(s.name)}` +\n'
    '         (s.detail ? `<span class="d">${esc(s.detail)}</span>` : \'\') + `</div>`;\n'
    '}\n'
    '\n'
    'function _renderSteps(boxId, record) {\n'
    '  const box = document.getElementById(boxId);\n'
    '  if (!box) return;\n'
    '  if (!record) { box.innerHTML = \'<div class="hint" style="margin:0">还没有运行记录</div>\'; return; }\n'
    '  const steps = (record.steps || []).map(s => ({\n'
    "    name: s.name, detail: s.detail || '',\n"
    "    state: s.ok ? 'ok' : 'fail'\n"
    '  }));\n'
    '  const lines = [];\n'
    '  steps.forEach(s => lines.push(_autoStepRow(s)));\n'
    "  const head = `${record.ok ? '✅' : (record.running ? '⏳' : (steps.length ? '❌' : '⏳'))} ` +\n"
    "    `${record.started_at || ''} 起（${record.trigger === 'auto' ? '定时' : '手动'}）` +\n"
    "    (record.finished_at ? ` · ${record.finished_at} 结束` : ' · 进行中');\n"
    '  box.innerHTML = `<div class="auto-step ${record.running ? \'run\' : (record.ok ? \'ok\' : (steps.length ? \'fail\' : \'run\'))}" style="margin-bottom:2px">${esc(head)}</div>` +\n'
    "    lines.join('');\n"
    '}\n'
    '\n'
    'let autoLoadedOk = false;        // 设置是否**真的从服务端读到过**\n'
    'let autoStaleNotifiedAt = 0;\n'
    'function autoStaleBanner(show) {\n'
    "  let el = document.getElementById('auto_stale');\n"
    '  if (!el) {\n'
    "    el = document.createElement('div');\n"
    "    el.id = 'auto_stale';\n"
    "    el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99998;background:#b3261e;'\n"
    "      + 'color:#fff;padding:8px 12px;font-size:13px;text-align:center';\n"
    "    el.textContent = '⚠️ 自动化设置没加载成功（多半是统一登录过期）—— 已禁止保存，'\n"
    "      + '点这里刷新页面';\n"
    '    el.onclick = () => { location.href = location.pathname; };\n'
    '    document.body.appendChild(el);\n'
    '  }\n'
    "  el.style.display = show ? 'block' : 'none';\n"
    '}\n'
    '\n'
    'async function autoLoad() {\n'
    "  const data = await fetch(BASE + '/api/auto').then(r => r.json()).catch(() => null);\n"
    '  if (!data || !data.ok) {\n'
    '    // ⚠️ 读不到设置时，面板会留着"开关默认未勾选"的假象；此时**绝不能**保存 ——\n'
    '    //    以前一改时间/保护名单就把"关"整表单写回去（2026-10-16 用户报"开关老是被关"）。\n'
    '    autoLoadedOk = false;\n'
    '    autoStaleBanner(true);\n'
    '    if (Date.now() - autoStaleNotifiedAt > 60000) {\n'
    '      autoStaleNotifiedAt = Date.now();\n'
    '      addLocal(\'[错误] 自动化设置没加载成功：已禁止保存（否则会把开关写成"关"）。\'\n'
    "               + '刷新页面重新登录后重试。');\n"
    '    }\n'
    '    return;\n'
    '  }\n'
    '  autoLoadedOk = true;\n'
    '  autoStaleBanner(false);\n'
    '  const st = data.settings || {};\n'
    "  document.getElementById('auto_enabled').checked = !!st.enabled;\n"
    "  document.getElementById('auto_run_at').value = st.run_at || '01:00';\n"
    "  document.getElementById('auto_markup').value = st.markup || '';\n"
    "  document.getElementById('auto_fee').value = st.fee || '';\n"
    "  document.getElementById('auto_delist_enabled').checked = !!st.delist_enabled;\n"
    "  document.getElementById('auto_delist_at').value = st.delist_at || '01:00';\n"
    "  document.getElementById('auto_delist_protect').value = (st.delist_protect || []).join('\\n');\n"
    '  RP_PROTECT = (st.delist_protect || []).slice();   // ⑤ 表的「🚫 不下架」按钮要用\n'
    '  rpProtectCount();\n'
    '  autoRender(data);\n'
    '}\n'
    '\n'
    '// 「最近运行」列表：新的在上面，一行一轮（类型 · 时间 · 结果摘要）。\n'
    'function _renderHistory(rows) {\n'
    "  const box = document.getElementById('auto_hist');\n"
    "  const sum = document.getElementById('auto_hist_sum');\n"
    '  if (!box) return;\n'
    '  if (!rows.length) {\n'
    '    box.innerHTML = \'<span class="hint">还没有运行历史</span>\';\n'
    "    if (sum) sum.textContent = '（还没有记录）';\n"
    '    return;\n'
    '  }\n'
    '  // 收起时摘要行就够用：条数 + 最近一次的类型/时间/结果\n'
    '  const lastRow = rows[rows.length - 1];\n'
    '  if (sum) {\n'
    "    const kind = lastRow.kind === 'delist' ? '自动下架' : '采集改价';\n"
    "    const when = String(lastRow.started_at || '').slice(0, 14) || '—';\n"
    "    const detail = (lastRow.steps || []).map(function (x) { return x.detail; }).filter(Boolean).join('；');\n"
    "    sum.textContent = '（' + rows.length + ' 条）最近：' + (lastRow.ok ? '✅' : '❌') + ' ' + kind + ' · ' + when\n"
    "      + ((lastRow.trigger === 'auto') ? '（定时）' : '（手动）')\n"
    "      + (detail ? ' · ' + detail.slice(0, 40) : '') + '\u3000— 点这里展开/收起';\n"
    '  }\n'
    '  box.innerHTML = rows.slice().reverse().map(function (r) {\n'
    "    const kind = r.kind === 'delist' ? '自动下架' : '采集改价';\n"
    "    const when = String(r.started_at || '').slice(0, 14) || '—';\n"
    "    const detail = (r.steps || []).map(function (x) { return x.detail; }).filter(Boolean).join('；');\n"
    "    const tail = (r.trigger === 'auto' ? '（定时）' : '（手动）');\n"
    '    return \'<div class="hint">\' + (r.ok ? \'✅\' : \'❌\') + \' <b>\' + esc(kind) + \'</b> · \'\n'
    "         + esc(when) + tail + ' · ' + esc(detail.slice(0, 80) || (r.ok ? '完成' : '失败')) + '</div>';\n"
    "  }).join('');\n"
    '}\n'
    '\n'
    'function autoRender(data) {\n'
    '  const st = data.settings || {};\n'
    '  const running = data.running;\n'
    '  // 状态徽标\n'
    "  const pState = document.getElementById('auto_pipeline_state');\n"
    "  pState.className = 'auto-state ' + (running === 'pipeline' || (running && running !== 'delist') ? 'busy'\n"
    "    : (st.enabled ? 'on' : ''));\n"
    "  pState.textContent = running && running !== 'delist' ? `执行中：${running}`\n"
    "    : (st.enabled ? `已启用 · 下次 ${data.next_pipeline || '—'}` : '已停用');\n"
    "  const dState = document.getElementById('auto_delist_state');\n"
    "  dState.className = 'auto-state ' + (running === 'delist' ? 'busy' : (st.delist_enabled ? 'on' : ''));\n"
    "  dState.textContent = running === 'delist' ? '执行中：自动下架'\n"
    "    : (st.delist_enabled ? `已启用 · 下次 ${data.next_delist || '—'}` : '已停用');\n"
    '  // 时间线\n'
    '  const last = data.last_pipeline || {};\n'
    "  _renderSteps('auto_steps', running && running !== 'delist' ? { ...last, running: true } : last);\n"
    '  const lastD = data.last_delist || {};\n'
    "  _renderSteps('auto_delist_steps', running === 'delist' ? { ...lastD, running: true } : lastD);\n"
    '  _renderHistory(data.history || []);\n'
    '}\n'
    '\n'
    'async function autoPoll() {\n'
    '  // 只在「正在跑」或刚跑完一轮时高频刷新；平时 5 秒一次也不重\n'
    "  const data = await fetch(BASE + '/api/auto').then(r => r.json()).catch(() => null);\n"
    '  if (!data || !data.ok) return;\n'
    '  autoRender(data);\n'
    '  const running = data.running;\n'
    '  if (autoWasRunning && !running) {\n'
    '    // 一轮刚结束：弹一次汇总，日志区里有完整过程\n'
    "    const rec = autoWasRunning === 'delist' ? data.last_delist : data.last_pipeline;\n"
    '    if (rec) {\n'
    '      const failed = (rec.steps || []).filter(s => !s.ok);\n'
    "      alert(`自动化（${autoWasRunning === 'delist' ? '自动下架' : '采集改价'}）${rec.ok ? '全部完成' : '中途失败'}：\\n` +\n"
    "        (rec.steps || []).map(s => `${s.ok ? '✓' : '✗'} ${s.name}${s.detail ? ' —— ' + s.detail : ''}`).join('\\n') +\n"
    "        (failed.length ? `\\n\\n失败原因见操作日志。` : ''));\n"
    '    }\n'
    '  }\n'
    '  autoWasRunning = running || null;\n'
    '}\n'
    '\n'
    '// 只发**用户真改过的那一个字段**（后端 update() 只改传进来的键）。\n'
    '// 整表单回写 = 把页面里那份可能过期的状态钉死到服务端 —— 这正是开关"老是被关"的原因。\n'
    'async function autoSave(patch) {\n'
    "  if (!patch || typeof patch !== 'object') return;\n"
    '  if (!autoLoadedOk) {\n'
    "    alert('自动化设置没加载成功（多半是统一登录过期）。\\n'\n"
    '          + \'现在保存会把没读到的开关写成"关"，所以先刷新页面重新登录。\');\n'
    '    return;\n'
    '  }\n'
    "  const data = await api('/api/auto/save', patch);\n"
    '  if (data.ok) { autoRender(data); show(data); }\n'
    '}\n'
    '\n'
    'async function autoRun(kind) {\n'
    "  if (!confirm(kind === 'delist'\n"
    "    ? '立即比对并下架「没采到的」过期模型？\\n（导入表里还有的、手工建的都不会动）'\n"
    "    : '立即跑一整轮：采集 → 上架 → 拉现价 → 水印 → 取每金币价 → 用采集金币价 → 改价？\\n（全程可能需要几分钟）')) return;\n"
    "  const data = await api('/api/auto/run', { kind });\n"
    '  if (data.ok) { autoWasRunning = kind; autoPoll(); }\n'
    '}\n'
    '\n'
    '// 预览：只列名单、不写后台（上线/改口径前先看影响面）\n'
    'async function delistDryRun() {\n'
    "  const data = await api('/api/delist', { dry_run: true });\n"
    '  if (!data.ok) return;\n'
    '  const names = (data.details || []).map(d => `· ${d.title}（模型 ${d.mid}）`);\n'
    '  alert(`【预览·不会下架】\\n后台模型 ${data.total} 个：\\n` +\n'
    '        `将会下架 ${data.delisted} 个、在产保留 ${data.kept} 个、原本就是灭的 ${data.skipped} 个。\\n\\n` +\n'
    "        (names.length ? '会被下架的清单：\\n' + names.slice(0, 40).join('\\n') +\n"
    "          (names.length > 40 ? `\\n… 等 ${names.length} 个` : '') : '没有需要下架的。'));\n"
    '  show(data);\n'
    '}\n'
    '</script>\n'
    '</body>\n'
    '</html>\n'
)

# 云端部署：把 URL 前缀注入前端（本地 BASE_PREFIX 为空串，注入后是 ""）。
# 前端所有 API 调用都经 `BASE + path` 拼接，路由侧用 _route_path() 剥前缀，两边对齐。
PAGE = PAGE.replace("__BASE_PREFIX__", json.dumps(BASE_PREFIX))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 端口被占用时给出人话提示，而不是一段 traceback
    try:
        httpd = ThreadingHTTPServer((HOST, port), Handler)
    except OSError as exc:
        sys.stderr.write(
            f"\n[启动失败] 无法监听 {HOST}:{port} —— {exc}\n"
            f"  该端口可能已被占用。换个端口再试，例如：\n"
            f"      python webapp.py {port + 1}\n"
            f"  或双击启动脚本时带上端口号。\n\n"
        )
        raise SystemExit(3) from exc

    url = f"http://{HOST}:{port}/"
    print("=" * 58)
    print("  FC27 SBC / Packs 自动上架工具")
    print("=" * 58)
    print(f"  界面地址：{url}")
    print(f"  只监听本机（{HOST}），不对外开放。关闭本窗口即停止工具。")
    print(f"  端口被占用时可换端口：python webapp.py {port + 1}")
    print("=" * 58)
    print()

    # ⑥ 自动化调度（定时采集改价 / 自动下架）
    AUTOMATION.start()

    # 可选：恢复上次「记住的登录状态」（默认没有这个文件，就照常要求登录）

    # 无人值守 / 自动化运行时可以设 FC27_NO_BROWSER=1 跳过自动开浏览器
    if not os.environ.get("FC27_NO_BROWSER"):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
