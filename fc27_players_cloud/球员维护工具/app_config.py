"""PlayerMaintenanceApp 的配置读写、文件选择与筛选预览。"""

from __future__ import annotations

import json
from pathlib import Path
import threading
from tkinter import END
from tkinter import Text
from tkinter import Toplevel
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from typing import Any
from typing import Mapping
from 球员维护工具.models import ExportFilters
from 球员维护工具.models import PipelineConfig
from 球员维护工具.player_database import PlayerDatabaseClient
from 球员维护工具.selection import SelectionError
from 球员维护工具.selection import generate_existing_model_selection
from 球员维护工具.transformer import filter_existing_players
import sys

if __package__:
    from .app_constants import RECOMMEND_MODE_LABELS, SCOPE_LABELS
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_constants import RECOMMEND_MODE_LABELS, SCOPE_LABELS

class ConfigMixin:
    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(title="选择本地源文件")
        if selected:
            self.source_var.set(selected)

    def _choose_directory(self) -> None:
        selected = filedialog.askdirectory(title="选择本地源目录")
        if selected:
            self.source_var.set(selected)

    def _choose_output_directory(self) -> None:
        selected = filedialog.askdirectory(title="选择运行输出目录")
        if selected:
            self.output_var.set(selected)

    def _read_config(self) -> PipelineConfig:
        try:
            advanced = json.loads(self.filters_var.get().strip() or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"高级筛选 JSON 无效：{exc}") from exc
        if not isinstance(advanced, dict):
            raise ValueError("高级筛选必须是 JSON 对象")
        filters = dict(advanced)
        for key, variable in self.filter_vars.items():
            value = variable.get().strip()
            if value:
                filters[key] = value
        return PipelineConfig(
            source_path=self.source_var.get().strip(),
            output_root=self.output_var.get().strip() or "runs",
            export_filters=ExportFilters(filters),
            manual_player_ids=self._read_lines(self.ids_text),
            manual_model_ids=self._read_lines(self.model_ids_text),
            manual_tags=self._read_lines(self.tags_text),
            manual_tag_ids=self._read_lines_value(self.tag_ids_var.get()),
            recommend_mode=next((mode for mode, label in RECOMMEND_MODE_LABELS.items() if label == self.recommend_mode_var.get()), "unchanged"),
            recommend_enabled=None,
            tag_scope=next((scope for scope, label in SCOPE_LABELS.items() if label == self.tag_scope_var.get()), "manual_ids"),
            recommend_scope=next((scope for scope, label in SCOPE_LABELS.items() if label == self.recommend_scope_var.get()), "manual_ids"),
            sync_scope=next((scope for scope, label in SCOPE_LABELS.items() if label == self.sync_scope_var.get()), "current_batch"),
            existing_player_policy="new_only",
            selected_steps=[step for step, variable in self.step_vars.items() if variable.get()],
        ).normalized()

    @staticmethod
    def _read_lines(widget: Text) -> list[str]:
        return [line.strip() for line in widget.get("1.0", END).replace(",", "\n").splitlines() if line.strip()]

    @staticmethod
    def _read_lines_value(value: str) -> list[str]:
        return [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]

    def _apply_config(self, config: PipelineConfig) -> None:
        config = config.normalized()
        self.source_var.set(config.source_path)
        self.output_var.set(config.output_root)
        criteria = dict(config.export_filters.criteria)
        for key, variable in self.filter_vars.items():
            variable.set(str(criteria.pop(key, "")))
        self.filters_var.set(json.dumps(criteria, ensure_ascii=False) if criteria else "")
        self.recommend_mode_var.set(RECOMMEND_MODE_LABELS.get(config.recommend_mode, RECOMMEND_MODE_LABELS["unchanged"]))
        self.tag_scope_var.set(SCOPE_LABELS.get(config.tag_scope, SCOPE_LABELS["manual_ids"]))
        self.recommend_scope_var.set(SCOPE_LABELS.get(config.recommend_scope, SCOPE_LABELS["manual_ids"]))
        self.sync_scope_var.set(SCOPE_LABELS.get(config.sync_scope, SCOPE_LABELS["current_batch"]))
        for step, variable in self.step_vars.items():
            variable.set(step in config.selected_steps)
        self._replace_text(self.ids_text, "\n".join(config.manual_player_ids))
        self._replace_text(self.model_ids_text, "\n".join(config.manual_model_ids))
        self._replace_text(self.tags_text, "\n".join(config.manual_tags))
        self.tag_ids_var.set(",".join(config.manual_tag_ids))

    @staticmethod
    def _replace_text(widget: Text, value: str) -> None:
        widget.delete("1.0", END)
        widget.insert("1.0", value)

    def _load_default_config(self) -> None:
        try:
            self._apply_config(self.store.load_config())
        except (OSError, ValueError):
            pass

    def _save_config(self) -> None:
        try:
            config = self._read_config()
            target = self.store.save_config(config)
            self.status_var.set(f"配置已保存：{target}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("配置错误", str(exc))

    def _load_config_dialog(self) -> None:
        selected = filedialog.askopenfilename(title="加载 JSON 配置", filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not selected:
            return
        try:
            self._apply_config(self.store.load_config(Path(selected)))
            self.status_var.set(f"已加载配置：{selected}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("配置错误", str(exc))

    def _load_tags(self) -> None:
        if self.admin_adapter is None:
            messagebox.showinfo("加载标签", "请先完成后台登录；未读取浏览器凭据。")
            return
        try:
            tags = self.admin_adapter.client.list_tags()
            self.tag_options = []
            self.tag_listbox.delete(0, END)
            for item in tags:
                tag_id = str(item.get("id") or "").strip()
                label = str(item.get("title") or item.get("name") or item.get("tag_name") or tag_id).strip()
                if tag_id:
                    self.tag_options.append((tag_id, label))
                    self.tag_listbox.insert(END, f"{label}（ID {tag_id}）")
            if self.existing_model_selector is not None:
                self.existing_model_selector.set_tag_catalog({int(tag_id): label for tag_id, label in self.tag_options if tag_id.isdigit()})
            self.status_var.set(f"已加载 {len(self.tag_options)} 个后台标签；可在“后台模型维护”页多选后批量操作")
        except Exception as exc:
            messagebox.showerror("加载标签失败", str(exc))

    def _sync_tag_ids_from_listbox(self) -> None:
        selected = self.tag_listbox.curselection()
        values = [self.tag_options[index][0] for index in selected if index < len(self.tag_options)]
        if values:
            self.tag_ids_var.set(",".join(values))

    @staticmethod
    def _filter_existing_players(source: Path, existing_ids: list[str], target: Path) -> Path:
        if __package__:
            from .transformer import filter_existing_players
        else:
            from 球员维护工具.transformer import filter_existing_players

        result = filter_existing_players(source, existing_ids, target)
        if not result.output_path:
            raise ValueError("本批次没有新增球员，未生成上传文件")
        return Path(result.output_path)

    @staticmethod
    def _product_verifier(model_id: int, phase: str, products: Any) -> Mapping[str, Any]:
        """只核验后台产品行结构和范围，不伪造价格变化或自行定价。"""

        if not products:
            return {"verified": False, "baseline_captured": phase == "before", "formula_verified": False}
        return {
            "verified": True,
            "baseline_captured": phase == "before",
            "formula_verified": False,
            "note": "仅核验实际产品行；未独立重算或假设价格变化",
        }

    def _preview_players(self) -> None:
        try:
            config = self._read_config()
        except ValueError as exc:
            messagebox.showerror("筛选错误", str(exc))
            return

        def worker() -> None:
            try:
                result = PlayerDatabaseClient().list_players(config.export_filters, page=1, per_page=50)
                self.events.put(("preview", result.to_dict()))
            except Exception as exc:
                self.events.put(("preview_error", str(exc)))

        threading.Thread(target=worker, name="fc27-player-preview", daemon=True).start()
        self.status_var.set("正在读取筛选预览…")

    def _generate_existing_model_ids(self) -> None:
        """按数据库筛选生成后台已有模型 ID；只读，确认后才替换文本框。"""

        if self.admin_adapter is None:
            messagebox.showinfo("生成后台已有模型 ID", "请先完成后台登录；此功能只读取后台模型列表，不会写入。")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在运行", "当前已有动作，请先等待完成")
            return
        try:
            config = self._read_config()
        except ValueError as exc:
            messagebox.showerror("筛选错误", str(exc))
            return

        admin_adapter = self.admin_adapter
        self._set_existing_selection_running(True)
        self.status_var.set("正在完整读取数据库筛选结果和后台已有模型…")

        def worker() -> None:
            try:
                result = generate_existing_model_selection(
                    PlayerDatabaseClient(),
                    admin_adapter,
                    config.export_filters,
                )
                # 事件只携带必要的 ID 和统计，不把球员原始对象写入日志或配置。
                self.events.put(("existing_model_selection_ready", result.to_dict()))
            except SelectionError as exc:
                self.events.put(("existing_model_selection_error", str(exc)))
            except Exception as exc:
                # 网络异常只回传类型，避免把 URL、响应或认证信息带入 GUI 消息。
                self.events.put(("existing_model_selection_error", f"读取失败；异常类型：{type(exc).__name__}"))

        self.worker = threading.Thread(target=worker, name="fc27-existing-model-selection", daemon=True)
        self.worker.start()

    def _set_existing_selection_running(self, running: bool) -> None:
        button = getattr(self, "generate_model_ids_button", None)
        if button is not None:
            button.configure(state="disabled" if running else "normal")

    def _show_existing_model_selection_preview(self, payload: Mapping[str, Any]) -> None:
        """展示 ID/数量预览；只有点击确认按钮才覆盖后台模型 ID 文本框。"""

        try:
            model_ids = [str(item).strip() for item in payload.get("model_ids", []) if str(item).strip()]
            existing_ids = [str(item).strip() for item in payload.get("existing_futbin_ids", []) if str(item).strip()]
            missing_ids = [str(item).strip() for item in payload.get("missing_futbin_ids", []) if str(item).strip()]
            model_id_by_futbin = {str(key): str(value) for key, value in dict(payload.get("model_id_by_futbin", {})).items()}
        except (TypeError, ValueError) as exc:
            messagebox.showerror("生成后台已有模型 ID", f"预览数据无效，未替换模型 ID：{exc}")
            return

        filtered_count = int(payload.get("filtered_count", payload.get("total", 0)) or 0)
        existing_count = int(payload.get("existing_count", len(existing_ids)) or 0)
        missing_count = int(payload.get("missing_count", len(missing_ids)) or 0)
        backend_count = int(payload.get("backend_model_count", 0) or 0)
        current_count = len(self._read_lines(self.model_ids_text))

        window = Toplevel(self.root)
        window.title("后台已有模型 ID 预览（只读）")
        window.geometry("760x520")
        window.transient(self.root)
        summary = (
            f"数据库筛选命中：{filtered_count}；后台已有：{existing_count}；未建模型：{missing_count}；"
            f"后台模型总数：{backend_count}\n"
            f"确认后将替换当前文本框中的 {current_count} 个模型 ID。"
        )
        ttk.Label(window, text=summary, justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        ttk.Label(
            window,
            text="仅展示 FUTBIN ID 与后台模型 ID；这是数据库筛选和后台已有模型的交集，不是后台筛选条件。",
            foreground="#555555",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        table_frame = ttk.Frame(window)
        table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        table = ttk.Treeview(table_frame, columns=("futbin_id", "model_id", "state"), show="headings")
        for column, heading, width in (("futbin_id", "FUTBIN ID", 220), ("model_id", "后台模型 ID", 220), ("state", "状态", 180)):
            table.heading(column, text=heading)
            table.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for futbin_id in existing_ids:
            table.insert("", "end", values=(futbin_id, model_id_by_futbin.get(futbin_id, ""), "后台已有，将生成"))
        for futbin_id in missing_ids:
            table.insert("", "end", values=(futbin_id, "", "后台未建模型，跳过"))

        action_frame = ttk.Frame(window)
        action_frame.pack(fill="x", padx=8, pady=(0, 8))
        if existing_count < 1 or not model_ids:
            ttk.Label(action_frame, text="没有后台已有模型 ID，已阻止覆盖当前文本框。", foreground="#a33").pack(side="left")
        else:
            ttk.Label(action_frame, text="名单生成后仍可能随数据库变化而过期；执行标签/推荐前请重新生成。", foreground="#8a5a00").pack(side="left")

        def replace_ids() -> None:
            if existing_count < 1 or not model_ids:
                return
            self._replace_text(self.model_ids_text, "\n".join(model_ids))
            self.status_var.set(f"已生成并确认替换 {len(model_ids)} 个后台模型 ID；运行前请重新生成名单")
            window.destroy()

        confirm = ttk.Button(action_frame, text="确认替换后台模型 ID", command=replace_ids, state="normal" if existing_count > 0 and model_ids else "disabled")
        confirm.pack(side="right", padx=(6, 0))
        ttk.Button(action_frame, text="取消", command=window.destroy).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", window.destroy)

