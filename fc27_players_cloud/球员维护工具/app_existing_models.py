"""PlayerMaintenanceApp 的后台已有模型维护页。"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
from tkinter import Canvas
from tkinter import Text
from tkinter import Toplevel
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from typing import Any
from typing import Mapping
from typing import Optional
from 球员维护工具.existing_model_ui import ExistingModelSelector
from 球员维护工具.existing_model_ui import build_existing_action_preview
from 球员维护工具.existing_model_ui import format_futbin_id_export
from 球员维护工具.existing_model_ui import selected_futbin_ids
from 球员维护工具.existing_model_ui import widget_is_descendant
from 球员维护工具.storage import JsonlLogger
from 球员维护工具.storage import redact_text
import sys

if __package__:
    from .app_formatters import _safe_existing_model_action_error
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_formatters import _safe_existing_model_action_error

class ExistingModelsMixin:
    def _build_existing_model_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        canvas = Canvas(parent, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas, padding=(4, 4))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        self.existing_model_tab = parent
        self.existing_model_canvas = canvas
        self.existing_model_selector = ExistingModelSelector(
            body,
            manager=self.existing_model_manager,
            on_action=self._existing_model_action,
            on_refresh=self._refresh_existing_models,
            on_load_tags=self._load_tags,
            on_export=self._export_existing_futbin_ids,
        )
        self.existing_model_selector.pack(fill="x", expand=True)
        ttk.Label(body, text="标签、推荐和下架操作都会先显示完整范围供确认；下架仍要求全部模型与产品字段通过预检。", foreground="#8a5a00", wraplength=1050).pack(fill="x", pady=(6, 8), anchor="w")
        if not getattr(self, "_existing_model_wheel_bound", False):
            self.root.bind_all("<MouseWheel>", self._scroll_existing_model_page, add="+")
            self.root.bind_all("<Button-4>", self._scroll_existing_model_page, add="+")
            self.root.bind_all("<Button-5>", self._scroll_existing_model_page, add="+")
            self._existing_model_wheel_bound = True

    def _scroll_existing_model_page(self, event: Any) -> str | None:
        tab = getattr(self, "existing_model_tab", None)
        if tab is None or not tab.winfo_ismapped():
            return None
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if not widget_is_descendant(widget, tab):
            return None
        selector = self.existing_model_selector
        if selector is not None and widget in {selector.tree, selector._tree_vertical_scrollbar, selector._tag_listbox}:
            return None
        if getattr(event, "num", None) == 4:
            self.existing_model_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.existing_model_canvas.yview_scroll(1, "units")
        else:
            delta = int(getattr(event, "delta", 0) or 0)
            units = int(-delta / 120) or (-1 if delta > 0 else 1)
            self.existing_model_canvas.yview_scroll(units, "units")
        return "break"

    def _refresh_existing_models(self) -> None:
        if self.admin_adapter is None:
            messagebox.showinfo("后台模型维护", "请先完成后台登录；只读取 FC27 / Players 模型，不读取浏览器凭据。")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("后台模型维护", "当前已有动作，请等待完成")
            return
        self.status_var.set("正在完整读取后台模型…")

        def worker() -> None:
            try:
                rows = self.admin_adapter.list_all_models()
                self.events.put(("existing_models_ready", rows))
            except Exception as exc:
                self.events.put(("existing_models_error", f"读取失败；异常类型：{type(exc).__name__}；{exc}"))

        self.worker = threading.Thread(target=worker, name="fc27-existing-models", daemon=True)
        self.worker.start()

    def _show_scrollable_confirmation(
        self,
        title: str,
        preview: str,
        *,
        confirm_text: str = "确认执行",
        cancel_text: str = "取消（不写入）",
        informative: bool = False,
        headline: str = "",
    ) -> bool:
        """显示完整可滚动预览；只有确认按钮才返回 True。

        ``informative=True`` 用于「已阻断、不会写入」这类只读告知：此时**不显示
        确认按钮**，只留一个「我知道了」，避免用户误以为还能继续执行。

        ``headline`` 会固定显示在弹窗底部（不随正文滚动），用于放"本次不会写入
        任何模型"这类关键结论——正文很长时它不会被滚出视野。
        """

        window = Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.geometry("1020x680")
        window.minsize(760, 460)
        window.resizable(True, True)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        preview_frame = ttk.Frame(window, padding=10)
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        preview_text = Text(preview_frame, wrap="none", state="normal", width=120, height=32)
        vertical = ttk.Scrollbar(preview_frame, orient="vertical", command=preview_text.yview)
        horizontal = ttk.Scrollbar(preview_frame, orient="horizontal", command=preview_text.xview)
        preview_text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        if informative:
            preview_text.configure(background="#fff8e1")
        preview_text.insert("1.0", preview)
        preview_text.configure(state="disabled")
        preview_text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        # 弹窗打开时把正文滚到顶部，确保读到的是开头而不是中间。
        preview_text.see("1.0")

        # 固定摘要条：放在按钮正上方，正文再长也不会被滚掉。
        summary = headline.strip() or (
            "只有点击“确认执行”才会进入写入线程；取消或关闭此窗口不会写入。"
            if not informative
            else "以上为只读提示，本次没有向后台写入任何内容，关闭本窗口即可。"
        )
        headline_label = ttk.Label(
            window,
            text=summary,
            wraplength=960,
            justify="left",
            padding=(12, 6),
            foreground="#7a4a00" if informative else "#333333",
        )
        headline_label.grid(row=1, column=0, sticky="ew")

        actions = ttk.Frame(window, padding=(10, 0, 10, 10))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        confirmed = {"value": False}

        def cancel() -> None:
            window.destroy()

        def confirm() -> None:
            confirmed["value"] = True
            window.destroy()

        if informative:
            close_button = ttk.Button(actions, text="我知道了（未写入任何内容）", command=cancel)
            close_button.grid(row=0, column=2)
            focus_target = close_button
        else:
            ttk.Button(actions, text=cancel_text, command=cancel).grid(row=0, column=1, padx=(0, 6))
            confirm_button = ttk.Button(actions, text=confirm_text, command=confirm)
            confirm_button.grid(row=0, column=2)
            focus_target = confirm_button
        window.protocol("WM_DELETE_WINDOW", cancel)
        window.bind("<Escape>", lambda _event: cancel())
        focus_target.focus_set()
        window.grab_set()
        self.root.wait_window(window)
        return bool(confirmed["value"])


    def _temporary_backend_write(self):
        """返回一次 GUI 已确认动作的临时写入上下文。

        生产适配器提供自己的上下文管理器，内部仍保留
        ``write_enabled`` 门槛。测试替身或兼容适配器没有该方法时，使用同样
        的 fail-closed 生命周期：确认前不打开，退出后强制恢复只读。
        """

        adapter = self.admin_adapter
        if adapter is None:
            raise RuntimeError("后台会话不存在，未发起写入")
        access = getattr(adapter, "temporary_write_access", None)
        if callable(access):
            return access()

        class _FallbackWriteAccess:
            def __enter__(inner_self):
                inner_self.previous = bool(getattr(adapter, "write_enabled", False))
                setattr(adapter, "write_enabled", True)
                return adapter

            def __exit__(inner_self, _exc_type, _exc, _traceback):
                setattr(adapter, "write_enabled", False)
                return False

        return _FallbackWriteAccess()

    def _force_backend_read_only(self) -> None:
        """worker 收尾兜底，避免异常路径遗留写入状态。"""

        if self.admin_adapter is not None and hasattr(self.admin_adapter, "write_enabled"):
            self.admin_adapter.write_enabled = False

    def _persist_existing_model_action_error(self, payload: Mapping[str, Any]) -> None:
        """保存已有模型标签/推荐动作的安全失败记录。"""

        store = getattr(self, "store", None)
        app_dir = getattr(store, "app_dir", None)
        if not isinstance(app_dir, Path):
            return
        try:
            JsonlLogger(app_dir / "admin_state" / "model_actions.log.jsonl").write(
                "ERROR",
                "existing_model_action_error",
                message=str(payload.get("message") or ""),
                action=payload.get("action"),
                model_count=payload.get("model_count"),
                error_type=payload.get("error_type"),
                report=payload.get("report", {}),
            )
        except (OSError, TypeError, ValueError):
            # 记录失败不能覆盖原有后台动作错误，也不能阻断只读收尾。
            return

    def _empty_after_removal_ids(self, rows: tuple[object, ...], tag_ids: tuple[int, ...]) -> tuple[int, ...]:
        """找出「移除所选标签后会变成零标签」的模型。

        2026-09-28 生产实据：后台不接受空标签（``msg=请选择标签``），因此这类
        模型必须提前识别并阻断。判定完全基于当前只读列表里的标签快照——只有
        当快照中的每个标签都在待移除集合内时才会变空；快照未读到的模型不误判。
        """

        requested = {int(item) for item in tag_ids}
        blocked: list[int] = []
        for row in rows:
            current = {int(item) for item in getattr(row, "tag_ids", ()) or ()}
            if current and current.issubset(requested):
                blocked.append(int(row.model_id))
        return tuple(blocked)

    def _existing_model_rows_for_ids(self, model_ids: tuple[int, ...]) -> tuple[object, ...]:
        selector = self.existing_model_selector
        if selector is None:
            return ()
        by_id = {row.model_id: row for row in selector.manager.rows}
        return tuple(by_id[item] for item in model_ids if item in by_id)

    def _export_existing_futbin_ids(self, model_ids: tuple[int, ...]) -> None:
        """仅把所选后台模型行中明确核实的 FUTBIN ID 导出为 UTF-8 TXT。"""

        rows = self._existing_model_rows_for_ids(tuple(int(item) for item in model_ids))
        if len(rows) != len(model_ids):
            messagebox.showerror("导出 FUTBIN ID", "所选模型明细已不在当前只读列表，未生成文件；请刷新后重新选择。")
            return
        try:
            futbin_ids = selected_futbin_ids(rows)
            content = format_futbin_id_export(rows)
        except ValueError as exc:
            messagebox.showerror("导出 FUTBIN ID", str(exc))
            return
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出选中模型的 FUTBIN ID",
            initialfile="selected_futbin_ids.txt",
            defaultextension=".txt",
            filetypes=[("UTF-8 文本文件", "*.txt")],
        )
        if not target:
            return
        destination = Path(target)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)
        except OSError as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            messagebox.showerror("导出 FUTBIN ID", f"写入文件失败：{exc}")
            return
        messagebox.showinfo(
            "导出 FUTBIN ID",
            f"已导出 {len(futbin_ids)} 个去重后的 FUTBIN ID（所选模型 {len(rows)} 个）。\n"
            f"格式：UTF-8 TXT，每行一个 FUTBIN ID。\n\n{target}",
        )

    def _progress_reporter(self, label: str, total: int):
        """生成传给适配器的进度回调：在工作线程里把进度投递回主线程。

        只在真正跨过「完成数」时才投递，避免高频事件淹没事件队列。
        """

        state = {"done": -1}

        def report(stage: str, done: int, total_count: int) -> None:
            if done == state["done"]:
                return
            state["done"] = done
            self.events.put(("existing_action_progress", (label, stage, int(done), int(total_count or total))))

        return report

    def _attach_existing_progress(self, label: str, total: int) -> None:
        """记录当前动作的进度回调，供写入线程取用。"""

        self._pending_progress = self._progress_reporter(label, total)

    def _existing_model_action(self, action: str, model_ids: tuple[int, ...]) -> None:
        if self.admin_adapter is None:
            messagebox.showinfo("后台模型维护", "请先完成后台登录")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("后台模型维护", "当前已有后台动作，请等待完成，避免并发修改同一模型")
            return
        if not model_ids:
            messagebox.showwarning("后台模型维护", "当前选择范围为空，未发起写入。")
            return
        if action == "unlist":
            frozen_ids = tuple(int(item) for item in model_ids)
            self._begin_busy(f"正在只读预检 {len(frozen_ids)} 个模型的下架范围…", total=len(frozen_ids))
            self._set_existing_action_running(True)
            progress = self._progress_reporter("下架预检", len(frozen_ids))

            def plan_worker() -> None:
                try:
                    plan = self.admin_adapter.plan_unlist(frozen_ids, progress=progress)
                    self.events.put(("existing_unlist_plan_ready", (frozen_ids, plan)))
                except Exception as exc:
                    self.events.put(("existing_unlist_plan_error", f"预检失败；异常类型：{type(exc).__name__}；{redact_text(exc)}"))

            self.worker = threading.Thread(target=plan_worker, name="fc27-existing-unlist-plan", daemon=True)
            self.worker.start()
            return
        if action in {"tags", "tags_remove", "remove_tags"}:
            selector = self.existing_model_selector
            tag_ids = selector.selected_tag_ids() if selector is not None else ()
            if not tag_ids:
                messagebox.showwarning("标签维护", "请在后台模型维护页的标签列表中选择一个或多个标签")
                return
            remove_action = action in {"tags_remove", "remove_tags"}
            if remove_action and not hasattr(self.admin_adapter, "remove_tags"):
                messagebox.showwarning("移除指定标签", "当前后台适配器尚未提供已核验的移除标签接口，已阻断写入。")
                return
            rows = self._existing_model_rows_for_ids(tuple(int(item) for item in model_ids))
            if len(rows) != len(model_ids):
                messagebox.showerror("后台模型维护", "所选模型明细已不在当前只读列表，未写入；请刷新后重新选择。")
                return
            if remove_action:
                # 移除后标签会变空的模型，后台必以「请选择标签」拒绝；这类模型
                # 必须在确认之前就查出来告知用户，而不是写入到一半才失败。
                blocked = self._empty_after_removal_ids(rows, tag_ids)
                if blocked:
                    preview_rows = [row for row in rows if int(row.model_id) in set(blocked)]
                    preview = build_existing_action_preview(preview_rows, action, tag_ids=tuple(tag_ids))
                    detail = (
                        f"以下 {len(blocked)} 个模型只有你勾选的这一个标签，移除后会变成「没有任何标签」，"
                        "而后台不允许空标签（会返回「请选择标签」），因此整批不会写入：\n\n"
                        + ", ".join(str(item) for item in blocked[:20])
                        + ("…" if len(blocked) > 20 else "")
                        + "\n\n处理办法（任选）：\n"
                        "1. 在后台网页编辑页逐个清空这几个模型的标签；\n"
                        "2. 先给它们「添加」另一个标签，再用本工具移除目标标签；\n"
                        "3. 取消勾选这几个模型，只对其余模型执行移除。"
                    )
                    self._show_scrollable_confirmation(
                        "批量移除标签 · 已被阻断（未写入）",
                        "【需要处理的模型】\n\n" + preview + "\n\n\n【说明与处理办法】\n\n" + detail + "\n",
                        informative=True,
                        headline=(
                            f"⚠ 整批未写入任何模型：其中 {len(blocked)} 个模型移除标签后会变成零标签，"
                            "后台不接受空标签。请按正文最后的「处理办法」操作后重新执行。"
                        ),
                    )
                    return
            preview = build_existing_action_preview(rows, action, tag_ids=tuple(tag_ids))
            if not self._show_scrollable_confirmation("确认批量标签", preview):
                return
            method = (
                (lambda progress: self.admin_adapter.remove_tags(model_ids, [int(item) for item in tag_ids], progress=progress))
                if remove_action
                else (lambda progress: self.admin_adapter.add_tags(model_ids, [int(item) for item in tag_ids], progress=progress))
            )
        elif action in {"recommend_enable", "recommend_disable"}:
            enabled = action == "recommend_enable"
            rows = self._existing_model_rows_for_ids(tuple(int(item) for item in model_ids))
            if len(rows) != len(model_ids):
                messagebox.showerror("后台模型维护", "所选模型明细已不在当前只读列表，未写入；请刷新后重新选择。")
                return
            preview = build_existing_action_preview(rows, action)
            if not self._show_scrollable_confirmation("确认推荐设置", preview):
                return
            method = lambda progress: self.admin_adapter.set_recommendation(model_ids, enabled, progress=progress)
        else:
            messagebox.showerror("后台模型维护", f"未知动作：{action}")
            return
        _ACTION_LABELS = {
            "tags": "添加标签",
            "tags_remove": "移除标签",
            "remove_tags": "移除标签",
            "recommend_enable": "开启推荐",
            "recommend_disable": "关闭推荐",
        }
        action_label = _ACTION_LABELS.get(action, action)
        total = len(model_ids)
        self._begin_busy(f"正在{action_label}并回读核验…", total=total)
        self._set_existing_action_running(True)
        progress = self._progress_reporter(action_label, total)

        def worker() -> None:
            try:
                with self._temporary_backend_write():
                    result = method(progress)
                self.events.put(("existing_model_action_done", (action, model_ids, dict(result))))
            except Exception as exc:
                error_payload = _safe_existing_model_action_error(action, model_ids, exc)
                self._persist_existing_model_action_error(error_payload)
                self.events.put(("existing_model_action_error", error_payload))
            finally:
                self._force_backend_read_only()

        self.worker = threading.Thread(target=worker, name="fc27-existing-model-action", daemon=True)
        self.worker.start()

    # ---- 新增球员上架 ----

