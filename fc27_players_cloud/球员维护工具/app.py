"""FC27 球员维护工具的 tkinter 入口。拆分后：常量在 app_constants，格式化函数在 app_formatters，登录控件在 login_dialog，五个 mixin 分别承载已有模型维护页、新卡页、配置页、登录对话框与流水线控制。"""


import json
import base64
import os
import queue
import secrets
import sys
import threading
import tempfile
import zipfile
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import END, BooleanVar, Canvas, Listbox, StringVar, Text, Tk, Toplevel, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, Mapping, Optional

if __package__:
    from .admin_adapter import AdminAdapter, SUPPORTED_CID, SUPPORTED_GID, build_existing_model_map, extract_futbin_id, extract_model_id
    from .admin_client import AdminClient, AdminHttpError
    from .player_database import PlayerDatabaseClient
    from .adapters import BackendLoginAdapter, LoginRequest
    from .models import ExportFilters, PipelineConfig, RunRecord, StepName, StepResult
    from .pipeline import PipelineRunner
    from .selection import SelectionError, generate_existing_model_selection
    from .new_card_selection import NewCardSelectionBasket, filter_rows_by_ids, player_futbin_id, validate_intent_scope
    from .new_card_recovery import (
        BatchRecoveryBlocked,
        NewCardBatch,
        RECOVERABLE_STEPS,
        find_new_card_batches,
        load_new_card_batch,
        resolve_recovery_scope,
        safe_result_summary,
    )
    from .existing_model_ui import (
        ExistingModelSelector,
        ExistingModelManager,
        UnlistPlan,
        build_existing_action_preview,
        build_unlist_action_preview,
        format_futbin_id_export,
        selected_futbin_ids,
        widget_is_descendant,
    )
    from .storage import JsonlLogger, LocalStore, atomic_write_json, redact_text
else:  # 允许用户直接双击/运行 app.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.admin_adapter import AdminAdapter, SUPPORTED_CID, SUPPORTED_GID, build_existing_model_map, extract_futbin_id, extract_model_id
    from 球员维护工具.admin_client import AdminClient, AdminHttpError
    from 球员维护工具.player_database import PlayerDatabaseClient
    from 球员维护工具.adapters import BackendLoginAdapter, LoginRequest
    from 球员维护工具.models import ExportFilters, PipelineConfig, RunRecord, StepName, StepResult
    from 球员维护工具.pipeline import PipelineRunner
    from 球员维护工具.selection import SelectionError, generate_existing_model_selection
    from 球员维护工具.new_card_selection import NewCardSelectionBasket, filter_rows_by_ids, player_futbin_id, validate_intent_scope
    from 球员维护工具.new_card_recovery import (
        BatchRecoveryBlocked,
        NewCardBatch,
        RECOVERABLE_STEPS,
        find_new_card_batches,
        load_new_card_batch,
        resolve_recovery_scope,
        safe_result_summary,
    )
    from 球员维护工具.existing_model_ui import (
        ExistingModelSelector,
        ExistingModelManager,
        UnlistPlan,
        build_existing_action_preview,
        build_unlist_action_preview,
        format_futbin_id_export,
        selected_futbin_ids,
        widget_is_descendant,
    )
    from 球员维护工具.storage import JsonlLogger, LocalStore, atomic_write_json, redact_text


# ---- 从拆分模块重导出，保持 球员维护工具.app 旧引用兼容 ----
if __package__:
    from .app_constants import APP_DIR, FILTER_LABELS, RECOMMEND_MODE_LABELS, SCOPE_LABELS, STEP_LABELS
    from .app_formatters import (
        _format_existing_model_action_error,
        _model_ids_text,
        _new_card_action_status,
        _new_card_status_label,
        _safe_existing_model_action_error,
        format_new_card_batch_summary,
        format_new_card_completion,
    )
    from .login_dialog import AdminLoginController, _save_login_shape_diagnostic, apply_styles, configure_tk
    from .app_existing_models import ExistingModelsMixin
    from .app_new_card import NewCardMixin
    from .app_config import ConfigMixin
    from .app_login import LoginMixin
    from .app_pipeline import PipelineMixin
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_constants import APP_DIR, FILTER_LABELS, RECOMMEND_MODE_LABELS, SCOPE_LABELS, STEP_LABELS
    from 球员维护工具.app_formatters import (
        _format_existing_model_action_error,
        _model_ids_text,
        _new_card_action_status,
        _new_card_status_label,
        _safe_existing_model_action_error,
        format_new_card_batch_summary,
        format_new_card_completion,
    )
    from 球员维护工具.login_dialog import AdminLoginController, _save_login_shape_diagnostic, apply_styles, configure_tk
    from 球员维护工具.app_existing_models import ExistingModelsMixin
    from 球员维护工具.app_new_card import NewCardMixin
    from 球员维护工具.app_config import ConfigMixin
    from 球员维护工具.app_login import LoginMixin
    from 球员维护工具.app_pipeline import PipelineMixin


