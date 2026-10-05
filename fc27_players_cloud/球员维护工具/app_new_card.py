"""PlayerMaintenanceApp 的新增球员上架页。"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import threading
from tkinter import END
from tkinter import messagebox
from tkinter import ttk
from typing import Any
from typing import Mapping
from typing import Optional
from 球员维护工具.admin_adapter import SUPPORTED_CID
from 球员维护工具.admin_adapter import SUPPORTED_GID
from 球员维护工具.admin_adapter import build_existing_model_map
from 球员维护工具.admin_adapter import extract_futbin_id
from 球员维护工具.admin_adapter import extract_model_id
from 球员维护工具.models import ExportFilters
from 球员维护工具.new_card_recovery import BatchRecoveryBlocked
from 球员维护工具.new_card_recovery import NewCardBatch
from 球员维护工具.new_card_recovery import RECOVERABLE_STEPS
from 球员维护工具.new_card_recovery import find_new_card_batches
from 球员维护工具.new_card_recovery import load_new_card_batch
from 球员维护工具.new_card_recovery import resolve_recovery_scope
from 球员维护工具.new_card_recovery import safe_result_summary
from 球员维护工具.new_card_selection import NewCardSelectionBasket
from 球员维护工具.new_card_selection import filter_rows_by_ids
from 球员维护工具.new_card_selection import validate_intent_scope
from 球员维护工具.player_database import PlayerDatabaseClient
from 球员维护工具.selection import collect_filtered_players
from 球员维护工具.storage import JsonlLogger
from 球员维护工具.storage import atomic_write_json
from 球员维护工具.storage import redact_text
from 球员维护工具.transformer import convert_workbook
import sys

if __package__:
    from .app_constants import APP_DIR, STEP_LABELS
    from .app_formatters import format_new_card_batch_summary
    from .app_formatters import is_low_rating_player
    from .app_formatters import new_card_rating_threshold
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_constants import APP_DIR, STEP_LABELS
    from 球员维护工具.app_formatters import format_new_card_batch_summary
    from 球员维护工具.app_formatters import is_low_rating_player
    from 球员维护工具.app_formatters import new_card_rating_threshold

class NewCardMixin:
    def _build_new_card_tab(self, parent: ttk.Frame) -> None:
        """建立新卡批次的可视化选择页。

        Treeview 的三个意图列可直接点击切换；顶部按钮对当前选中的行批量
        设置。这样“上架”“加标签”“开推荐”是三个独立集合，不会因为选中
        一行就隐式执行全部动作。
        """

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        controls = ttk.LabelFrame(parent, text="1. 获取最新球员（数据库只读）")
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(7, weight=1)
        ttk.Label(controls, text="最新天数").grid(row=0, column=0, padx=(8, 3), pady=7)
        days_box = ttk.Combobox(controls, textvariable=self.new_card_days_var, values=("1", "3", "7", "14", "30"), width=7, state="readonly")
        days_box.grid(row=0, column=1, padx=3, pady=7)
        ttk.Label(controls, text="天（按首次入库时间筛选）").grid(row=0, column=2, padx=(2, 12), pady=7)
        ttk.Label(controls, text="搜索").grid(row=0, column=3, padx=(3, 2), pady=7)
        search_entry = ttk.Entry(controls, textvariable=self.new_card_search_var, width=20)
        search_entry.grid(row=0, column=4, padx=3, pady=7)
        search_entry.bind("<KeyRelease>", lambda _event: self._refresh_new_card_tree())
        self.new_card_fetch_button = ttk.Button(controls, text="开始获取最新球员", command=self._fetch_new_cards)
        self.new_card_fetch_button.grid(row=0, column=5, padx=5, pady=7)
        ttk.Button(controls, text="保存选择", command=self._save_new_card_selection).grid(row=0, column=6, padx=3, pady=7)
        ttk.Label(controls, textvariable=self.new_card_summary_var, foreground="#555555").grid(row=0, column=7, sticky="w", padx=8, pady=7)
        # 收录规则：默认隐藏低于阈值的卡；关闭后可见灰显，确认预览仍会警示。
        ttk.Checkbutton(
            controls, text="隐藏低分卡（默认不收录）", variable=self.new_card_min_rating_var, command=self._refresh_new_card_tree
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=(8, 3), pady=(0, 7))
        ttk.Label(controls, text="低于").grid(row=1, column=2, sticky="e", padx=(2, 2), pady=(0, 7))
        threshold_box = ttk.Spinbox(
            controls, from_=40, to=99, textvariable=self.new_card_min_rating_value_var, width=4, command=self._refresh_new_card_tree
        )
        threshold_box.grid(row=1, column=3, sticky="w", pady=(0, 7))
        threshold_box.bind("<KeyRelease>", lambda _event: self._refresh_new_card_tree())
        ttk.Label(controls, text="分（可改阈值；解析不到评分的卡不隐藏，需人工确认）", foreground="#8a5a00").grid(
            row=1, column=4, columnspan=3, sticky="w", pady=(0, 7)
        )

        action_frame = ttk.LabelFrame(parent, text="2. 对选中行设置独立意图")
        action_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        action_top = ttk.Frame(action_frame)
        action_top.pack(fill="x", padx=6)
        ttk.Label(action_top, text="也可以直接点击表格中的 ✓/— 切换单行").pack(side="left", padx=(2, 12), pady=4)
        ttk.Label(action_top, text="标签 ID").pack(side="left", padx=(0, 3), pady=4)
        ttk.Entry(action_top, textvariable=self.tag_ids_var, width=16).pack(side="left", padx=(0, 8), pady=4)
        ttk.Button(action_top, text="加载标签", command=self._load_tags).pack(side="left", padx=(0, 8), pady=4)
        action_select = ttk.Frame(action_frame)
        action_select.pack(fill="x", padx=6)
        self.new_card_action_buttons = []
        for intent, label in (("upload", "上架"), ("tags", "加标签"), ("recommend", "开推荐")):
            button = ttk.Button(action_select, text=f"{label}：勾选当前行", command=lambda intent=intent: self._set_new_card_intent_from_selection(intent, True))
            button.pack(side="left", padx=2, pady=4)
            self.new_card_action_buttons.append(button)
            button = ttk.Button(action_select, text=f"{label}：取消", command=lambda intent=intent: self._set_new_card_intent_from_selection(intent, False))
            button.pack(side="left", padx=(0, 7), pady=4)
            self.new_card_action_buttons.append(button)
        action_bulk = ttk.Frame(action_frame)
        action_bulk.pack(fill="x", padx=6)
        ttk.Label(action_bulk, text="一键批量（只作用于当前可见行：已按搜索与低分筛选过滤）").pack(side="left", padx=(2, 10), pady=4)
        for intent, label in (("upload", "上架"), ("tags", "加标签"), ("recommend", "开推荐")):
            button = ttk.Button(action_bulk, text=f"全选可见行：{label}", command=lambda intent=intent: self._set_new_card_intent_visible(intent, True))
            button.pack(side="left", padx=2, pady=4)
            self.new_card_action_buttons.append(button)
        ttk.Button(action_bulk, text="清除可见行全部意图", command=self._clear_visible_intents).pack(side="left", padx=(8, 2), pady=4)
        action_execute = ttk.Frame(action_frame)
        action_execute.pack(fill="x", padx=6)
        ttk.Button(action_execute, text="生成选中上架文件", command=self._prepare_selected_upload_file).pack(side="right", padx=5, pady=4)
        ttk.Button(action_execute, text="执行完整上架流程", command=self._run_selected_new_card_flow).pack(side="right", padx=5, pady=4)

        recovery_frame = ttk.LabelFrame(parent, text="3. 已导入批次后续（只读加载，可单步恢复）")
        recovery_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        recovery_frame.columnconfigure(1, weight=1)
        ttk.Label(recovery_frame, text="已导入批次").grid(row=0, column=0, sticky="w", padx=(8, 3), pady=5)
        self.new_card_batch_combo = ttk.Combobox(
            recovery_frame,
            textvariable=self.new_card_batch_var,
            state="readonly",
            width=62,
        )
        self.new_card_batch_combo.grid(row=0, column=1, sticky="ew", padx=3, pady=5)
        self.new_card_batch_combo.bind("<<ComboboxSelected>>", lambda _event: self._show_selected_new_card_batch())
        ttk.Button(recovery_frame, text="刷新历史批次", command=self._refresh_new_card_batches).grid(row=0, column=2, padx=3, pady=5)
        ttk.Label(recovery_frame, text="单步").grid(row=1, column=0, sticky="w", padx=(8, 3), pady=5)
        ttk.Combobox(
            recovery_frame,
            textvariable=self.new_card_recovery_step_var,
            values=tuple(STEP_LABELS[step] for step in RECOVERABLE_STEPS),
            state="readonly",
            width=16,
        ).grid(row=1, column=1, sticky="w", padx=3, pady=5)
        self.new_card_recovery_button = ttk.Button(
            recovery_frame,
            text="预览并执行所选单步",
            command=self._run_new_card_recovery_step,
            state="disabled",
        )
        self.new_card_recovery_button.grid(row=1, column=2, padx=3, pady=5)
        ttk.Label(
            recovery_frame,
            textvariable=self.new_card_recovery_summary_var,
            foreground="#555555",
            wraplength=1000,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 5))

        table_frame = ttk.Frame(parent)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("name", "rating", "position", "club", "league", "futbin_id", "existing", "upload", "tags", "recommend")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.new_card_tree = tree
        headings = {
            "name": ("球员", 160), "rating": ("评分", 55), "position": ("位置", 70),
            "club": ("俱乐部", 130), "league": ("联赛", 140), "futbin_id": ("FUTBIN ID", 90),
            "existing": ("后台模型", 85), "upload": ("上架", 55), "tags": ("加标签", 65), "recommend": ("开推荐", 65),
        }
        for column in columns:
            title, width = headings[column]
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="center" if column in {"rating", "futbin_id", "existing", "upload", "tags", "recommend"} else "w")
        tree.tag_configure("existing", foreground="#735c00")
        tree.tag_configure("new", foreground="#1b5e20")
        tree.tag_configure("low_rating", foreground="#9e9e9e")
        tree.tag_configure("stripe", background="#f3f6fa")
        tree.bind("<Button-1>", self._on_new_card_tree_click)
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        ttk.Label(parent, text="说明：标签和推荐只会作用于导入成功后返回的对应模型；已有模型选择请到“后台模型维护”页处理。金币价同步仅作用于本次导入并回读成功的模型。", foreground="#8a5a00", wraplength=1000).grid(row=4, column=0, sticky="w", pady=(6, 0))
        self._refresh_new_card_tree()
        self._refresh_new_card_batches()

    def _fetch_new_cards(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "当前已有后台或文件动作，请等待完成")
            return
        try:
            days = int(self.new_card_days_var.get().strip())
        except (TypeError, ValueError):
            messagebox.showerror("获取最新球员", "最新天数必须是整数")
            return
        if days < 1 or days > 90:
            messagebox.showerror("获取最新球员", "最新天数必须在 1 到 90 之间")
            return
        search = self.new_card_search_var.get().strip()
        self._set_new_card_fetch_running(True)
        self.new_card_summary_var.set(f"正在读取最近 {days} 天新增球员…")

        def worker() -> None:
            try:
                criteria: dict[str, Any] = {"days_new": str(days)}
                if search:
                    criteria["q"] = search
                if __package__:
                    from .selection import collect_filtered_players
                else:
                    from 球员维护工具.selection import collect_filtered_players
                total, items = collect_filtered_players(
                    PlayerDatabaseClient(), ExportFilters(criteria), per_page=200, max_candidates=5000
                )
                existing_map: dict[str, int] = {}
                if self.admin_adapter is not None:
                    # 后台映射是只读核对；失败时不替换旧选择快照，避免把未知行
                    # 静默当作新卡。
                    existing_map = build_existing_model_map(self.admin_adapter.list_all_models())
                self.events.put(("new_cards_ready", (days, search, [dict(item) for item in items], existing_map, total)))
            except Exception as exc:
                self.events.put(("new_cards_error", f"获取失败；异常类型：{type(exc).__name__}；详情：{redact_text(exc)}"))

        self.worker = threading.Thread(target=worker, name="fc27-new-card-fetch", daemon=True)
        self.worker.start()

    def _set_new_card_fetch_running(self, running: bool) -> None:
        if self.new_card_fetch_button is not None:
            self.new_card_fetch_button.configure(state="disabled" if running else "normal")

    def _refresh_new_card_tree(self) -> None:
        tree = self.new_card_tree
        if tree is None:
            return
        for item in tree.get_children(""):
            tree.delete(item)
        query = self.new_card_search_var.get().strip()
        rows = self.new_card_basket.rows_for(query)
        hide_low = bool(self.new_card_min_rating_var.get())
        threshold = new_card_rating_threshold(self.new_card_min_rating_value_var.get())
        visible_rows = []
        low_count = 0
        hidden_count = 0
        for row in rows:
            player = row.player
            is_low = is_low_rating_player(player, threshold)
            if is_low:
                low_count += 1
            if hide_low and is_low:
                hidden_count += 1
                continue
            visible_rows.append((row, is_low))
        self.new_card_display_ids = [row.futbin_id for row, _low in visible_rows]
        for index, (row, is_low) in enumerate(visible_rows):
            player = row.player
            existing = str(row.existing_model_id) if row.existing_model_id is not None else "未读取"
            tags = ["existing" if row.existing_model_id is not None else "new"]
            if is_low:
                tags.append("low_rating")
            if index % 2 == 1:
                tags.append("stripe")
            tree.insert("", END, iid=row.futbin_id, values=(
                player.get("name") or player.get("common_name") or "",
                player.get("rating", ""), player.get("position", ""), player.get("club_name", ""),
                player.get("league_name", ""), row.futbin_id, existing,
                "✓" if row.upload else "—", "✓" if row.tags else "—", "✓" if row.recommend else "—",
            ), tags=tuple(tags))
        summary = (
            f"当前显示 {len(visible_rows)} 条；上架 {len(self.new_card_basket.selected_ids('upload'))} 条；"
            f"标签 {len(self.new_card_basket.selected_ids('tags'))} 条；推荐 {len(self.new_card_basket.selected_ids('recommend'))} 条；"
            f"低分(<{threshold}) {low_count} 条"
        )
        if hidden_count:
            summary += f"（已隐藏 {hidden_count} 条，可关闭筛选取消勾选）"
        self.new_card_summary_var.set(summary)

    def _on_new_card_tree_click(self, event: Any) -> str | None:
        tree = self.new_card_tree
        if tree is None:
            return None
        row_id = tree.identify_row(event.y)
        column = tree.identify_column(event.x)
        intent_by_column = {"#8": "upload", "#9": "tags", "#10": "recommend"}
        intent = intent_by_column.get(column)
        if not row_id or intent is None or row_id not in self.new_card_basket.rows:
            return None
        row = self.new_card_basket.rows[row_id]
        self.new_card_basket.set_intent([row_id], intent, not bool(getattr(row, intent)))
        self._refresh_new_card_tree()
        return "break"

    def _set_new_card_intent_from_selection(self, intent: str, enabled: bool) -> None:
        tree = self.new_card_tree
        ids = tree.selection() if tree is not None else ()
        if not ids:
            messagebox.showinfo("选择球员", "请先在表格中选择一行或多行球员")
            return
        self.new_card_basket.set_intent(ids, intent, enabled)
        self._refresh_new_card_tree()
        self._save_new_card_selection(silent=True)

    def _visible_new_card_ids(self) -> tuple[str, ...]:
        """当前可见行 ID：已应用搜索与低分筛选；批量操作绝不触碰被隐藏的行。"""

        return tuple(self.new_card_display_ids or ())

    def _set_new_card_intent_visible(self, intent: str, enabled: bool) -> None:
        ids = self._visible_new_card_ids()
        if not ids:
            messagebox.showinfo("一键批量选择", "当前没有可见行；请先获取最新球员，或放宽搜索/低分筛选")
            return
        self.new_card_basket.set_intent(ids, intent, enabled)
        self._refresh_new_card_tree()
        self._save_new_card_selection(silent=True)
        self.status_var.set(f"已{'勾选' if enabled else '取消'} {len(ids)} 条可见行的{ {'upload': '上架', 'tags': '加标签', 'recommend': '开推荐'}[intent] }意图")

    def _clear_visible_intents(self) -> None:
        ids = self._visible_new_card_ids()
        if not ids:
            messagebox.showinfo("一键批量选择", "当前没有可见行；请先获取最新球员，或放宽搜索/低分筛选")
            return
        for intent in ("upload", "tags", "recommend"):
            self.new_card_basket.set_intent(ids, intent, False)
        self._refresh_new_card_tree()
        self._save_new_card_selection(silent=True)
        self.status_var.set(f"已清除 {len(ids)} 条可见行的上架/标签/推荐意图")

    def _save_new_card_selection(self, silent: bool = False) -> None:
        try:
            payload = self.new_card_basket.to_dict()
            payload.update({"days_new": self.new_card_days_var.get().strip(), "search": self.new_card_search_var.get().strip()})
            atomic_write_json(self.new_card_selection_path, payload)
            path = self.new_card_selection_path
            if not silent:
                self.status_var.set(f"新卡选择已保存：{path}")
        except (OSError, ValueError, TypeError) as exc:
            if not silent:
                messagebox.showerror("保存新卡选择", str(exc))

    def _load_saved_new_card_selection(self) -> None:
        """恢复本地选择快照用于展示；不会把它当作当前后台批次。"""

        try:
            if not self.new_card_selection_path.is_file():
                return
            payload = json.loads(self.new_card_selection_path.read_text(encoding="utf-8"))
            self.new_card_basket = NewCardSelectionBasket.from_dict(payload)
            if isinstance(payload, Mapping):
                saved_days = str(payload.get("days_new") or "").strip()
                if saved_days:
                    self.new_card_days_var.set(saved_days)
                self.new_card_search_var.set(str(payload.get("search") or "").strip())
            self._refresh_new_card_tree()
            if self.new_card_basket.rows:
                self.new_card_summary_var.set(f"已恢复本地选择快照 {len(self.new_card_basket.rows)} 条；请重新获取最新球员确认批次")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # 快照损坏只忽略，不覆盖，也不把旧手动模型 ID带入新卡范围。
            self.new_card_basket = NewCardSelectionBasket()

    def _low_rating_warning(self, upload_ids: Any, tag_ids: Any, recommend_ids: Any) -> str:
        """确认预览的低分警示：默认规则不收录 85 分以下卡，出现时要求额外评估。

        界面变量缺失时（如测试用 __new__ 绕过初始化）不猜阈值，返回空提示。
        """
        value_var = getattr(self, "new_card_min_rating_value_var", None)
        threshold = new_card_rating_threshold(value_var.get() if value_var is not None else None)
        basket = getattr(self, "new_card_basket", None)
        rows = getattr(basket, "rows", None) if basket is not None else None
        if not isinstance(rows, Mapping):
            return ""

        def low_of(ids: Any) -> list[str]:
            found: list[str] = []
            for item in ids:
                futbin_id = str(item)
                row = rows.get(futbin_id)
                if row is not None and is_low_rating_player(row.player, threshold) and futbin_id not in found:
                    found.append(futbin_id)
            return found

        low_upload = low_of(upload_ids)
        low_tag = low_of(tag_ids)
        low_recommend = low_of(recommend_ids)
        if not (low_upload or low_tag or low_recommend):
            return ""
        parts: list[str] = []
        if low_upload:
            parts.append(f"上架 {', '.join(low_upload)}")
        if low_tag:
            parts.append(f"标签 {', '.join(low_tag)}")
        if low_recommend:
            parts.append(f"推荐 {', '.join(low_recommend)}")
        return (
            f"⚠ 低分卡警示：本次范围含低于 {threshold} 分的卡——{'；'.join(parts)}。"
            "当前收录规则为暂不收录 85 分以下卡；继续执行即视为这些低分卡已通过额外评估。\n"
        )

    def _prepare_selected_upload_file(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "当前已有后台或文件动作，请等待完成")
            return
        if not self.new_card_backend_map_checked:
            messagebox.showwarning("生成上架文件", "尚未完成后台已有模型只读核对；请先登录后台后重新获取最新球员。未知模型不能直接当作新卡上架。")
            return
        upload_ids = self.new_card_basket.selected_ids("upload", include_existing=False)
        if not upload_ids:
            messagebox.showwarning("生成上架文件", "请至少勾选一名未识别为已有模型的球员上架")
            return
        try:
            days = int(self.new_card_days_var.get().strip())
        except (TypeError, ValueError):
            messagebox.showerror("生成上架文件", "最新天数必须是整数")
            return
        self._set_new_card_fetch_running(True)
        self.new_card_summary_var.set(f"正在生成仅含 {len(upload_ids)} 条的上架文件…")

        def worker() -> None:
            try:
                _run_id, output_root = self.store.create_run_dir("runs/new_card_prepare")
                source = output_root / "latest_export.xlsx"
                PlayerDatabaseClient().export_players(ExportFilters({"days_new": str(days)}), source, overwrite=False)
                if __package__:
                    from .transformer import convert_workbook
                else:
                    from 球员维护工具.transformer import convert_workbook
                transformed = output_root / "transformed.xlsx"
                result = convert_workbook(source, transformed)
                selected = output_root / "selected_upload.xlsx"
                filter_rows_by_ids(result.output_path or transformed, selected, upload_ids)
                self.events.put(("new_upload_ready", str(selected)))
            except Exception as exc:
                self.events.put(("new_upload_error", f"生成失败；异常类型：{type(exc).__name__}"))

        self.worker = threading.Thread(target=worker, name="fc27-selected-upload", daemon=True)
        self.worker.start()

    def _run_selected_new_card_flow(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "当前已有后台或文件动作，请等待完成")
            return
        if self.admin_adapter is None:
            messagebox.showinfo("新卡上架", "请先完成后台登录。工具不会读取浏览器凭据。")
            return
        if not self.new_card_backend_map_checked:
            messagebox.showwarning("新卡上架", "本批次尚未完成后台已有模型只读核对；请登录后台后重新获取最新球员，再执行写入。")
            return
        upload_ids = self.new_card_basket.selected_ids("upload", include_existing=False)
        try:
            days = int(self.new_card_days_var.get().strip())
        except (TypeError, ValueError):
            messagebox.showerror("新卡上架", "最新天数必须是整数")
            return
        self.runner.reset_stop()
        tag_ids = self._read_lines_value(self.tag_ids_var.get())
        tag_new_ids = self.new_card_basket.selected_new_ids("tags")
        recommend_new_ids = self.new_card_basket.selected_new_ids("recommend")
        existing_tag_pairs = self.new_card_basket.selected_existing_model_pairs("tags")
        existing_recommend_pairs = self.new_card_basket.selected_existing_model_pairs("recommend")
        existing_model_map: dict[str, int] = {}
        for futbin_id, model_id in (*existing_tag_pairs, *existing_recommend_pairs):
            prior = existing_model_map.get(futbin_id)
            if prior is not None and prior != model_id:
                messagebox.showerror("新卡已有模型范围", f"FUTBIN {futbin_id} 的冻结模型 ID 不一致：{prior} / {model_id}")
                return
            if prior is None and model_id in existing_model_map.values():
                messagebox.showerror("新卡已有模型范围", f"模型 ID {model_id} 对应多个 FUTBIN ID，已阻断")
                return
            existing_model_map[futbin_id] = model_id
        existing_tag_ids = tuple(model_id for _futbin_id, model_id in existing_tag_pairs)
        existing_recommend_ids = tuple(model_id for _futbin_id, model_id in existing_recommend_pairs)
        try:
            upload_ids, tag_new_ids, recommend_new_ids = validate_intent_scope(upload_ids, tag_new_ids, recommend_new_ids)
        except ValueError as exc:
            messagebox.showerror("新卡选择范围", str(exc))
            return
        selected_tag_futbin_ids = tuple(dict.fromkeys((*tag_new_ids, *(item[0] for item in existing_tag_pairs))))
        selected_recommend_futbin_ids = tuple(dict.fromkeys((*recommend_new_ids, *(item[0] for item in existing_recommend_pairs))))
        if not upload_ids and not selected_tag_futbin_ids and not selected_recommend_futbin_ids:
            messagebox.showwarning("新卡上架", "请至少勾选一项上架、加标签或开推荐")
            return
        if selected_tag_futbin_ids and not tag_ids:
            messagebox.showwarning("新卡标签", "已勾选加标签球员，但没有选择标签 ID；请在本页输入标签 ID或点击“加载标签”后再执行。")
            return
        self._set_new_card_fetch_running(True)
        self.status_var.set("正在准备选中上架文件…")

        def worker() -> None:
            try:
                _run_id, output_root = self.store.create_run_dir("runs/new_card_flow")
                source = output_root / "selected_upload.xlsx"
                plan = None
                if upload_ids:
                    export_source = output_root / "latest_export.xlsx"
                    PlayerDatabaseClient().export_players(ExportFilters({"days_new": str(days)}), export_source, overwrite=False)
                    if __package__:
                        from .transformer import convert_workbook
                    else:
                        from 球员维护工具.transformer import convert_workbook
                    transformed = output_root / "transformed.xlsx"
                    result = convert_workbook(export_source, transformed)
                    filter_rows_by_ids(result.output_path or transformed, source, upload_ids)
                    plan = self.admin_adapter.plan_import(source)
                journal_path = output_root / "new_card_journal.json"
                self.events.put(("new_card_plan_ready", (str(source), plan, tuple(upload_ids), tuple(tag_new_ids), tuple(recommend_new_ids), tuple(tag_ids), tuple(existing_tag_pairs), tuple(existing_recommend_pairs), str(journal_path), dict(existing_model_map))))
            except Exception as exc:
                self.events.put(("new_card_flow_error", f"准备失败；异常类型：{type(exc).__name__}；详情：{redact_text(exc)}"))

        self.worker = threading.Thread(target=worker, name="fc27-new-card-flow-preflight", daemon=True)
        self.worker.start()

    def _confirm_new_card_plan_and_run(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) not in {8, 9, 10} or self.admin_adapter is None:
            self._set_new_card_fetch_running(False)
            return
        source, plan, upload_ids, tag_ids_for_new, recommend_ids_for_new, tag_ids, existing_tag_pairs, existing_recommend_pairs = payload[:8]
        journal_path = Path(str(payload[8])) if len(payload) >= 9 else Path(str(source)).with_name("new_card_journal.json")
        existing_model_map_raw = payload[9] if len(payload) == 10 else {}
        try:
            upload_ids = tuple(str(item) for item in upload_ids)
            upload_plan_ids = tuple(str(item) for item in getattr(plan, "upload_futbin_ids", ())) if plan is not None else ()
            if upload_plan_ids != upload_ids:
                raise ValueError("后台导入前的新增 ID 计划与选择集合不一致，已阻断")
            upload_ids, tag_ids_for_new, recommend_ids_for_new = validate_intent_scope(upload_ids, tag_ids_for_new, recommend_ids_for_new)
            existing_model_map = {str(key).strip(): int(value) for key, value in dict(existing_model_map_raw or {}).items()}
            if any(not key or value < 1 for key, value in existing_model_map.items()):
                raise ValueError("已有卡冻结映射含空 FUTBIN ID 或无效模型 ID，已阻断")
            if len(existing_model_map) != len(set(existing_model_map.values())):
                raise ValueError("已有卡冻结映射含重复模型 ID，已阻断")
            existing_tag_pairs = tuple((str(futbin_id), int(model_id)) for futbin_id, model_id in existing_tag_pairs)
            existing_recommend_pairs = tuple((str(futbin_id), int(model_id)) for futbin_id, model_id in existing_recommend_pairs)
            expected_existing_map = {futbin_id: model_id for futbin_id, model_id in (*existing_tag_pairs, *existing_recommend_pairs)}
            if expected_existing_map != existing_model_map:
                raise ValueError("已有卡冻结映射与标签/推荐动作范围不一致，已阻断")
            existing_tag_ids = tuple(model_id for _futbin_id, model_id in existing_tag_pairs)
            existing_recommend_ids = tuple(model_id for _futbin_id, model_id in existing_recommend_pairs)
            if not existing_model_map and (existing_tag_ids or existing_recommend_ids):
                raise ValueError("已有卡动作缺少冻结 FUTBIN→模型 ID 映射，已阻断")
            text = "本次新卡批次完整动作预览\n"
            text += f"上架并导入：{len(upload_plan_ids)} 条；FUTBIN ID：{', '.join(upload_plan_ids) if upload_plan_ids else '无'}\n"
            text += f"加标签：新卡 FUTBIN ID {', '.join(tag_ids_for_new) if tag_ids_for_new else '无'}；已有模型 ID {', '.join(str(item) for item in existing_tag_ids) if existing_tag_ids else '无'}；标签 ID {', '.join(str(item) for item in tag_ids) if tag_ids else '无'}\n"
            text += f"开启推荐：新卡 FUTBIN ID {', '.join(recommend_ids_for_new) if recommend_ids_for_new else '无'}；已有模型 ID {', '.join(str(item) for item in existing_recommend_ids) if existing_recommend_ids else '无'}\n"
            text += f"同步金币价：{len(upload_plan_ids)} 条（导入后只用回读模型 ID；FUTBIN ID：{', '.join(upload_plan_ids) if upload_plan_ids else '无'}）\n"
            low_warning = self._low_rating_warning(upload_plan_ids, (*tag_ids_for_new, *(item[0] for item in existing_tag_pairs)), (*recommend_ids_for_new, *(item[0] for item in existing_recommend_pairs)))
            if low_warning:
                text += low_warning
            text += "已有卡写入前只读核验 gid=1327、cid=9627、FUTBIN ID 和模型 ID。\n确认后按以上冻结范围执行；取消不会写入。"
            if not self._show_scrollable_confirmation("确认新卡批次操作", text):
                self._set_new_card_fetch_running(False)
                self.status_var.set("已取消新卡批次写入")
                return
        except Exception as exc:
            self._set_new_card_fetch_running(False)
            messagebox.showerror("新卡导入计划", str(exc))
            return
        try:
            frozen_tag_ids: tuple[int, ...] = tuple(int(item) for item in tag_ids)
            if any(item < 1 for item in frozen_tag_ids) or len(set(frozen_tag_ids)) != len(frozen_tag_ids):
                raise ValueError
        except (TypeError, ValueError) as exc:
            self._set_new_card_fetch_running(False)
            messagebox.showerror("新卡标签范围", "标签 ID 必须是大于 0 的整数；未发起导入")
            return

        def worker() -> None:
            logger = JsonlLogger(journal_path.with_name("run.log.jsonl"))
            write_access = None
            write_access_entered = False
            journal: dict[str, Any] = {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "finished_at": "",
                "source_path": str(source) if upload_ids else "",
                "expected_upload_futbin_ids": list(upload_ids),
                "selected_tag_futbin_ids": list(dict.fromkeys((*tag_ids_for_new, *(item[0] for item in existing_tag_pairs)))),
                "selected_recommend_futbin_ids": list(dict.fromkeys((*recommend_ids_for_new, *(item[0] for item in existing_recommend_pairs)))),
                # 后续单步恢复只能使用本次冻结的动作参数，绝不回读旧配置补范围。
                "selected_tag_ids": list(frozen_tag_ids),
                "recommend_enabled": True,
                "existing_model_map": dict(existing_model_map),
                "steps": {"import": "pending", "tags": "pending", "recommend": "pending", "sync": "pending"},
            }

            def save_journal(**updates: Any) -> None:
                journal.update(updates)
                if journal.get("status") in {"success", "partial_or_unknown", "failed"} and not journal.get("finished_at"):
                    journal["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                atomic_write_json(journal_path, journal)
                atomic_write_json(
                    journal_path.parent / "run.json",
                    {
                        "run_id": journal_path.parent.name,
                        "run_dir": str(journal_path.parent),
                        "started_at": journal.get("started_at", ""),
                        "finished_at": journal.get("finished_at", ""),
                        "status": journal.get("status", "unknown"),
                        "steps": [
                            {"step": name, "status": str(status), "message": "新卡流程阶段"}
                            for name, status in dict(journal.get("steps") or {}).items()
                        ],
                    },
                )
                logger.write(
                    "INFO",
                    "new_card_stage",
                    "新卡流程阶段记录",
                    status=journal.get("status"),
                    steps=journal.get("steps"),
                )

            def mark_pending_after_failure(step_names: tuple[str, ...]) -> None:
                for step_name in step_names:
                    if journal["steps"].get(step_name) == "pending":
                        journal["steps"][step_name] = "skipped_after_failure"
            try:
                write_access = self._temporary_backend_write()
                write_access.__enter__()
                write_access_entered = True
                save_journal()
                if existing_model_map:
                    frozen_existing_pairs = tuple(existing_model_map.items())
                    self._verify_new_card_recovery_models(
                        tuple(item[0] for item in frozen_existing_pairs),
                        tuple(int(item[1]) for item in frozen_existing_pairs),
                    )
                if self.runner.stop_event.is_set():
                    raise RuntimeError("已请求停止，未发起后台导入")
                model_map: dict[str, int] = {}
                imported_model_ids: list[int] = []
                actions: dict[str, Any] = {}
                if upload_ids:
                    journal["steps"]["import"] = "running"
                    save_journal()
                    outcome = self.admin_adapter.import_players(Path(str(source)))
                    data = outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)
                    model_map = {str(key): int(value) for key, value in dict(data.get("futbin_model_map") or {}).items()}
                    if set(model_map) != set(upload_ids):
                        raise RuntimeError("导入回读映射与本次上架选择不一致，后续动作已停止")
                    imported_model_ids = [model_map[item] for item in upload_ids]
                    journal["steps"]["import"] = "success"
                    save_journal(job_id=data.get("job_id"), futbin_model_map=model_map, imported_model_ids=imported_model_ids)
                    actions["import"] = data
                else:
                    journal["steps"]["import"] = "skipped"
                    save_journal(futbin_model_map={}, imported_model_ids=[])
                    actions["import"] = {"status": "skipped", "reason": "本批仅处理已有模型动作"}

                def action_ids(new_futbin_ids: tuple[str, ...], existing_pairs: tuple[tuple[str, int], ...]) -> list[int]:
                    values: list[int] = []
                    for futbin_id in new_futbin_ids:
                        if futbin_id not in model_map:
                            raise RuntimeError(f"FUTBIN {futbin_id} 缺少本次导入回读模型 ID")
                        model_id = int(model_map[futbin_id])
                        if model_id not in values:
                            values.append(model_id)
                    for _futbin_id, model_id in existing_pairs:
                        model_id = int(model_id)
                        if model_id not in values:
                            values.append(model_id)
                    return values

                new_tag_ids = action_ids(tuple(tag_ids_for_new), tuple(existing_tag_pairs))
                new_recommend_ids = action_ids(tuple(recommend_ids_for_new), tuple(existing_recommend_pairs))
                if new_tag_ids and tag_ids:
                    if existing_tag_pairs:
                        self._verify_new_card_recovery_models(
                            tuple(item[0] for item in existing_tag_pairs),
                            tuple(int(item[1]) for item in existing_tag_pairs),
                        )
                    if self.runner.stop_event.is_set():
                        raise RuntimeError("已请求停止，未发起标签写入")
                    journal["steps"]["tags"] = "running"
                    save_journal()
                    result = self.admin_adapter.add_tags(new_tag_ids, [int(item) for item in tag_ids])
                    actions["tags"] = dict(result)
                    actions["tag_model_ids"] = list(new_tag_ids)
                    journal["steps"]["tags"] = "success"
                    save_journal()
                else:
                    journal["steps"]["tags"] = "skipped"
                    save_journal()
                if new_recommend_ids:
                    if existing_recommend_pairs:
                        self._verify_new_card_recovery_models(
                            tuple(item[0] for item in existing_recommend_pairs),
                            tuple(int(item[1]) for item in existing_recommend_pairs),
                        )
                    if self.runner.stop_event.is_set():
                        raise RuntimeError("已请求停止，未发起推荐写入")
                    journal["steps"]["recommend"] = "running"
                    save_journal()
                    result = self.admin_adapter.set_recommendation(new_recommend_ids, True)
                    actions["recommend"] = dict(result)
                    actions["recommend_model_ids"] = list(new_recommend_ids)
                    journal["steps"]["recommend"] = "success"
                    save_journal()
                else:
                    journal["steps"]["recommend"] = "skipped"
                    save_journal()
                if imported_model_ids:
                    if self.runner.stop_event.is_set():
                        raise RuntimeError("已请求停止，未发起金币价同步")
                    journal["steps"]["sync"] = "running"
                    save_journal()
                    result = self.admin_adapter.sync_prices(imported_model_ids)
                    actions["sync"] = dict(result)
                    journal["steps"]["sync"] = "success"
                    save_journal(status="success")
                else:
                    journal["steps"]["sync"] = "skipped"
                    actions["sync"] = {"status": "skipped", "reason": "本批没有新导入模型"}
                    save_journal(status="success")
                actions.update({
                    "model_ids": imported_model_ids,
                    "futbin_model_map": dict(model_map),
                    "existing_model_map": dict(existing_model_map),
                    "tag_model_ids": list(new_tag_ids),
                    "recommend_model_ids": list(new_recommend_ids),
                })
                self._append_new_card_history(journal_path, journal)
                self.events.put(("new_card_flow_finished", actions))
            except Exception as exc:
                for step_name, step_status in journal["steps"].items():
                    if step_status == "running":
                        journal["steps"][step_name] = "failed"
                mark_pending_after_failure(("import", "tags", "recommend", "sync"))
                detail = redact_text(exc)
                error_payload: dict[str, Any] = {"error_type": type(exc).__name__, "error_message": detail}
                # AdminHttpError 的 status/url/diagnostic 是脱敏结构诊断，可安全入档。
                status = getattr(exc, "status", None)
                if status is not None:
                    error_payload["http_status"] = status
                diagnostic = getattr(exc, "diagnostic", None)
                if isinstance(diagnostic, Mapping) and diagnostic:
                    error_payload["diagnostic"] = dict(diagnostic)
                save_journal(status="partial_or_unknown", **error_payload)
                self._append_new_card_history(journal_path, journal)
                self.events.put((
                    "new_card_flow_error",
                    f"执行失败；异常类型：{type(exc).__name__}；详情：{detail}；已保存阶段记录：{journal_path}",
                ))
            finally:
                try:
                    if write_access is not None and write_access_entered:
                        write_access.__exit__(None, None, None)
                finally:
                    self._force_backend_read_only()

        self.status_var.set("正在执行新卡批次，并按已核验映射处理各项动作…")
        self.worker = threading.Thread(target=worker, name="fc27-new-card-flow", daemon=True)
        self.worker.start()

    # ---- 新卡批次后续单步恢复 ----

    def _refresh_new_card_batches(self) -> None:
        """只读加载已完成导入回读的历史批次，不读取配置或手动模型 ID。"""

        try:
            batches = find_new_card_batches(APP_DIR)
        except Exception as exc:
            self.new_card_batches = ()
            self.new_card_batch_by_display = {}
            if self.new_card_batch_combo is not None:
                self.new_card_batch_combo.configure(values=())
            self.new_card_batch_var.set("")
            self.new_card_recovery_summary_var.set(f"历史批次读取失败：{type(exc).__name__}；已保持只读")
            if self.new_card_recovery_button is not None:
                self.new_card_recovery_button.configure(state="disabled")
            return
        self.new_card_batches = batches
        self.new_card_batch_by_display = {batch.display_name: batch for batch in batches}
        values = tuple(self.new_card_batch_by_display)
        if self.new_card_batch_combo is not None:
            self.new_card_batch_combo.configure(values=values)
        current = self.new_card_batch_var.get()
        if current not in self.new_card_batch_by_display:
            self.new_card_batch_var.set(values[0] if values else "")
        self._show_selected_new_card_batch()

    def _selected_new_card_batch(self) -> Optional[NewCardBatch]:
        selected = self.new_card_batch_by_display.get(self.new_card_batch_var.get().strip())
        if selected is not None:
            return selected
        return None

    def _show_selected_new_card_batch(self) -> None:
        batch = self._selected_new_card_batch()
        if batch is None:
            self.new_card_recovery_summary_var.set("没有可恢复的新卡批次；请刷新历史批次")
            if self.new_card_recovery_button is not None:
                self.new_card_recovery_button.configure(state="disabled")
            return
        self.new_card_recovery_summary_var.set(format_new_card_batch_summary(batch))
        if self.new_card_recovery_button is not None:
            self.new_card_recovery_button.configure(state="normal")

    def _recovery_step_key(self) -> str:
        label = self.new_card_recovery_step_var.get().strip()
        return next((step for step in RECOVERABLE_STEPS if STEP_LABELS.get(step) == label), label)

    def _verify_new_card_recovery_models(
        self,
        futbin_ids: tuple[str, ...],
        model_ids: tuple[int, ...],
    ) -> None:
        """写前重新读取每个模型，确认 ID、范围和 FUTBIN 映射仍未漂移。"""

        if self.admin_adapter is None:
            raise BatchRecoveryBlocked("后台会话不存在，未写入")
        if len(futbin_ids) != len(model_ids):
            raise BatchRecoveryBlocked("冻结 FUTBIN 与模型 ID 数量不一致，未写入")
        for futbin_id, model_id in zip(futbin_ids, model_ids):
            row = self.admin_adapter.client.get_model(int(model_id))
            if not isinstance(row, Mapping):
                raise BatchRecoveryBlocked(f"模型 {model_id} 回读结构无效，未写入")
            if extract_model_id(row) != int(model_id):
                raise BatchRecoveryBlocked(f"模型 {model_id} 回读 ID 不一致，未写入")
            gid = next((row[key] for key in ("gid", "game_id", "gameId") if key in row and row[key] is not None), None)
            cid = next((row[key] for key in ("cid", "category_id", "categoryId") if key in row and row[key] is not None), None)
            if str(gid) != str(SUPPORTED_GID) or str(cid) != str(SUPPORTED_CID):
                raise BatchRecoveryBlocked(f"模型 {model_id} 不属于 FC27/Players 范围，未写入")
            actual_futbin = extract_futbin_id(row)
            if str(actual_futbin or "").strip() != str(futbin_id):
                raise BatchRecoveryBlocked(
                    f"模型 {model_id} 当前 FUTBIN ID 与冻结值不一致（{actual_futbin or '缺失'} != {futbin_id}），未写入"
                )

    @staticmethod
    def _recovery_preview(batch: NewCardBatch, step: str, futbin_ids: tuple[str, ...], model_ids: tuple[int, ...]) -> str:
        action = {"tags": "追加冻结标签", "recommend": "设置推荐", "sync": "同步金币价"}[step]
        lines = [
            f"历史批次：{batch.run_id}",
            f"动作：{action}",
            f"FUTBIN ID（冻结选择与已核验映射交集）：{', '.join(futbin_ids)}",
            f"后台模型 ID（本次实际写入范围）：{', '.join(str(item) for item in model_ids)}",
        ]
        if step == "tags":
            lines.append(f"标签 ID（批次创建时冻结）：{', '.join(str(item) for item in batch.selected_tag_ids)}")
        elif step == "recommend":
            lines.append(f"推荐动作（批次创建时冻结）：{'开启' if batch.recommend_enabled else '关闭'}")
        lines.extend(
            [
                "导入步骤不会重传；旧配置、手动模型 ID和空范围不会被使用。",
                "确认后由 AdminAdapter 逐模型写入并回读；回读失败将标为未知并阻断重试。",
                "确认后才执行；取消不会写入。",
            ]
        )
        return "\n".join(lines)

    def _run_new_card_recovery_step(self) -> None:
        if self.admin_adapter is None:
            messagebox.showinfo("新卡批次恢复", "请先完成后台登录；历史批次读取本身不需要登录。")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "当前已有后台动作，请等待完成")
            return
        batch = self._selected_new_card_batch()
        if batch is None:
            messagebox.showwarning("新卡批次恢复", "请先刷新并选择一个可恢复的新卡批次")
            return
        step = self._recovery_step_key()
        try:
            futbin_ids, model_ids = resolve_recovery_scope(batch, step)
            preview = self._recovery_preview(batch, step, futbin_ids, model_ids)
        except BatchRecoveryBlocked as exc:
            messagebox.showwarning("新卡批次恢复已阻断", str(exc))
            self.new_card_recovery_summary_var.set(f"只读阻断：{exc}")
            return
        if not self._show_scrollable_confirmation("确认新卡批次单步写入", preview):
            return
        self.runner.reset_stop()
        self._set_new_card_recovery_running(True)
        self.status_var.set(f"正在恢复批次 {batch.run_id} 的 {STEP_LABELS.get(step, step)}，写后回读中…")

        def worker() -> None:
            journal_path = batch.journal_path
            logger = JsonlLogger(journal_path.with_name("run.log.jsonl"))
            step_started = False
            write_access = None
            write_access_entered = False
            try:
                write_access = self._temporary_backend_write()
                write_access.__enter__()
                write_access_entered = True
                # UI 预览之后重新从磁盘读取，避免窗口滞留期间使用过期范围。
                current_batch = load_new_card_batch(journal_path)
                frozen_futbin_ids, frozen_model_ids = resolve_recovery_scope(current_batch, step)
                journal_raw = json.loads(journal_path.read_text(encoding="utf-8"))
                if not isinstance(journal_raw, dict):
                    raise BatchRecoveryBlocked("批次 journal 根节点不是对象，未写入")
                step_status = str((journal_raw.get("steps") or {}).get(step) or "unknown")
                if step_status not in {"pending", "skipped_after_failure"}:
                    raise BatchRecoveryBlocked(f"批次在确认后已变更为 {step_status}，未写入")
                self._verify_new_card_recovery_models(frozen_futbin_ids, frozen_model_ids)
                journal = journal_raw
                journal["finished_at"] = ""
                journal.setdefault("steps", {})[step] = "running"
                journal.setdefault("recovery_actions", {})[step] = {
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "futbin_ids": list(frozen_futbin_ids),
                    "model_ids": list(frozen_model_ids),
                }
                self._persist_new_card_journal(journal_path, journal, logger)
                step_started = True
                if step == "tags":
                    result = self.admin_adapter.add_tags(frozen_model_ids, current_batch.selected_tag_ids)
                elif step == "recommend":
                    result = self.admin_adapter.set_recommendation(frozen_model_ids, bool(current_batch.recommend_enabled))
                else:
                    result = self.admin_adapter.sync_prices(frozen_model_ids)
                result_data = dict(result) if isinstance(result, Mapping) else {}
                if result_data.get("verified") is not True:
                    raise RuntimeError("后台动作未返回 verified=true，状态保持未知，禁止重试")
                journal["steps"][step] = "success"
                journal["recovery_actions"][step].update(
                    {
                        "status": "success",
                        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "result": safe_result_summary(result_data),
                    }
                )
                statuses = {str(key): str(value) for key, value in dict(journal.get("steps") or {}).items()}
                if statuses.get("import") in {"success", "skipped"} and all(status in {"success", "skipped"} for name, status in statuses.items() if name in {"import", *RECOVERABLE_STEPS}):
                    journal["status"] = "success"
                else:
                    journal["status"] = "partial_or_unknown"
                self._persist_new_card_journal(journal_path, journal, logger)
                self.events.put(("new_card_recovery_finished", (step, current_batch.run_id, frozen_model_ids)))
            except Exception as exc:
                if step_started:
                    try:
                        raw = json.loads(journal_path.read_text(encoding="utf-8"))
                        if isinstance(raw, dict):
                            raw.setdefault("steps", {})[step] = "failed"
                            raw["status"] = "partial_or_unknown"
                            raw["error_type"] = type(exc).__name__
                            raw["recovery_actions"] = dict(raw.get("recovery_actions") or {})
                            action = dict(raw["recovery_actions"].get(step) or {})
                            action.update({"status": "failed", "error_type": type(exc).__name__, "message": redact_text(exc)})
                            raw["recovery_actions"][step] = action
                            self._persist_new_card_journal(journal_path, raw, logger)
                    except Exception:
                        # 已标记 running 但无法更新 journal 时，保留 running 让后续只读复核阻断。
                        pass
                self.events.put(("new_card_recovery_error", (step, batch.run_id, type(exc).__name__, redact_text(exc))))
            finally:
                try:
                    if write_access is not None and write_access_entered:
                        write_access.__exit__(None, None, None)
                finally:
                    self._force_backend_read_only()

        self.worker = threading.Thread(target=worker, name="fc27-new-card-recovery", daemon=True)
        self.worker.start()

    def _set_new_card_recovery_running(self, running: bool) -> None:
        if self.new_card_recovery_button is not None:
            self.new_card_recovery_button.configure(state="disabled" if running else "normal")
        if self.new_card_batch_combo is not None:
            self.new_card_batch_combo.configure(state="disabled" if running else "readonly")

    def _persist_new_card_journal(self, journal_path: Path, journal: Mapping[str, Any], logger: JsonlLogger) -> None:
        """原子更新新卡 journal、run.json、脱敏 JSONL 和主历史索引。"""

        status = str(journal.get("status") or "unknown")
        if status in {"success", "partial_or_unknown", "failed"} and not journal.get("finished_at"):
            mutable = dict(journal)
            mutable["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            journal = mutable
        atomic_write_json(journal_path, journal)
        steps = journal.get("steps") if isinstance(journal, Mapping) else {}
        atomic_write_json(
            journal_path.parent / "run.json",
            {
                "run_id": journal_path.parent.name,
                "run_dir": str(journal_path.parent),
                "started_at": journal.get("started_at", ""),
                "finished_at": journal.get("finished_at", ""),
                "status": journal.get("status", "unknown"),
                "steps": [
                    {"step": name, "status": str(value), "message": "新卡流程阶段"}
                    for name, value in dict(steps or {}).items()
                ],
            },
        )
        logger.write(
            "INFO",
            "new_card_stage",
            "新卡流程阶段记录",
            status=journal.get("status"),
            steps=steps,
            recovery_actions=journal.get("recovery_actions", {}),
        )
        self._append_new_card_history(journal_path, journal)

    def _append_new_card_history(self, journal_path: Path, journal: Mapping[str, Any]) -> None:
        """把新卡各步骤的安全摘要写入主窗口历史；不保存后台原始响应。"""

        steps = journal.get("steps") if isinstance(journal, Mapping) else {}
        safe_steps = []
        if isinstance(steps, Mapping):
            for step_name in ("import", "tags", "recommend", "sync"):
                safe_steps.append({"step": step_name, "status": str(steps.get(step_name) or "unknown"), "message": "新卡流程阶段"})
        record = {
            "run_id": journal_path.parent.name,
            "run_dir": str(journal_path.parent),
            "started_at": str(journal.get("started_at") or ""),
            "finished_at": str(journal.get("finished_at") or ""),
            "status": str(journal.get("status") or "unknown"),
            "steps": safe_steps,
        }
        history = self.store.load_history()
        # 同一 run_id 的恢复动作更新原记录，避免每次单步都制造重复历史。
        history = [
            item
            for item in history
            if isinstance(item, Mapping) and str(item.get("run_dir") or "") != record["run_dir"]
        ]
        history.insert(0, record)
        atomic_write_json(self.store.history_path, history[:200])

