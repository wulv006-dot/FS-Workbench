"""PlayerMaintenanceApp 的流水线执行、事件轮询与日志历史。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
from dataclasses import is_dataclass
import json
from pathlib import Path
import queue
import threading
import time
from tkinter import END
from tkinter import Toplevel
from tkinter import messagebox
from tkinter import ttk
from typing import Any
from typing import Dict
from typing import Mapping
from typing import Optional
from 球员维护工具.admin_adapter import AdminAdapter
from 球员维护工具.admin_adapter import build_existing_model_map
from 球员维护工具.admin_adapter import extract_model_id
from 球员维护工具.admin_client import AdminHttpError
from 球员维护工具.existing_model_ui import build_unlist_action_preview
from 球员维护工具.models import PipelineConfig
from 球员维护工具.models import RunRecord
from 球员维护工具.models import StepName
from 球员维护工具.models import StepResult
from 球员维护工具.storage import atomic_write_json
from 球员维护工具.storage import redact_text
import sys

if __package__:
    from .app_constants import APP_DIR, STEP_LABELS
    from .app_formatters import _format_existing_model_action_error, _new_card_action_status, format_new_card_completion
    from .login_dialog import AdminLoginController
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_constants import APP_DIR, STEP_LABELS
    from 球员维护工具.app_formatters import _format_existing_model_action_error, _new_card_action_status, format_new_card_completion
    from 球员维护工具.login_dialog import AdminLoginController

class PipelineMixin:
    def _run_all(self) -> None:
        try:
            config = self._read_config()
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        if not config.selected_steps:
            messagebox.showwarning("没有步骤", "请至少勾选一个步骤")
            return
        self._start_worker("all", config)

    def _run_step(self) -> None:
        try:
            config = self._read_config()
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        label = self.single_step_var.get()
        step = next((name for name, text in STEP_LABELS.items() if text == label), label)
        self._start_worker(step, config)

    def _start_worker(self, mode: str, config: PipelineConfig) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "当前已有运行，请先停止或等待完成")
            return
        selected = config.selected_steps if mode == "all" else [mode]
        write_steps = [step for step in selected if step in {"import", "tags", "recommend", "sync"}]
        if write_steps:
            prep_steps = self._preparation_steps(config, selected)
            if prep_steps is None:
                messagebox.showwarning("缺少准备步骤", "本次导入没有 Excel 源文件，请同时选择导出和格式处理步骤。")
                return
            if prep_steps:
                self._set_running(True)
                self._begin_busy("正在准备本次导入文件…")
                self.status_var.set("正在准备本次导入文件…")
                self._append_log({"event": "preflight_started", "steps": prep_steps})
                prep_config = PipelineConfig.from_dict({**config.to_dict(), "selected_steps": prep_steps})

                def prepare_worker() -> None:
                    try:
                        record = self.runner.run_all(prep_config)
                        self.events.put(("preflight_ready", (record, config, mode, selected)))
                    except Exception as exc:
                        self.events.put(("worker_error", str(exc)))

                self.worker = threading.Thread(target=prepare_worker, name="fc27-player-preflight", daemon=True)
                self.worker.start()
                return
        if write_steps:
            preview = self._build_write_plan(config, selected)
            if not preview:
                messagebox.showwarning("无法确认后台范围", "当前批次还没有可核验的新增 FUTBIN ID或模型 ID；请先完成本次导入，或选择手动模型 ID范围。")
                return
            if not self._show_scrollable_confirmation("确认后台操作范围", preview):
                return
            if "import" in write_steps and getattr(self, "_pending_import_source", ""):
                config = PipelineConfig.from_dict({**config.to_dict(), "source_path": self._pending_import_source})
        self._set_running(True)
        self._begin_busy("运行中…")
        self.status_var.set("运行中…")
        self._append_log({"event": "ui_run_requested", "mode": mode})

        self._launch_pipeline_worker(mode, config)

    @staticmethod
    def _preparation_steps(config: PipelineConfig, selected: list[str]) -> Optional[list[str]]:
        """返回写入前需要完成的本地步骤；无法形成输入时返回 None。"""
        write_steps = [step for step in selected if step in {"import", "tags", "recommend", "sync"}]
        if "import" not in write_steps:
            return []
        prep: list[str] = []
        if "export" in selected:
            prep.append("export")
        if "transform" in selected:
            prep.append("transform")
        if not config.source_path and "export" not in prep:
            return None
        return prep

    def _launch_pipeline_worker(self, mode: str, config: PipelineConfig) -> None:
        write_requested = mode in {"import", "tags", "recommend", "sync"} or any(
            step in {"import", "tags", "recommend", "sync"} for step in config.selected_steps
        )

        def worker() -> None:
            try:
                access = self._temporary_backend_write() if write_requested else nullcontext()
                with access:
                    record = self.runner.run_all(config) if mode == "all" else self.runner.run_step(mode, config)
                self.events.put(("record", record))
            except Exception as exc:
                self.events.put(("worker_error", str(exc)))
            finally:
                self._force_backend_read_only()

        self.worker = threading.Thread(target=worker, name="fc27-player-pipeline", daemon=True)
        self.worker.start()

    def _build_write_plan(self, config: PipelineConfig, selected: list[str], prepared_source: Optional[str] = None) -> str:
        """生成写入前的具体范围清单；无法列出 ID 时拒绝泛化确认。"""
        if self.admin_adapter is None:
            return ""
        lines = ["本次将执行以下后台动作："]
        write_steps = [step for step in selected if step in {"import", "tags", "recommend", "sync"}]
        import_plan = None
        if "import" in write_steps:
            source = Path(prepared_source or config.source_path).expanduser() if (prepared_source or config.source_path) else None
            if source is None or not source.is_file():
                return ""
            try:
                import_plan = self.admin_adapter.plan_import(source)
            except Exception:
                return ""
            if not import_plan.upload_futbin_ids:
                return ""
            self._pending_import_source = str(getattr(import_plan, "upload_source_path", source))
            self._pending_import_ids = tuple(str(item) for item in import_plan.upload_futbin_ids)
            lines.append(f"导入后台：新增 FUTBIN ID {', '.join(import_plan.upload_futbin_ids)}（共 {len(import_plan.upload_futbin_ids)} 个）")
        for step in ("tags", "recommend", "sync"):
            if step not in write_steps:
                continue
            if step == "tags" and not config.manual_tag_ids:
                return ""
            if step == "recommend" and config.recommend_mode == "unchanged":
                continue
            scope = config.tag_scope if step == "tags" else config.recommend_scope if step == "recommend" else config.sync_scope
            if scope == "manual_ids":
                ids = [str(item) for item in config.manual_model_ids if str(item).strip()]
            else:
                ids = []
                if "import" in write_steps and import_plan is not None:
                    ids = [f"FUTBIN {item}" for item in import_plan.upload_futbin_ids]
            if not ids:
                return ""
            action = {"tags": "写入标签", "recommend": "设置推荐", "sync": "同步金币价"}[step]
            if step == "tags":
                extra = f"；标签 ID {', '.join(config.manual_tag_ids)}"
            elif step == "recommend":
                extra = f"；动作：{'开启' if config.recommend_mode == 'enable' else '关闭'}"
            else:
                extra = ""
            suffix = "（导入后仅使用本次 futbin_model_map 绑定）" if scope == "current_batch" and "import" in write_steps else ""
            lines.append(f"{action}：{', '.join(ids)}{extra}{suffix}")
        lines.append("策略：仅新增，不覆盖已有；导入必须通过后台任务终态和 FUTBIN 映射回读。确认后才执行；取消不会写入。")
        return "\n".join(lines)

    def _show_import_tasks(self) -> None:
        if self.admin_adapter is None:
            messagebox.showinfo("后台任务恢复", "请先完成后台登录；不会读取浏览器凭据。")
            return
        unresolved = {"uploading", "unknown", "unknown_response", "unknown_timeout", "unknown_status", "queued", "pending", "parsing", "importing", "processing", "done_unverified"}
        records = [dict(item) for item in self.admin_adapter.store.load() if str(item.get("status") or "") in unresolved]
        window = Toplevel(self.root)
        window.title("后台导入任务恢复（只轮询）")
        window.geometry("820x420")
        ttk.Label(window, text="这里只轮询已有 job_id，不会重新上传文件。请选择一个未决任务。", foreground="#555555").pack(anchor="w", padx=8, pady=8)
        tree = ttk.Treeview(window, columns=("job", "status", "count", "updated"), show="headings", selectmode="browse")
        for col, title, width in (("job", "任务 ID", 280), ("status", "状态", 130), ("count", "预期数量", 90), ("updated", "更新时间", 200)):
            tree.heading(col, text=title); tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for index, record in enumerate(records):
            tree.insert("", "end", iid=str(index), values=(record.get("job_id", ""), record.get("status", ""), record.get("expected_count", ""), record.get("updated_at", "")))
        restore = ttk.Button(window, text="恢复并轮询", state="normal" if records else "disabled")
        restore.pack(anchor="e", padx=8, pady=(0, 8))

        def start_restore() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("后台任务恢复", "请先选择任务", parent=window)
                return
            if self.worker and self.worker.is_alive():
                messagebox.showinfo("正在运行", "当前已有后台动作，请先等待完成", parent=window)
                return
            record = records[int(selected[0])]
            job_id = str(record.get("job_id") or "").strip()
            expected = [str(item) for item in (record.get("expected_futbin_ids") or []) if str(item).strip()]
            if not job_id or not expected or int(record.get("expected_count") or 0) < 1:
                messagebox.showerror("后台任务恢复", "任务记录缺少 job_id、预期数量或 FUTBIN ID，已阻断。", parent=window)
                return
            restore.configure(state="disabled")
            self.status_var.set(f"正在恢复任务 {job_id}（只轮询）…")

            def worker() -> None:
                try:
                    outcome = self.admin_adapter.track_import(job_id, expected_count=int(record["expected_count"]), expected_futbin_ids=expected)
                    self.events.put(("task_recovered", (job_id, outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome), window)))
                except Exception as exc:
                    self.events.put(("task_recovery_error", (job_id, str(exc), window)))
            self.worker = threading.Thread(target=worker, name="fc27-import-recovery", daemon=True)
            self.worker.start()

        restore.configure(command=start_restore)

    def _run_diagnostics(self) -> None:
        if self.admin_adapter is None:
            messagebox.showinfo("后台只读检查", "请先完成后台登录。此检查只读后台，不会写入。")
            return
        self.status_var.set("正在执行后台只读检查…")

        def worker() -> None:
            stage = "模型列表"
            more_sample = {"shape": "unknown", "count": None, "player_id": None, "player_id_type": None}
            try:
                client = self.admin_adapter.client
                page = client.list_models(page=1, limit=1, search=[{"field": "gid", "operator": "=", "val": "1327"}, {"field": "cid", "operator": "=", "val": "9627"}])
                shape_path = self.admin_adapter.store.root / "diagnostics" / "list_shape.json"
                shape = {
                    "checked_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
                    "query": {"page": 1, "limit": 1, "gid": 1327, "cid": 9627},
                    "total": page.total,
                    "list_length": len(page.rows),
                    "field_names": sorted({str(key) for row in page.rows for key in row}),
                }
                atomic_write_json(shape_path, shape)
                if not page.rows:
                    raise RuntimeError(f"后台模型列表没有可检查的 FC27/9627 模型；安全查询形状已保存：{shape_path}")
                model_row = dict(page.rows[0])
                raw_more = model_row.get("more")
                if isinstance(raw_more, str):
                    try:
                        raw_more = json.loads(raw_more)
                    except (TypeError, ValueError):
                        raw_more = None
                if isinstance(raw_more, Mapping):
                    raw_extend = raw_more.get("extend")
                    if isinstance(raw_extend, list):
                        more_sample = {"shape": "list", "count": len(raw_extend), "player_id": None, "player_id_type": None}
                        for entry in raw_extend:
                            if isinstance(entry, Mapping) and str(entry.get("key") or "") == "player_id":
                                value = entry.get("value")
                                more_sample["player_id"] = str(value) if value is not None else None
                                more_sample["player_id_type"] = type(value).__name__ if value is not None else None
                                break
                    elif isinstance(raw_extend, Mapping):
                        value = raw_extend.get("player_id")
                        more_sample = {"shape": "dict", "count": len(raw_extend), "player_id": str(value) if value is not None else None, "player_id_type": type(value).__name__ if value is not None else None}
                model_id = extract_model_id(model_row)
                if model_id is None:
                    raise RuntimeError("模型列表首行缺少明确模型 ID")
                stage = "模型详情"
                detail = dict(client.get_model(model_id))
                stage = "关联产品"
                products = [dict(item) for item in client.get_products(model_id)]
                stage = "标签"
                tags = [dict(item) for item in client.list_tags()]
                stage = "全量模型ID核验"
                all_models = self.admin_adapter.list_all_models()
                expected_total = int(page.total) if page.total is not None else None
                if expected_total is not None and len(all_models) != expected_total:
                    raise RuntimeError(f"全量模型数量与首页 total 不符：{len(all_models)} != {expected_total}")
                model_map = build_existing_model_map(all_models)
                if len(model_map) > len(all_models):
                    raise RuntimeError("全量 FUTBIN 映射数量超过模型总数")
                model_allowed = {"id", "gid", "cid", "title", "tid", "is_rec"}
                model_out = {key: value for key, value in detail.items() if key in model_allowed or "futbin" in str(key).lower()}
                more = detail.get("more")
                if isinstance(more, Mapping) and "extend" in more:
                    model_out["more_extend"] = more.get("extend")
                payload = {
                    "checked_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
                    "scope": {"gid": 1327, "cid": 9627, "model_id": model_id},
                    "existing_model_count": len(all_models),
                    "mapped_futbin_count": len(model_map),
                    "model_more_sample": more_sample,
                    "model": model_out,
                    "model_field_names": sorted(str(key) for key in detail),
                    "products": [{key: value for key, value in item.items() if key in {"id", "mid", "gid", "cid", "aid", "site_id"} or "price" in str(key).lower()} for item in products],
                    "product_field_names": sorted({str(key) for item in products for key in item}),
                    "tags": [{key: value for key, value in item.items() if key in {"id", "title", "name", "tag_name"}} for item in tags],
                    "tag_field_names": sorted({str(key) for item in tags for key in item}),
                }
                target = self.admin_adapter.store.root / "diagnostics" / "latest.json"
                atomic_write_json(target, payload)
                atomic_write_json(self.admin_adapter.store.root / "diagnostics" / "status.json", {"status": "success", "stage": stage, "existing_model_count": len(all_models), "mapped_futbin_count": len(model_map)})
                self.events.put(("diagnostics_success", str(target)))
            except Exception as exc:
                if isinstance(exc, AdminHttpError):
                    diagnostic = exc.diagnostic if isinstance(exc.diagnostic, Mapping) else {}
                    method = str(diagnostic.get("method") or "").upper()
                    endpoint = str(diagnostic.get("endpoint") or "")
                    safe_context = "；".join(item for item in (f"HTTP状态：{exc.status}" if exc.status is not None else "", f"方法：{method}" if method else "", f"端点：{endpoint}" if endpoint else "") if item)
                    message = f"阶段：{stage}；异常类型：AdminHttpError" + (f"；{safe_context}" if safe_context else "")
                else:
                    message = f"阶段：{stage}；异常类型：{type(exc).__name__}"
                try:
                    atomic_write_json(self.admin_adapter.store.root / "diagnostics" / "status.json", {"status": "failed", "stage": stage, "error_type": type(exc).__name__, "model_more_sample": more_sample})
                except Exception:
                    pass
                self.events.put(("diagnostics_error", message))
        threading.Thread(target=worker, name="fc27-admin-diagnostics", daemon=True).start()

    def _stop(self) -> None:
        if self.worker and self.worker.is_alive():
            self.runner.request_stop()
            self.status_var.set("已请求停止；等待当前动作安全结束…")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_all_button.configure(state=state)
        self.run_step_button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    # ---- 运行中反馈：动画 + 计时 + 进度条 ----
    #
    # 长任务（尤其逐模型读写）跑起来后界面完全静止，用户分不清「在跑」还是
    # 「卡死」。这里做三件事：①状态栏一个小转轮持续动画；②显示已用时长；
    # ③底部进度条（已知总量走 determinate，未知走 indeterminate）。

    _BUSY_FRAMES = ("◐", "◓", "◑", "◒")

    def _begin_busy(self, text: str, *, total: int = 0) -> None:
        """进入「运行中」：按钮禁用 + 动画 + 计时 + 进度条。

        ``total`` > 0 时进度条为确定态（用于逐模型写入），否则为滚动动画。
        """

        self._busy_active = True
        self._busy_frame = 0
        self._busy_total = int(total)
        self._busy_done = 0
        self._busy_label_text = text
        self._busy_started_at = time.monotonic()
        self.status_var.set(text)
        if getattr(self, "busy_progress", None) is not None:
            self.busy_progress.pack(fill="x", pady=(0, 6))
            if self._busy_total > 0:
                self.busy_progress.configure(mode="determinate", maximum=self._busy_total, value=0)
            else:
                self.busy_progress.configure(mode="indeterminate")
                self.busy_progress.start(80)
        self._tick_busy()

    def _update_busy(self, text: str, *, done: int = -1, total: int = -1) -> None:
        """更新运行中文字与进度（不重启计时器）。"""

        if not getattr(self, "_busy_active", False):
            self._begin_busy(text, total=max(total, 0))
            return
        self._busy_label_text = text
        if total >= 0:
            self._busy_total = total
        if done >= 0:
            self._busy_done = done
        if getattr(self, "busy_progress", None) is not None and self._busy_total > 0:
            self.busy_progress.configure(mode="determinate", maximum=self._busy_total, value=min(self._busy_done, self._busy_total))

    def _end_busy(self) -> None:
        """退出「运行中」：停动画、收进度条。"""

        self._busy_active = False
        if getattr(self, "busy_progress", None) is not None:
            self.busy_progress.stop()
            self.busy_progress.pack_forget()
        if getattr(self, "busy_label", None) is not None:
            self.busy_label.configure(text="")
        if getattr(self, "busy_elapsed_label", None) is not None:
            self.busy_elapsed_label.configure(text="")

    def _tick_busy(self) -> None:
        """每 120ms 刷新一次转轮与已用时长；结束即自停。"""

        if not getattr(self, "_busy_active", False):
            return
        self._busy_frame = (self._busy_frame + 1) % len(self._BUSY_FRAMES)
        if getattr(self, "busy_label", None) is not None:
            self.busy_label.configure(text=self._BUSY_FRAMES[self._busy_frame])
        elapsed = int(time.monotonic() - getattr(self, "_busy_started_at", time.monotonic()))
        suffix = f"（已用时 {elapsed // 60:02d}:{elapsed % 60:02d}）"
        if getattr(self, "busy_elapsed_label", None) is not None:
            if self._busy_total > 0:
                suffix = f"（{min(self._busy_done, self._busy_total)}/{self._busy_total}）" + suffix
            self.busy_elapsed_label.configure(text=suffix)
        root = getattr(self, "root", None)
        # 测试里用 __new__ 构造的替身没有 root，只跳过动画续帧，不影响功能。
        if root is not None and hasattr(root, "after"):
            self._busy_after_id = root.after(120, self._tick_busy)

    def _set_existing_action_running(self, running: bool) -> None:
        """后台模型维护页的写入类按钮统一开关，防止重复点击。"""

        selector = getattr(self, "existing_model_selector", None)
        if selector is not None and hasattr(selector, "set_busy"):
            selector.set_busy(running)

    def _on_pipeline_event(self, event: str, payload: object) -> None:
        self.events.put((event, payload))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "preflight_ready":
                    prep_record, original_config, original_mode, original_selected = payload
                    if not isinstance(prep_record, RunRecord) or prep_record.status != "success":
                        self._force_backend_read_only()
                        self.status_var.set("本次导入准备失败，未执行后台写入")
                        self._set_running(False)
                        self._append_log({"event": "preflight_blocked", "status": getattr(prep_record, "status", "unknown")})
                        continue
                    source = ""
                    for step in prep_record.steps:
                        if step.step == StepName.TRANSFORM.value and step.status == "success":
                            source = str(step.result.get("output_path") or step.result.get("output") or "")
                        elif step.step == StepName.EXPORT.value and not source and step.status == "success":
                            source = str(step.result.get("output") or "")
                            if not source and step.result.get("outputs"):
                                source = str(step.result["outputs"][0])
                    if not source:
                        source = original_config.source_path
                    remaining = [step for step in original_selected if step in {"import", "tags", "recommend", "sync"}]
                    execution_config = PipelineConfig.from_dict({**original_config.to_dict(), "source_path": source, "selected_steps": remaining})
                    preview = self._build_write_plan(execution_config, remaining, prepared_source=source)
                    if not preview or not self._show_scrollable_confirmation("确认本次批次操作", preview):
                        self._force_backend_read_only()
                        self.status_var.set("已取消后台写入")
                        self._set_running(False)
                        continue
                    if "import" in remaining and getattr(self, "_pending_import_source", ""):
                        execution_config = PipelineConfig.from_dict({**execution_config.to_dict(), "source_path": self._pending_import_source, "selected_steps": remaining})
                    self.status_var.set("已确认本次批次，正在执行后台动作…")
                    self._launch_pipeline_worker("all", execution_config)
                elif event == "record":
                    self._force_backend_read_only()
                    self._end_busy()
                    record = payload
                    if isinstance(record, RunRecord):
                        self.status_var.set(f"运行结束：{record.status}")
                        self.run_dir_var.set(record.run_dir)
                        self._append_log({"event": "run_finished", **record.to_dict()})
                    self._set_running(False)
                    self._refresh_history()
                elif event == "run_started" and isinstance(payload, RunRecord):
                    self.run_dir_var.set(payload.run_dir)
                    self._append_log({"event": event, **payload.to_dict()})
                elif event == "step_started":
                    step = str(payload.get("step") or payload) if isinstance(payload, Mapping) else str(payload)
                    done_step = STEP_LABELS.get(step, step)
                    text = f"正在执行步骤：{done_step}…"
                    self.status_var.set(text)
                    self._update_busy(text)
                    self._append_log({"event": event, "payload": self._jsonable(payload)})
                elif event == "step_finished" and isinstance(payload, StepResult):
                    self._append_log({"event": event, **payload.to_dict()})
                elif event == "stop_requested":
                    self._append_log({"event": event, "payload": self._jsonable(payload)})
                elif event == "preview":
                    self.status_var.set("筛选预览完成")
                    self._show_preview(payload if isinstance(payload, dict) else {})
                elif event == "preview_error":
                    self.status_var.set("筛选预览失败")
                    messagebox.showerror("筛选预览失败", str(payload))
                elif event == "new_cards_ready":
                    days, search, rows, existing_map, total = payload
                    try:
                        self.new_card_basket.replace(rows)
                        self.new_card_existing_map = {str(key): int(value) for key, value in dict(existing_map or {}).items()}
                        self.new_card_backend_map_checked = self.admin_adapter is not None
                        self.new_card_basket.set_existing_models(self.new_card_existing_map)
                        self._refresh_new_card_tree()
                        self._save_new_card_selection(silent=True)
                        known = len(self.new_card_existing_map)
                        self.new_card_summary_var.set(f"最近 {days} 天新增 {total} 条；后台已识别 {known} 条；请逐行设置上架/标签/推荐")
                        self.status_var.set("最新球员已加载，请在新增球员上架页勾选操作范围")
                    finally:
                        self._set_new_card_fetch_running(False)
                elif event == "new_cards_error":
                    self._set_new_card_fetch_running(False)
                    self.new_card_summary_var.set("获取失败")
                    self.status_var.set("获取最新球员失败")
                    messagebox.showerror("获取最新球员", str(payload))
                elif event == "new_upload_ready":
                    self._set_new_card_fetch_running(False)
                    self.source_var.set(str(payload))
                    self.status_var.set(f"选中上架文件已生成：{payload}")
                    self.new_card_summary_var.set(f"选中上架文件已生成：{Path(str(payload)).name}")
                    messagebox.showinfo("生成选中上架文件", f"已生成仅含上架选择的文件：\n{payload}\n\n可到“配置与筛选”页单独运行 Excel 格式处理/导入步骤。")
                elif event == "new_upload_error":
                    self._set_new_card_fetch_running(False)
                    self.status_var.set("生成选中上架文件失败")
                    messagebox.showerror("生成选中上架文件", str(payload))
                elif event == "new_card_plan_ready":
                    self._confirm_new_card_plan_and_run(payload)
                elif event == "new_card_flow_finished":
                    self._force_backend_read_only()
                    self._set_new_card_fetch_running(False)
                    result = dict(payload) if isinstance(payload, Mapping) else {}
                    imported_ids = result.get("model_ids") if isinstance(result.get("model_ids"), (list, tuple)) else ()
                    existing_map = result.get("existing_model_map") if isinstance(result.get("existing_model_map"), Mapping) else {}
                    tag_ids = result.get("tag_model_ids") if isinstance(result.get("tag_model_ids"), (list, tuple)) else ()
                    recommend_ids = result.get("recommend_model_ids") if isinstance(result.get("recommend_model_ids"), (list, tuple)) else ()
                    import_status = _new_card_action_status(result, "import")
                    sync_status = _new_card_action_status(result, "sync")
                    self.status_var.set(
                        f"新卡批次完成：导入{import_status}；标签 {len(tag_ids)} 个模型；"
                        f"推荐 {len(recommend_ids)} 个模型；金币价同步{sync_status}；已有模型 {len(existing_map)} 条"
                    )
                    self._refresh_history()
                    self._append_log(
                        {
                            "event": "new_card_flow_finished",
                            "status": "success",
                            "import_status": import_status,
                            "sync_status": sync_status,
                            "import_count": len(imported_ids),
                            "existing_model_count": len(existing_map),
                            "tag_model_count": len(tag_ids),
                            "recommend_model_count": len(recommend_ids),
                        }
                    )
                    self._save_new_card_selection(silent=True)
                    messagebox.showinfo("新卡批次完成", format_new_card_completion(result))
                elif event == "new_card_flow_error":
                    self._force_backend_read_only()
                    self._set_new_card_fetch_running(False)
                    self.status_var.set("新卡流程已停止或失败")
                    self._refresh_history()
                    self._append_log({"event": "new_card_flow_error", "message": str(payload)})
                    messagebox.showerror("新卡流程", str(payload))
                elif event == "new_card_recovery_finished":
                    self._force_backend_read_only()
                    step, run_id, model_ids = payload
                    self._set_new_card_recovery_running(False)
                    self.status_var.set(f"历史批次单步完成并已回读：{run_id} / {STEP_LABELS.get(step, step)}")
                    self._append_log({"event": "new_card_recovery_finished", "step": step, "status": "success", "model_count": len(model_ids)})
                    self._refresh_new_card_batches()
                    self._refresh_history()
                    messagebox.showinfo(
                        "新卡批次单步完成",
                        f"批次 {run_id} 的“{STEP_LABELS.get(step, step)}”已完成，并通过后台回读核验。\n\n模型 ID：{', '.join(str(item) for item in model_ids)}",
                    )
                elif event == "new_card_recovery_error":
                    self._force_backend_read_only()
                    step, run_id, error_type, message = payload
                    self._set_new_card_recovery_running(False)
                    self.status_var.set(f"新卡批次单步失败或状态未知：{run_id}")
                    self._append_log({"event": "new_card_recovery_error", "step": step, "status": "partial_or_unknown", "message": message})
                    self._refresh_new_card_batches()
                    self._refresh_history()
                    messagebox.showerror(
                        "新卡批次单步未完成",
                        f"批次 {run_id} 的“{STEP_LABELS.get(step, step)}”未完成。\n异常类型：{error_type}\n{message}\n\n为避免重复提交，当前步骤已阻断重试；请先只读回查或手工处理。",
                    )
                elif event == "existing_models_ready":
                    try:
                        rows = payload if isinstance(payload, (list, tuple)) else ()
                        if self.existing_model_selector is not None:
                            self.existing_model_selector.set_rows(rows)
                        self.status_var.set(f"后台模型读取完成：{len(rows)} 条；请筛选并勾选后操作")
                    except Exception as exc:
                        self.status_var.set("后台模型数据无法安全显示")
                        messagebox.showerror("后台模型维护", str(exc))
                elif event == "existing_models_error":
                    self.status_var.set("后台模型读取失败")
                    messagebox.showerror("后台模型维护", str(payload))
                elif event == "existing_unlist_plan_ready":
                    frozen_ids, plan = payload
                    try:
                        text = build_unlist_action_preview(plan)
                        # 预检完成，先退出预检动画再进确认框，避免弹窗背后还在转。
                        self._end_busy()
                        self._set_existing_action_running(False)
                        if not self._show_scrollable_confirmation("确认执行下架", text):
                            self.status_var.set("已取消下架写入")
                            continue
                        ids_for_write = tuple(int(item) for item in frozen_ids)
                        self._begin_busy(f"正在执行 {len(ids_for_write)} 个模型下架并回读…", total=len(ids_for_write))
                        self._set_existing_action_running(True)
                        progress = self._progress_reporter("下架", len(ids_for_write))

                        def unlist_worker(ids: tuple[int, ...] = ids_for_write) -> None:
                            try:
                                with self._temporary_backend_write():
                                    outcome = self.admin_adapter.execute_unlist(ids, progress=progress)
                                self.events.put(("existing_unlist_done", (ids, outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome))))
                            except Exception as exc:
                                report = getattr(exc, "report", {})
                                status = str(report.get("status") or "partial_or_unknown") if isinstance(report, Mapping) else "partial_or_unknown"
                                self.events.put(("existing_unlist_error", f"下架结果：{status}；异常类型：{type(exc).__name__}；{redact_text(exc)}"))
                            finally:
                                self._force_backend_read_only()

                        self.worker = threading.Thread(target=unlist_worker, name="fc27-existing-unlist", daemon=True)
                        self.worker.start()
                    except Exception as exc:
                        self._end_busy()
                        self._set_existing_action_running(False)
                        self.status_var.set("下架预检结果无法显示")
                        messagebox.showerror("下架预检", redact_text(exc))
                elif event == "existing_unlist_plan_error":
                    self._end_busy()
                    self._set_existing_action_running(False)
                    self.status_var.set("下架预检失败，未写入")
                    messagebox.showerror("下架预检", str(payload))
                elif event == "existing_unlist_done":
                    self._force_backend_read_only()
                    self._end_busy()
                    self._set_existing_action_running(False)
                    ids_done, result = payload
                    status = str(result.get("status") or "completed_readback") if isinstance(result, Mapping) else "completed_readback"
                    effective = bool(result.get("effective_unlisted")) if isinstance(result, Mapping) else False
                    self.status_var.set(f"下架完成并回读：{len(ids_done)} 个；状态 {status}")
                    messagebox.showinfo("下架结果", f"已选择 {len(ids_done)} 个模型；后台字段回读状态：{status}。\n\n前台实际下架效果独立核验：{'已核验' if effective else '未独立证实'}。")
                    self._refresh_existing_models()
                elif event == "existing_unlist_error":
                    self._force_backend_read_only()
                    self._end_busy()
                    self._set_existing_action_running(False)
                    self.status_var.set("下架未完成或状态未知")
                    messagebox.showerror("下架结果", str(payload))
                elif event == "existing_action_progress":
                    label, stage, done, total = payload
                    text = f"正在{label}：{stage} {done}/{total}…"
                    self.status_var.set(text)
                    self._update_busy(text, done=done, total=total)
                elif event == "existing_model_action_done":
                    self._force_backend_read_only()
                    self._end_busy()
                    self._set_existing_action_running(False)
                    action, model_ids, result = payload
                    self.status_var.set(f"后台模型动作完成并已回读：{action}，{len(model_ids)} 个")
                    self._append_log({"event": "existing_model_action_done", "action": action, "model_count": len(model_ids), "verified": result.get("verified") if isinstance(result, Mapping) else None})
                    messagebox.showinfo("后台模型维护", f"已完成并通过回读核验：{len(model_ids)} 个模型。")
                    self._refresh_existing_models()
                elif event == "existing_model_action_error":
                    self._force_backend_read_only()
                    self._end_busy()
                    self._set_existing_action_running(False)
                    self.status_var.set("后台模型动作失败")
                    error_payload = payload if isinstance(payload, Mapping) else {
                        "error_type": "UnknownError",
                        "message": redact_text(payload),
                    }
                    log_payload = dict(error_payload)
                    report = log_payload.get("report")
                    if isinstance(report, Mapping) and report.get("status"):
                        log_payload["status"] = report.get("status")
                    self._append_log({"event": "existing_model_action_error", **log_payload})
                    messagebox.showerror("后台模型维护", _format_existing_model_action_error(error_payload))
                elif event == "existing_model_selection_ready":
                    self._set_existing_selection_running(False)
                    self.status_var.set("后台已有模型 ID 生成完成，等待确认替换")
                    self._show_existing_model_selection_preview(payload if isinstance(payload, Mapping) else {})
                elif event == "existing_model_selection_error":
                    self._set_existing_selection_running(False)
                    self.status_var.set("后台已有模型 ID 生成失败")
                    messagebox.showerror("生成后台已有模型 ID", str(payload))
                elif event == "worker_error":
                    self._force_backend_read_only()
                    self.status_var.set("运行失败")
                    self._set_running(False)
                    messagebox.showerror("流水线运行失败", str(payload))
                elif event == "captcha_ready":
                    self.status_var.set("验证码已获取，请输入账号、密码和验证码")
                    self._show_login_dialog(payload if isinstance(payload, bytes) else None)
                elif event == "captcha_error":
                    self.status_var.set("验证码获取失败")
                    messagebox.showerror("后台登录", str(payload))
                elif event == "login_success":
                    session, window = payload
                    self.backend_session = session
                    self.new_card_backend_map_checked = False
                    self.new_card_existing_map = {}
                    if isinstance(self.backend_login_handler, AdminLoginController):
                        self.admin_adapter = AdminAdapter(
                            self.backend_login_handler.client,
                            state_root=APP_DIR / "admin_state",
                            write_enabled=False,
                            stop_event=self.runner.stop_event,
                            workbook_filter=self._filter_existing_players,
                        )
                        self.runner.backend = self.admin_adapter
                    else:
                        self.runner.backend = self.backend_login_handler
                    self.status_var.set("后台登录会话已建立（仅内存）；正在自动读取后台模型列表…")
                    window.destroy()
                    # 登录后自动加载后台模型列表（只读）。延迟触发以避开尚未退出的
                    # 登录 worker 线程；失败不影响登录状态，用户仍可点击
                    # 「获取/刷新后台模型」手动重试。
                    self.root.after(500, self._refresh_existing_models)
                elif event == "login_error":
                    error, window = payload
                    self.new_card_backend_map_checked = False
                    window.destroy()
                    self.status_var.set("后台登录失败")
                    messagebox.showerror("后台登录失败", str(error))
                elif event == "task_recovered":
                    job_id, result, window = payload
                    self.status_var.set(f"后台任务已恢复并完成轮询：{job_id}")
                    self._append_log({"event": "task_recovered", "job_id": job_id, "result": result})
                    window.destroy()
                    self._set_running(False)
                elif event == "task_recovery_error":
                    job_id, error, window = payload
                    self.status_var.set(f"后台任务恢复失败：{job_id}")
                    self._append_log({"event": "task_recovery_error", "job_id": job_id, "message": error})
                    messagebox.showerror("后台任务恢复失败", str(error), parent=window)
                elif event == "diagnostics_success":
                    self.status_var.set("后台只读检查完成，已保存脱敏诊断")
                    self._append_log({"event": "diagnostics_success", "path": payload})
                    messagebox.showinfo("后台只读检查", f"完成，已保存：\n{payload}")
                elif event == "diagnostics_error":
                    self.status_var.set("后台只读检查失败")
                    self._append_log({"event": "diagnostics_error", "message": payload})
                    messagebox.showerror("后台只读检查失败", str(payload))
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _show_preview(self, payload: Dict[str, Any]) -> None:
        window = Toplevel(self.root)
        window.title("筛选球员预览（只读）")
        window.geometry("820x500")
        ttk.Label(window, text="只读预览：最多显示前 50 条；实际写入范围仍需明确后台模型 ID").pack(anchor="w", padx=8, pady=(8, 2))
        total = payload.get("total")
        items = payload.get("items", [])
        ttk.Label(window, text=f"总数：{total}；当前显示：{min(len(items), 50)}").pack(anchor="w", padx=8, pady=(0, 4))
        table = ttk.Treeview(window, columns=("name", "rating", "rare_type_name", "futbin_id"), show="headings")
        headings = {"name": "姓名", "rating": "评分", "rare_type_name": "卡版本", "futbin_id": "FUTBIN ID"}
        for column, heading in headings.items():
            table.heading(column, text=heading)
            table.column(column, width=180 if column in {"name", "rare_type_name"} else 110, anchor="w")
        scroll = ttk.Scrollbar(window, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        table.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=(0, 8))
        for item in items[:50]:
            table.insert("", END, values=(
                item.get("name", item.get("common_name", "")),
                item.get("rating", ""),
                item.get("rare_type_name", ""),
                item.get("futbin_id", ""),
            ))

    def _append_log(self, value: Dict[str, Any]) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(END, self._summary_text(value) + "\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    @staticmethod
    def _summary_text(value: Mapping[str, Any]) -> str:
        event = str(value.get("event") or "运行记录")
        event_labels = {"run_started": "运行开始", "run_finished": "运行结束", "step_started": "步骤开始", "step_finished": "步骤完成", "stop_requested": "已请求停止", "task_recovered": "后台任务恢复", "task_recovery_error": "后台任务恢复失败", "diagnostics_success": "后台只读检查完成", "diagnostics_error": "后台只读检查失败", "ui_run_requested": "已请求运行", "existing_model_action_error": "后台模型动作失败"}
        label = event_labels.get(event, event)
        timestamp = str(value.get("timestamp") or value.get("started_at") or value.get("finished_at") or "")
        step = str(value.get("step") or "")
        status = str(value.get("status") or "")
        if step:
            label += f"｜{STEP_LABELS.get(step, step)}"
        if status:
            label += f"｜状态：{status}"
        message = str(value.get("message") or value.get("error_message") or value.get("payload") or "")
        if message and len(message) > 180:
            message = message[:180] + "…"
        return f"{timestamp}  {label}" + (f"｜{message}" if message else "")

    def _refresh_history(self) -> None:
        history = self.store.load_history()
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", END)
        lines = []
        for item in history:
            lines.append(self._summary_text({"event": "run_finished", **item}))
            for step in item.get("steps", []):
                lines.append("  " + self._summary_text({"event": "step_finished", **step}))
            lines.append(f"  详情：{item.get('run_dir', '')}\\run.json")
        self.history_text.insert(END, ("\n".join(lines) if lines else "暂无运行历史") + "\n")
        self.history_text.configure(state="disabled")

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, Path):
            return str(value)
        return value