class PlayerMaintenanceApp(
    ExistingModelsMixin,
    NewCardMixin,
    ConfigMixin,
    LoginMixin,
    PipelineMixin,
):
    def __init__(self, root: Tk, backend_login: Optional[BackendLoginAdapter] = None) -> None:
        self.root = root
        self.root.title("FC27 球员维护工具")
        self.root.geometry("1120x760")
        self.root.minsize(920, 620)
        apply_styles(self.root)
        self.store = LocalStore(APP_DIR)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.runner = PipelineRunner(self.store, progress=self._on_pipeline_event)
        self.backend_login_handler = backend_login or AdminLoginController()
        self.admin_adapter: Optional[AdminAdapter] = None
        self.backend_session: Optional[object] = None
        self.worker: Optional[threading.Thread] = None
        self._build_vars()
        self._build_ui()
        self._load_default_config()
        self._load_saved_new_card_selection()
        self.root.after(150, self._poll_events)

    def _build_vars(self) -> None:
        self.source_var = StringVar()
        self.output_var = StringVar(value="runs")
        self.filters_var = StringVar(value="{}")
        self.filter_vars = {key: StringVar() for key in FILTER_LABELS}
        self.recommend_mode_var = StringVar(value=RECOMMEND_MODE_LABELS["unchanged"])
        self.tag_scope_var = StringVar(value="manual_ids")
        self.recommend_scope_var = StringVar(value="manual_ids")
        self.sync_scope_var = StringVar(value="current_batch")
        self.tag_ids_var = StringVar()
        self.tag_options: list[tuple[str, str]] = []
        # 新卡批次的三套独立选择；只保存 FUTBIN ID、展示字段和本地意图。
        self.new_card_days_var = StringVar(value="1")
        self.new_card_search_var = StringVar()
        # 收录规则：默认隐藏 85 分以下卡（可改阈值/关闭）；确认预览仍会警示低分卡。
        self.new_card_min_rating_var = BooleanVar(value=True)
        self.new_card_min_rating_value_var = StringVar(value="85")
        self.new_card_summary_var = StringVar(value="尚未拉取新增球员")
        self.new_card_basket = NewCardSelectionBasket()
        self.new_card_tree: Optional[ttk.Treeview] = None
        self.new_card_display_ids: list[str] = []
        self.new_card_existing_map: dict[str, int] = {}
        self.new_card_backend_map_checked = False
        self.new_card_fetch_button: Optional[ttk.Button] = None
        self.new_card_action_buttons: list[ttk.Button] = []
        self.new_card_selection_path = APP_DIR / "admin_state" / "new_card_selection.json"
        self.new_card_batches: tuple[NewCardBatch, ...] = ()
        self.new_card_batch_by_display: dict[str, NewCardBatch] = {}
        self.new_card_batch_var = StringVar()
        self.new_card_recovery_step_var = StringVar(value=STEP_LABELS["tags"])
        self.new_card_recovery_summary_var = StringVar(value="尚未加载历史导入批次")
        self.new_card_batch_combo: Optional[ttk.Combobox] = None
        self.new_card_recovery_button: Optional[ttk.Button] = None
        self.existing_model_manager = ExistingModelManager()
        self.existing_model_selector: Optional[ExistingModelSelector] = None
        self.step_vars = {step.value: BooleanVar(value=True) for step in StepName}
        self.single_step_var = StringVar(value=STEP_LABELS[StepName.EXPORT.value])
        self.status_var = StringVar(value="就绪")
        self.run_dir_var = StringVar(value="")
        # 运行中反馈状态（动画帧、进度、计时）；由 _begin_busy/_end_busy 维护。
        self._busy_active = False
        self._busy_frame = 0
        self._busy_total = 0
        self._busy_done = 0
        self._busy_label_text = ""
        self._busy_started_at = 0.0

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="后台操作").pack(side="left", padx=(0, 8))
        ttk.Label(toolbar, text="当前范围：FC 27（1327） → Players（9627）", foreground="#555555").pack(side="left", padx=(0, 14))
        ttk.Button(toolbar, text="后台登录", command=self._backend_login).pack(side="left", padx=3)
        ttk.Button(toolbar, text="后台只读检查", command=self._run_diagnostics).pack(side="left", padx=3)
        ttk.Button(toolbar, text="后台任务恢复", command=self._show_import_tasks).pack(side="left", padx=3)

        workspace = ttk.Notebook(outer)
        workspace.pack(fill="both", expand=True, pady=(0, 8))
        new_card_tab = ttk.Frame(workspace, padding=6)
        workspace.add(new_card_tab, text="新增球员上架")
        self._build_new_card_tab(new_card_tab)
        existing_tab = ttk.Frame(workspace, padding=6)
        workspace.add(existing_tab, text="后台模型维护")
        self._build_existing_model_tab(existing_tab)
        config_tab = ttk.Frame(workspace)
        workspace.add(config_tab, text="配置与筛选")
        config_tab.columnconfigure(0, weight=1)
        config_tab.rowconfigure(0, weight=1)
        config_canvas = Canvas(config_tab, highlightthickness=0)
        config_scroll = ttk.Scrollbar(config_tab, orient="vertical", command=config_canvas.yview)
        config_canvas.configure(yscrollcommand=config_scroll.set)
        config_canvas.grid(row=0, column=0, sticky="nsew")
        config_scroll.grid(row=0, column=1, sticky="ns")
        config_body = ttk.Frame(config_canvas)
        config_window = config_canvas.create_window((0, 0), window=config_body, anchor="nw")
        config_body.bind("<Configure>", lambda _event: config_canvas.configure(scrollregion=config_canvas.bbox("all")))
        config_canvas.bind("<Configure>", lambda event: config_canvas.itemconfigure(config_window, width=event.width))

        config_frame = ttk.LabelFrame(config_body, text="配置")
        config_frame.pack(fill="x", pady=(0, 8))
        config_frame.columnconfigure(1, weight=1)

        ttk.Label(config_frame, text="Excel 源文件/目录").grid(row=0, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(config_frame, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=6, pady=5)
        ttk.Button(config_frame, text="选择文件", command=self._choose_file).grid(row=0, column=2, padx=2, pady=5)
        ttk.Button(config_frame, text="选择目录", command=self._choose_directory).grid(row=0, column=3, padx=6, pady=5)

        ttk.Label(config_frame, text="运行输出目录").grid(row=1, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(config_frame, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=6, pady=5)
        ttk.Button(config_frame, text="选择目录", command=self._choose_output_directory).grid(row=1, column=2, padx=2, pady=5)

        filter_frame = ttk.LabelFrame(config_frame, text="数据库筛选（用于导出/生成名单，不是后台筛选；留空表示不加该条件）")
        filter_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=6, pady=5)
        for index, key in enumerate(FILTER_LABELS):
            row, col = divmod(index, 4)
            ttk.Label(filter_frame, text=FILTER_LABELS[key]).grid(row=row * 2, column=col * 2, sticky="w", padx=(6, 2), pady=(4, 0))
            ttk.Entry(filter_frame, textvariable=self.filter_vars[key], width=14).grid(row=row * 2 + 1, column=col * 2, sticky="ew", padx=(6, 10), pady=(0, 4))
            filter_frame.columnconfigure(col * 2, weight=1)
        advanced = ttk.Frame(config_frame)
        advanced.grid(row=3, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 3))
        ttk.Label(advanced, text="高级筛选 JSON（可选）").pack(side="left")
        ttk.Entry(advanced, textvariable=self.filters_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(
            config_frame,
            text="留空 Excel 源文件时，导出步骤调用已核实的只读数据库接口；Excel 源文件供格式处理/上传使用。数据库筛选至少填写一项才能生成后台已有名单。",
            foreground="#666666",
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 5))
        filter_actions = ttk.Frame(config_frame)
        filter_actions.grid(row=5, column=0, columnspan=4, sticky="e", padx=6, pady=(0, 5))
        ttk.Button(filter_actions, text="预览筛选球员", command=self._preview_players).pack(side="right", padx=(6, 0))
        self.generate_model_ids_button = ttk.Button(filter_actions, text="生成后台已有模型 ID", command=self._generate_existing_model_ids)
        self.generate_model_ids_button.pack(side="right")

        manual_frame = ttk.Frame(config_frame)
        manual_frame.grid(row=6, column=0, columnspan=4, sticky="ew", padx=6, pady=5)
        manual_frame.columnconfigure(1, weight=1)
        manual_frame.columnconfigure(3, weight=1)
        ttk.Label(manual_frame, text="FUTBIN ID（每行一个）").grid(row=0, column=0, sticky="nw", padx=(0, 5))
        self.ids_text = Text(manual_frame, height=4, width=32, wrap="none")
        self.ids_text.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(manual_frame, text="后台模型 ID（每行一个；保存后可能过期）").grid(row=0, column=2, sticky="nw", padx=(0, 5))
        self.model_ids_text = Text(manual_frame, height=4, width=32, wrap="none")
        self.model_ids_text.grid(row=0, column=3, sticky="ew")
        ttk.Label(manual_frame, text="标签名称备注（可选）").grid(row=1, column=0, sticky="nw", padx=(0, 5), pady=(5, 0))
        self.tags_text = Text(manual_frame, height=4, width=32, wrap="none")
        self.tags_text.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(5, 0))
        ttk.Label(manual_frame, text="已选标签 ID").grid(row=1, column=2, sticky="w", pady=(5, 0))
        ttk.Entry(manual_frame, textvariable=self.tag_ids_var, width=28).grid(row=1, column=3, sticky="ew", pady=(5, 0))
        ttk.Label(manual_frame, text="标签范围").grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Combobox(manual_frame, textvariable=self.tag_scope_var, values=tuple(SCOPE_LABELS.values()), state="readonly", width=16).grid(row=2, column=1, sticky="w", pady=(5, 0))
        ttk.Label(manual_frame, text="推荐范围").grid(row=2, column=2, sticky="w", pady=(5, 0))
        ttk.Combobox(manual_frame, textvariable=self.recommend_scope_var, values=tuple(SCOPE_LABELS.values()), state="readonly", width=16).grid(row=2, column=3, sticky="w", pady=(5, 0))
        ttk.Button(manual_frame, text="加载 FC27 Players 标签", command=self._load_tags).grid(row=3, column=3, sticky="e", pady=(5, 0))
        self.tag_listbox = Listbox(manual_frame, height=4, width=42, exportselection=False, selectmode="extended")
        self.tag_listbox.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        self.tag_listbox.bind("<<ListboxSelect>>", lambda _event: self._sync_tag_ids_from_listbox())
        ttk.Label(manual_frame, text="运行标签/推荐前请重新生成名单（数据库数据变化后旧名单可能过期）", foreground="#8a5a00").grid(row=4, column=2, columnspan=2, sticky="w", pady=(4, 0))

        run_frame = ttk.LabelFrame(outer, text="运行")
        run_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(run_frame, text="串行步骤").grid(row=0, column=0, sticky="w", padx=6, pady=5)
        step_box = ttk.Frame(run_frame)
        step_box.grid(row=0, column=1, columnspan=5, sticky="w", padx=6, pady=5)
        for index, step in enumerate(StepName):
            ttk.Checkbutton(step_box, text=STEP_LABELS[step.value], variable=self.step_vars[step.value]).grid(row=0, column=index, padx=(0, 8))
        ttk.Label(run_frame, text="推荐").grid(row=1, column=0, sticky="w", padx=6, pady=5)
        ttk.Combobox(run_frame, textvariable=self.recommend_mode_var, values=tuple(RECOMMEND_MODE_LABELS.values()), state="readonly", width=8).grid(row=1, column=1, sticky="w", padx=3, pady=5)
        ttk.Label(run_frame, text="默认不变，不清空已有推荐").grid(row=1, column=2, sticky="w", padx=6, pady=5)
        ttk.Label(run_frame, text="同步范围").grid(row=2, column=0, sticky="w", padx=6, pady=5)
        ttk.Combobox(run_frame, textvariable=self.sync_scope_var, values=tuple(SCOPE_LABELS.values()), state="readonly", width=16).grid(row=2, column=1, sticky="w", padx=3, pady=5)
        ttk.Label(run_frame, text="单步").grid(row=1, column=3, sticky="e", padx=(10, 3), pady=5)
        ttk.Combobox(run_frame, textvariable=self.single_step_var, values=[STEP_LABELS[step.value] for step in StepName], state="readonly", width=16).grid(row=1, column=4, sticky="w", padx=3, pady=5)
        self.run_all_button = ttk.Button(run_frame, text="运行已选步骤", command=self._run_all)
        self.run_all_button.grid(row=1, column=5, padx=3, pady=5)
        self.run_step_button = ttk.Button(run_frame, text="运行单步", command=self._run_step)
        self.run_step_button.grid(row=1, column=6, padx=3, pady=5)
        self.stop_button = ttk.Button(run_frame, text="停止", command=self._stop, state="disabled")
        self.stop_button.grid(row=1, column=7, padx=3, pady=5)
        ttk.Button(run_frame, text="保存配置", command=self._save_config).grid(row=2, column=5, padx=(15, 3), pady=5)
        ttk.Button(run_frame, text="加载配置", command=self._load_config_dialog).grid(row=2, column=6, padx=3, pady=5)

        status_frame = ttk.Frame(outer)
        status_frame.pack(fill="x", pady=(0, 8))
        # 状态栏：左侧是「动画 + 文字」，让用户在长任务里也能确认工具还活着。
        self.busy_label = ttk.Label(status_frame, text="", width=3, anchor="center", foreground="#0969da")
        self.busy_label.pack(side="left")
        ttk.Label(status_frame, textvariable=self.status_var, foreground="#333333").pack(side="left")
        self.busy_elapsed_label = ttk.Label(status_frame, text="", foreground="#8a5a00")
        self.busy_elapsed_label.pack(side="left", padx=(6, 0))
        ttk.Label(status_frame, textvariable=self.run_dir_var, foreground="#666666").pack(side="right")
        # 进度条：不确定总量时为 indeterminate 动画，已知总量时走 determinate。
        self.busy_progress = ttk.Progressbar(outer, mode="indeterminate", length=200)
        self.busy_progress.pack(fill="x", pady=(0, 6))
        self.busy_progress.pack_forget()

        log_frame = ttk.Frame(workspace, padding=5)
        history_frame = ttk.Frame(workspace, padding=5)
        workspace.add(log_frame, text="运行日志")
        workspace.add(history_frame, text="历史")
        self.log_text = ScrolledText(log_frame, wrap="none", state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.history_text = ScrolledText(history_frame, wrap="none", state="disabled")
        self.history_text.pack(fill="both", expand=True)
        self._refresh_history()

    # ---- 后台已有模型维护 ----



def main(backend_login: Optional[BackendLoginAdapter] = None) -> int:
    configure_tk()
    if "--probe-tk" in sys.argv[1:] or "--probe-runtime" in sys.argv[1:]:
        try:
            if "--probe-runtime" in sys.argv[1:]:
                import openpyxl  # noqa: F401
            probe = Tk()
            probe.withdraw()
            probe.update_idletasks()
            probe.destroy()
            return 0
        except Exception as exc:
            print(f"tkinter 不可用：{exc}", file=sys.stderr)
            return 2
    try:
        root = Tk()
    except Exception as exc:
        print(f"无法启动 tkinter：{exc}", file=sys.stderr)
        print("请检查本机 Python 是否带 Tcl/Tk；启动工具.bat 会探测 bundled runtime。", file=sys.stderr)
        return 2
    PlayerMaintenanceApp(root, backend_login=backend_login)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
