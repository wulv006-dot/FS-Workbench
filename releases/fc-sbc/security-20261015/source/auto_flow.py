# -*- coding: utf-8 -*-
"""⑥ 自动化：定时「采集 → 上架 → 拉现价 → 水印 → 取每金币价 → 用采集金币价 → 改价」
与「自动下架」。

## 与既有结构的关系

* **不做任何新的后台写法**：每一步都调用 webapp 里*用户手点的那条*链路
  （do_fetch / do_execute / do_goods_list / do_watermark_models / do_fetch_rates /
  do_reprice / do_delist），保证「自动化做的 = 用户手点的」。
* **锁**：全应用只有一把 ``SESSION.busy``。自动化是重任务，照 ``run(gate=True)``
  的语义占锁 —— 占不到（用户正在操作）就本轮跳过、下一轮重试，绝不抢。
* **设置落盘**：``output/auto_settings.json``，结构见 :class:`AutoSettings`。
* **触发时机**：每 20 秒醒一次。判断「今天 configured 的 HH:MM 已过 且 今天还没跑过」
  —— 这样服务哪怕 01:30 才启动、设置的是 01:00，也会补跑当天那一轮。

## 顺序

用户口径（2026-10-15）：先采集 SBC（+Packs），上架，拉后台各区现价，一键添加水印，
按 MMOEXP 取回最新每金币价，用采集的金币价，最后改价。
自动下架默认同一时间，**排在整个链路之后**（要用本轮采集结果做比对）。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import traceback
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #

_DEFAULTS: dict[str, Any] = {
    # —— 自动采集改价 ——
    "enabled": False,
    "run_at": "01:00",            # 每日执行时间（服务器本地时间 HH:MM）
    "markup": "",                 # 上架计价加成；空 = 用 pricing.DEFAULT_MARKUP
    "fee": "",                    # 上架计价手续费；空 = 用 pricing.BASE_FEE
    "min_coins": 10000,           # SBC 唯一闸门
    # —— 自动下架 ——
    "delist_enabled": False,
    "delist_at": "01:00",
    # 永不自动下架的标题（每项一条；支持 * 通配，大小写不敏感）。
    # 采集表里没有 ≠ 过期 —— 手工建的商品（球员包 / 赛季通行证之类）不在采集表里，
    # 没有这张名单就会被误下架（2026-10-15 预览实测发现）。
    "delist_protect": [],
    # —— 运行状态（只读区，由 runner 维护） ——
    "last_pipeline": None,        # {date, started_at, finished_at, trigger, ok, steps:[…]}
    "last_delist": None,
    "running": None,              # 正在跑的步骤名（内存里有真值，落盘只为崩溃后留痕）
}

_TIME_FMT = "%H:%M"


def _valid_time(text: Any) -> str:
    s = str(text or "").strip()
    try:
        datetime.strptime(s, _TIME_FMT)
    except ValueError:
        raise ValueError(f"时间格式应为 HH:MM（如 01:00），收到 {text!r}") from None
    return s


class AutoSettings:
    """output/auto_settings.json 的读写。只存数据，不存逻辑。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, Any] = dict(_DEFAULTS)

    # -- 读写 --
    def load(self) -> "AutoSettings":
        merged = dict(_DEFAULTS)
        if self.path.is_file():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    merged.update(stored)
            except (OSError, ValueError):
                # 坏文件当默认值（这是设置文件，不是用户数据，无需 raise）
                pass
        self.data = merged
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".auto-settings-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(self.data, ensure_ascii=False, indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if os.name == "posix":
                directory = os.open(str(self.path.parent), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    # -- 便捷字段 --
    @property
    def enabled(self) -> bool:
        return bool(self.data.get("enabled"))

    @property
    def delist_enabled(self) -> bool:
        return bool(self.data.get("delist_enabled"))

    def update(self, body: dict) -> dict:
        """应用界面提交的设置；返回「改了哪些字段」。非法值抛 ValueError。"""
        changed: list[str] = []
        if "enabled" in body:
            value = bool(body["enabled"])
            if value != self.data["enabled"]:
                changed.append("enabled")
            self.data["enabled"] = value
        if "run_at" in body:
            value = _valid_time(body.get("run_at"))
            if value != self.data["run_at"]:
                changed.append("run_at")
            self.data["run_at"] = value
        if "delist_enabled" in body:
            value = bool(body["delist_enabled"])
            if value != self.data["delist_enabled"]:
                changed.append("delist_enabled")
            self.data["delist_enabled"] = value
        if "delist_at" in body:
            value = _valid_time(body.get("delist_at"))
            if value != self.data["delist_at"]:
                changed.append("delist_at")
            self.data["delist_at"] = value
        for key in ("markup", "fee"):
            if key in body:
                text = str(body.get(key) or "").strip()
                if text:
                    from decimal import Decimal, InvalidOperation
                    try:
                        Decimal(text)
                    except InvalidOperation:
                        raise ValueError(f"{key} 应为数字，收到 {body.get(key)!r}") from None
                if text != self.data[key]:
                    changed.append(key)
                self.data[key] = text
        if "delist_protect" in body:
            raw = body.get("delist_protect")
            if isinstance(raw, str):
                entries = [line.strip() for line in raw.splitlines()]
            elif isinstance(raw, (list, tuple)):
                entries = [str(x).strip() for x in raw]
            else:
                raise ValueError(f"delist_protect 应为列表或按行文本，收到 {type(raw).__name__}")
            entries = [e for e in entries if e]
            if entries != self.data["delist_protect"]:
                changed.append("delist_protect")
            self.data["delist_protect"] = entries
        if "min_coins" in body:
            try:
                value = int(body.get("min_coins") or 10000)
            except (TypeError, ValueError):
                raise ValueError(f"min_coins 应为整数，收到 {body.get('min_coins')!r}") from None
            if value != self.data["min_coins"]:
                changed.append("min_coins")
            self.data["min_coins"] = value
        return {"changed": changed}


# --------------------------------------------------------------------------- #
# 到期判断
# --------------------------------------------------------------------------- #

def _parse_at(text: str) -> tuple[int, int]:
    hh, mm = _valid_time(text).split(":")
    return int(hh), int(mm)


def is_due(now: datetime, at: str, done_date: Optional[str]) -> bool:
    """「今天 configured 时刻已过 且 今天还没跑过」。

    用"当天已跑"而不是"距上次 24h"：凌晨 1 点的任务，白天重启服务不该再跑一遍。
    """
    hh, mm = _parse_at(at)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now >= target and (done_date or "") != now.strftime("%Y-%m-%d")


def next_run_text(at: str, now: Optional[datetime] = None) -> str:
    """下一次会执行的时刻（人看的）：今天没跑且已过点 → 就是现在；否则明天该时刻。"""
    now = now or datetime.now()
    hh, mm = _parse_at(at)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return target.strftime("%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# 自动化引擎
# --------------------------------------------------------------------------- #

def _host_get(host: Any, key: str) -> Any:
    """取 host 上的能力。**兼容 dict 与对象两种形态**。

    ⚠️ 2026-10-15 踩过：webapp 用 ``bind({...})``（dict）传进来，而这里写的是
    ``host.session``（属性访问）—— 任务线程第一行就 ``AttributeError``，
    而且抛在 try 之外 ⇒ 状态永远卡在 running、日志空白、没有留痕。
    dict / 对象两种都支持，谁都别再踩。
    """
    if isinstance(host, Mapping):
        return host[key]
    return getattr(host, key)


class Automation:
    """绑定 webapp 的步骤函数后，负责定时触发与逐步执行。

    webapp 在 main() 里 ``Automation.start(host)``；host 是一个带以下键的对象：
    fetch_sbc / fetch_packs / execute / pull_goods / watermark / fetch_rates /
    fill_coins / reprice / delist / reload_rows / log / settings(全局 repricer.Settings)
    """

    TICK_SECONDS = 20

    def __init__(self, settings_path: str | Path):
        self.settings_path = Path(settings_path)
        self._host: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        # 与 SESSION.busy 分开的「自动化正在跑」标记：调度线程与手动触发都要抢它，
        # 防止同一个链路被并发拉起两份（SESSION.busy 只是 HTTP 侧的闸）。
        self._job_lock = threading.Lock()
        self._job_running: Optional[str] = None

    # -- 生命周期 --
    def bind(self, host: Any) -> None:
        self._host = host

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fc27-auto", daemon=True)
        self._thread.start()
        # 启动就报一行（用户要能在日志里看到"定时器活着"），顺带把当前设置摊开
        if self._host is not None:
            try:
                st = AutoSettings(self.settings_path).load()
                _host_get(self._host, "log")(
                    "⑥ 自动化调度已启动："
                    + (f"自动采集改价 每日 {st.data['run_at']}；" if st.enabled
                       else "自动采集改价 已停用；")
                    + (f"自动下架 每日 {st.data['delist_at']}（每 20 秒检查一次）"
                       if st.delist_enabled else "自动下架 已停用（每 20 秒检查一次）"))
            except Exception:  # noqa: BLE001 —— 启动日志失败不影响调度
                pass

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def status(self) -> dict:
        st = AutoSettings(self.settings_path).load()
        return {
            "settings": {k: st.data.get(k) for k in (
                "enabled", "run_at", "markup", "fee", "min_coins",
                "delist_enabled", "delist_at", "delist_protect")},
            "running": self._job_running,
            "next_pipeline": next_run_text(st.data["run_at"]) if st.enabled else None,
            "next_delist": next_run_text(st.data["delist_at"]) if st.delist_enabled else None,
            "last_pipeline": st.data.get("last_pipeline"),
            "last_delist": st.data.get("last_delist"),
        }

    # -- 调度 --
    def _loop(self) -> None:
        while not self._stop.wait(self.TICK_SECONDS):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 —— 调度线程绝不能死
                try:
                    self._log("⚠️ 自动化调度异常：" + traceback.format_exc(limit=3))
                except Exception:  # noqa: BLE001
                    pass

    def _tick(self) -> None:
        if self._host is None or self._job_running:
            return
        st = AutoSettings(self.settings_path).load()
        now = datetime.now()
        if st.enabled and is_due(now, st.data["run_at"],
                                 (st.data.get("last_pipeline") or {}).get("date")):
            self.run_pipeline(trigger="auto")
            return
        if st.delist_enabled and is_due(now, st.data["delist_at"],
                                        (st.data.get("last_delist") or {}).get("date")):
            self.run_delist(trigger="auto")

    # -- 手动触发（界面按钮 / 测试） --
    def run_pipeline(self, *, trigger: str = "manual") -> dict:
        with self._job_lock:
            if self._job_running:
                return {"ok": False, "error": "已有一轮自动化在跑"}
            self._job_running = "pipeline"
        thread = threading.Thread(target=self._pipeline_job, kwargs={"trigger": trigger},
                                  name="fc27-auto-pipeline", daemon=True)
        thread.start()
        return {"ok": True, "started": "pipeline"}

    def run_delist(self, *, trigger: str = "manual") -> dict:
        with self._job_lock:
            if self._job_running:
                return {"ok": False, "error": "已有一轮自动化在跑"}
            self._job_running = "delist"
        thread = threading.Thread(target=self._delist_job, kwargs={"trigger": trigger},
                                  name="fc27-auto-delist", daemon=True)
        thread.start()
        return {"ok": True, "started": "delist"}

    # -- 执行体 --
    def _acquire_busy(self) -> bool:
        """占全局锁；占不到说明用户正在操作，本轮放弃（调度会重试）。"""
        session = _host_get(self._host, "session")
        with session.lock:
            if session.busy:
                return False
            session.busy = True
        return True

    def _release_busy(self) -> None:
        session = _host_get(self._host, "session")
        with session.lock:
            session.busy = False

    def _log(self, text: str) -> None:
        """往界面日志打一行（失败也不能影响任务本身）。"""
        try:
            _host_get(self._host, "log")(text)
        except Exception:  # noqa: BLE001
            pass

    _PIPELINE_STEPS = (
        ("① 采集 SBC（FUT.GG）", "fetch_sbc"),
        ("② 采集 Packs（FUTGenie）", "fetch_packs"),
        ("③ 上架（含补 set_id）", "execute"),
        ("④ 拉取后台各区现价", "pull_goods"),
        ("⑤ 一键添加水印", "watermark"),
        ("⑥ 按 MMOEXP 取回最新每金币价", "fetch_rates"),
        ("⑦ 用采集的金币价", "fill_coins"),
        ("⑧ 改价", "reprice"),
    )

    @staticmethod
    def _record(trigger: str) -> dict:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "started_at": datetime.now().strftime("%m-%d %H:%M:%S"),
            "trigger": trigger, "ok": False, "steps": [],
        }

    def _pipeline_job(self, *, trigger: str) -> None:
        record = self._record(trigger)
        got = False
        postponed = False
        try:
            got = self._acquire_busy()
            if not got:
                # 推迟**不算"今天已跑"**（不落痕）—— 下个 tick 会再试
                postponed = True
                self._log("自动化：用户正在操作（忙），本轮自动采集改价推迟（稍后自动重试）")
                return
            self._log(f"自动化：开始执行整条链（触发={'定时' if trigger == 'auto' else '手动'}）")
            steps: list[dict] = record["steps"]
            for name, key in self._PIPELINE_STEPS:
                if self._stop.is_set():
                    break
                self._job_running = name
                entry = {"name": name, "ok": False, "detail": ""}
                try:
                    result = _host_get(self._host, key)()
                    entry["ok"] = isinstance(result, dict) and result.get("ok") is True
                    entry["detail"] = _summarize(name, result)
                except Exception as exc:  # noqa: BLE001 —— 单步失败要留下原因
                    entry["detail"] = f"{type(exc).__name__}: {exc}"
                    steps.append(entry)
                    self._log(f"自动化｜{name} 失败：{exc}")
                    break
                steps.append(entry)
                if not entry["ok"]:
                    self._log(f"自动化｜{name} 未成功，停止后续步骤：{entry['detail']}")
                    break
                self._log(f"自动化｜{name} 完成：{entry['detail']}")
            else:
                record["ok"] = True
        except Exception as exc:  # noqa: BLE001 —— 兜底：任何意外都必须留痕 + 复位状态
            # ⚠️ 2026-10-15 事故：host 能力取不到时抛在 try 之外，线程静默死掉
            #    ⇒ 状态卡在 running、日志空白、没有留痕。这条兜底就是防它再来。
            record["steps"].append({"name": "内部错误", "ok": False,
                                    "detail": f"{type(exc).__name__}: {exc}"})
            self._log(f"自动化｜内部错误（已中止本轮）：{type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            # ⚠️ 先落痕再清"正在跑"：轮询方看到 running=None 时，记录必须已经可读，
            #    否则会读到"跑完了但 last_pipeline 还是上一轮/没有"的中间态。
            if not postponed:
                record["finished_at"] = datetime.now().strftime("%m-%d %H:%M:%S")
                _save_record(self.settings_path, "last_pipeline", record)
            self._job_running = None
            if got:
                self._release_busy()

    def _delist_job(self, *, trigger: str) -> None:
        record = self._record(trigger)
        got = False
        postponed = False
        try:
            got = self._acquire_busy()
            if not got:
                postponed = True
                self._log("自动化：用户正在操作（忙），本轮自动下架推迟（稍后自动重试）")
                return
            self._job_running = "自动下架"
            entry = {"name": "自动下架", "ok": False, "detail": ""}
            try:
                result = _host_get(self._host, "delist")()
                entry["ok"] = isinstance(result, dict) and result.get("ok") is True
                entry["detail"] = _summarize("自动下架", result)
                record["ok"] = entry["ok"]
            except Exception as exc:  # noqa: BLE001
                entry["detail"] = f"{type(exc).__name__}: {exc}"
                self._log(f"自动化｜自动下架失败：{exc}")
            record["steps"].append(entry)
            self._log(f"自动化｜自动下架完成：{entry['detail']}")
        except Exception as exc:  # noqa: BLE001
            record["steps"].append({"name": "内部错误", "ok": False,
                                    "detail": f"{type(exc).__name__}: {exc}"})
            self._log(f"自动化｜自动下架内部错误：{type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            # 与流水线同口径：先落痕再清"正在跑"
            if not postponed:
                record["finished_at"] = datetime.now().strftime("%m-%d %H:%M:%S")
                _save_record(self.settings_path, "last_delist", record)
            self._job_running = None
            if got:
                self._release_busy()


def _summarize(step: str, result: Any) -> str:
    """把每步的返回压成一行人话（存进设置文件、显示在时间线上）。"""
    if not isinstance(result, dict):
        return "完成"
    parts: list[str] = []
    for key, label in (
        ("added", "新增"), ("created", "上架"), ("count", "行数"),
        ("updated", "改价"), ("delisted", "下架"), ("kept", "保留"),
        ("skipped", "跳过"), ("watermarked", "水印"), ("filled", "填金币"),
    ):
        value = result.get(key)
        if isinstance(value, int):
            parts.append(f"{label}{value}")
    message = result.get("message") or result.get("summary")
    if message:
        parts.append(str(message)[:80])
    return "，".join(parts) if parts else "完成"


def _save_record(settings_path: Path, key: str, record: dict) -> None:
    st = AutoSettings(settings_path).load()
    st.data[key] = record
    st.save()
