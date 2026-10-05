"""FC27 已有模型的 Tk 选择器；纯业务对象由 existing_model_domain 提供。"""
from __future__ import annotations
from tkinter import END, EXTENDED, Listbox, ttk
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from .existing_model_domain import *

class ExistingModelSelector(ttk.LabelFrame):
    """可嵌入主窗口的已有模型选择器。

    父窗口通过 ``set_rows`` 注入只读全量结果，并从 ``on_action`` 接收
    ``("tags"|"tags_remove"|"recommend_enable"|"recommend_disable"|"unlist", ids)``。
    """

    def __init__(
        self,
        master: Any,
        *,
        manager: ExistingModelManager | None = None,
        on_selection_changed: Optional[Callable[[tuple[int, ...]], None]] = None,
        on_action: Optional[Callable[[str, tuple[int, ...]], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_load_tags: Optional[Callable[[], None]] = None,
        on_export: Optional[Callable[[tuple[int, ...]], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, text="后台已有球员模型（FC27 / Players）", **kwargs)
        self.manager = manager or ExistingModelManager()
        self.on_selection_changed = on_selection_changed
        self.on_action = on_action
        self.on_refresh = on_refresh
        self.on_load_tags = on_load_tags
        self.on_export = on_export
        self._tag_catalog: dict[int, str] = {}
        self._tag_id_by_label: dict[str, int] = {}
        self._status = ttk.Label(
            self,
            text="尚未加载后台模型；完成后台登录后将自动加载，也可点击右上角「获取/刷新后台模型」",
            foreground="#8a5a00",
        )
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        filters = ttk.Frame(self)
        filters.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        filters.columnconfigure(5, weight=1)
        self._recommend_var = ttk.Combobox(filters, state="readonly", width=10, values=("全部推荐", "已开启", "未开启"))
        self._recommend_var.current(0)
        self._recommend_var.grid(row=0, column=0, padx=(0, 5))
        self._tag_id_var = ttk.Entry(filters, width=10)
        self._tag_id_var.grid(row=0, column=1, padx=2)
        ttk.Label(filters, text="标签 ID").grid(row=0, column=2, padx=(1, 5))
        self._tag_name_var = ttk.Combobox(filters, width=16, state="normal", values=())
        self._tag_name_var.grid(row=0, column=3, padx=2)
        self._tag_name_var.configure(postcommand=self._refresh_tag_name_values)
        ttk.Label(filters, text="标签名称").grid(row=0, column=4, padx=(5, 2))
        self._keyword_var = ttk.Entry(filters, width=20)
        self._keyword_var.grid(row=0, column=5, sticky="ew", padx=4)
        self._keyword_var.insert(0, "标题 / FUTBIN ID / 模型 ID")
        self._keyword_var.bind("<FocusIn>", lambda _event: self._clear_placeholder(self._keyword_var, "标题 / FUTBIN ID / 模型 ID"))
        ttk.Button(filters, text="筛选", command=self.apply_filter).grid(row=0, column=6, padx=4)
        ttk.Button(filters, text="获取/刷新后台模型", command=self._refresh_clicked).grid(row=0, column=7, padx=(2, 0))

        tag_actions = ttk.LabelFrame(self, text="对已选择模型批量操作标签")
        tag_actions.grid(row=2, column=0, sticky="ew", padx=8, pady=(2, 6))
        tag_actions.columnconfigure(0, weight=1)
        self._tag_listbox = Listbox(tag_actions, height=3, selectmode=EXTENDED, exportselection=False)
        self._tag_listbox.grid(row=0, column=0, rowspan=3, sticky="ew", padx=(6, 4), pady=5)
        self._tag_listbox.insert(END, "请先点击“加载 FC27 Players 标签”")
        self._tag_listbox.configure(state="disabled")
        tag_button_column = ttk.Frame(tag_actions)
        tag_button_column.grid(row=0, column=1, rowspan=3, sticky="ns", padx=(4, 7), pady=5)
        ttk.Button(tag_button_column, text="加载 FC27 Players 标签", command=self._load_tags_clicked).pack(fill="x", pady=(0, 4))
        # 写入类按钮留引用：动作进行中统一禁用，防止重复点击造成并发修改。
        self._busy_buttons = []
        add_tags_button = ttk.Button(tag_button_column, text="添加所选标签", command=lambda: self._action("tags"))
        add_tags_button.pack(fill="x", pady=(0, 4))
        remove_tags_button = ttk.Button(tag_button_column, text="移除所选标签", command=lambda: self._action("tags_remove"))
        remove_tags_button.pack(fill="x")
        tag_select_row = ttk.Frame(tag_actions)
        tag_select_row.grid(row=3, column=0, columnspan=2, sticky="w", padx=7, pady=(0, 3))
        ttk.Button(tag_select_row, text="全选标签", command=self._select_all_tags).pack(side="left", padx=(0, 4))
        ttk.Button(tag_select_row, text="清空标签选择", command=self._clear_tag_selection).pack(side="left", padx=(0, 4))
        ttk.Label(tag_actions, text="可点「全选标签」一次选中全部；也可用 Ctrl/Shift 多选。操作前会显示模型和标签范围供确认。", foreground="#666666").grid(row=4, column=0, columnspan=2, sticky="w", padx=7, pady=(0, 5))
        self._tag_selection_status = ttk.Label(tag_actions, text="当前选中标签：0 个")
        self._tag_selection_status.grid(row=5, column=0, columnspan=2, sticky="w", padx=7, pady=(0, 5))
        self._tag_listbox.bind("<<ListboxSelect>>", self._update_tag_selection_status)

        columns = ("pick", "id", "futbin", "title", "rec", "tag_ids", "tag_names", "status", "auto_off")
        table_frame = ttk.Frame(self)
        table_frame.grid(row=4, column=0, sticky="nsew", padx=8, pady=2)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14, selectmode="extended")
        headings = {
            "pick": "选择", "id": "模型ID", "futbin": "FUTBIN ID", "title": "标题", "rec": "推荐",
            "tag_ids": "标签ID", "tag_names": "标签名称", "status": "状态", "auto_off": "自动下架",
        }
        widths = {"pick": 52, "id": 85, "futbin": 100, "title": 245, "rec": 62, "tag_ids": 115, "tag_names": 190, "status": 70, "auto_off": 85}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=45, stretch=column in {"title", "tag_names"}, anchor="center" if column != "title" else "w")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self._tree_vertical_scrollbar = vertical
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        style = ttk.Style(self)
        style.configure("ExistingModels.Treeview", rowheight=25)
        style.configure("ExistingModels.Treeview.Heading", font=("Segoe UI", 9, "bold"))
        self.tree.configure(style="ExistingModels.Treeview")
        self.tree.tag_configure("stripe", background="#f3f6fa")
        self.tree.bind("<Button-1>", self._toggle_checkbox)

        selection = ttk.Frame(self)
        selection.grid(row=5, column=0, sticky="ew", padx=8, pady=(4, 2))
        ttk.Button(selection, text="全选当前筛选", command=self._select_visible).pack(side="left", padx=(0, 4))
        ttk.Button(selection, text="取消当前筛选", command=self._deselect_visible).pack(side="left", padx=4)
        ttk.Button(selection, text="清空选择", command=self._clear_selection).pack(side="left", padx=4)
        ttk.Button(selection, text="导出选中 FUTBIN ID（TXT）", command=self._export_clicked).pack(side="left", padx=(12, 4))

        actions = ttk.LabelFrame(self, text="其他模型操作")
        actions.grid(row=6, column=0, sticky="ew", padx=8, pady=(2, 3))
        enable_rec_button = ttk.Button(actions, text="开启推荐", command=lambda: self._action("recommend_enable"))
        enable_rec_button.pack(side="left", padx=5, pady=5)
        disable_rec_button = ttk.Button(actions, text="关闭推荐", command=lambda: self._action("recommend_disable"))
        disable_rec_button.pack(side="left", padx=5, pady=5)
        unlist_button = ttk.Button(actions, text="下架所选模型", command=lambda: self._action("unlist"))
        unlist_button.pack(side="left", padx=5, pady=5)
        self._busy_buttons = [
            *getattr(self, "_busy_buttons", []),
            add_tags_button,
            remove_tags_button,
            enable_rec_button,
            disable_rec_button,
            unlist_button,
        ]
        # 状态行放在筛选区正下方：不滚动就能看到加载状态与空态引导。
        self._status.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 2))
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._notify_selection())
        self._render()

    @staticmethod
    def _clear_placeholder(widget: Any, placeholder: str) -> None:
        if widget.get() == placeholder:
            widget.delete(0, "end")

    def _refresh_clicked(self) -> None:
        if self.on_refresh is None:
            self._status.configure(text="请由主程序读取后台全量模型后调用 set_rows")
            return
        self.on_refresh()

    def _load_tags_clicked(self) -> None:
        if self.on_load_tags is None:
            self._status.configure(text="请由主程序加载 FC27 Players 标签")
            return
        self.on_load_tags()

    def set_rows(self, rows: Iterable[Mapping[str, Any]]) -> tuple[ExistingModelRow, ...]:
        result = self.manager.replace_rows(rows)
        self._render()
        self._notify_selection()
        return result

    def set_tag_catalog(self, catalog: Mapping[int | str, Any] | None) -> Mapping[int, str]:
        result = self.manager.set_tag_catalog(catalog)
        self._tag_catalog = dict(result)
        self._tag_id_by_label = {self._tag_option(tag_id, name): tag_id for tag_id, name in sorted(result.items())}
        self._tag_listbox.configure(state="normal")
        self._tag_listbox.delete(0, END)
        for label in self._tag_id_by_label:
            self._tag_listbox.insert(END, label)
        if not self._tag_id_by_label:
            self._tag_listbox.insert(END, "后台暂无已加载标签")
            self._tag_listbox.configure(state="disabled")
        self._update_tag_selection_status()
        self._refresh_tag_name_values()
        self._render()
        return result

    @staticmethod
    def _tag_option(tag_id: int, name: str) -> str:
        return f"{tag_id} | {name or '未命名标签'}"

    def _refresh_tag_name_values(self) -> None:
        self._tag_name_var.configure(values=tuple(sorted(set(self._tag_catalog.values()), key=str.casefold)))

    def selected_tag_ids(self) -> tuple[int, ...]:
        selected = []
        for index in self._tag_listbox.curselection():
            label = self._tag_listbox.get(index)
            tag_id = self._tag_id_by_label.get(label)
            if tag_id is not None and tag_id not in selected:
                selected.append(tag_id)
        return tuple(selected)

    def _update_tag_selection_status(self, _event: Any = None) -> None:
        if hasattr(self, "_tag_selection_status"):
            self._tag_selection_status.configure(text=f"当前选中标签：{len(self.selected_tag_ids())} 个")

    def set_busy(self, busy: bool) -> None:
        """后台动作进行中禁用写入类按钮，避免重复点击造成并发修改。"""

        state = "disabled" if busy else "normal"
        for button in getattr(self, "_busy_buttons", ()):
            try:
                button.configure(state=state)
            except Exception:
                pass

    def _select_all_tags(self) -> None:
        """一次选中标签列表里的全部标签；无标签或未加载时给出提示而不报错。"""
        if self._tag_listbox.cget("state") == "disabled":
            self._tag_selection_status.configure(text="当前选中标签：0 个（标签列表未加载，请先「加载 FC27 Players 标签」）")
            return
        self._tag_listbox.selection_set(0, END)
        self._update_tag_selection_status()

    def _clear_tag_selection(self) -> None:
        """清空标签列表的选择，不影响模型勾选。"""
        if self._tag_listbox.cget("state") == "disabled":
            self._tag_selection_status.configure(text="当前选中标签：0 个（标签列表未加载，请先「加载 FC27 Players 标签」）")
            return
        self._tag_listbox.selection_clear(0, END)
        self._update_tag_selection_status()

    def refresh_from_backend(self, backend: Any) -> tuple[ExistingModelRow, ...]:
        """由主窗口在后台线程完成读取后调用；只接受已有模型全量适配器。"""

        result = self.manager.load(backend)
        self._render()
        self._notify_selection()
        return result

    def apply_filter(self) -> ExistingModelFilter:
        choice = self._recommend_var.get()
        is_rec = None if choice == "全部推荐" else (1 if choice == "已开启" else 0)
        tag_id_text = self._tag_id_var.get().strip()
        tag_name = self._tag_name_var.get().strip()
        keyword = "" if self._keyword_var.get() == "标题 / FUTBIN ID / 模型 ID" else self._keyword_var.get()
        criteria = self.manager.set_filter(is_rec=is_rec, tag_id=tag_id_text or None, tag_name=tag_name, keyword=keyword)
        self._render()
        return criteria

    def _toggle_checkbox(self, event: Any) -> str | None:
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if region == "cell" and column == "#1" and item:
            self.manager.toggle(int(item))
            self._render()
            self._notify_selection()
            return "break"
        return None

    def _select_visible(self) -> None:
        self.manager.select_visible()
        self._render()
        self._notify_selection()

    def _deselect_visible(self) -> None:
        self.manager.deselect_visible()
        self._render()
        self._notify_selection()

    def _clear_selection(self) -> None:
        self.manager.clear_selection()
        self._render()
        self._notify_selection()

    def _notify_selection(self) -> None:
        if self.on_selection_changed is not None:
            self.on_selection_changed(self.manager.selected_model_ids())

    def _action(self, action: str) -> None:
        ids = self.manager.selected_model_ids()
        if not ids:
            self._status.configure(text="请先选择至少一个模型")
            return
        if action in {"tags", "tags_remove"} and not self.selected_tag_ids():
            self._status.configure(text="请先在上方标签列表中选择一个或多个标签")
            return
        if self.on_action is None:
            self._status.configure(text=f"已选择 {len(ids)} 个模型；请由主程序处理 {action}")
            return
        self.on_action(action, ids)

    def _export_clicked(self) -> None:
        ids = self.manager.selected_model_ids()
        if not ids:
            self._status.configure(text="请先选择至少一个模型")
            return
        if self.on_export is None:
            self._status.configure(text=f"已选择 {len(ids)} 个模型；请由主程序处理 FUTBIN ID 导出")
            return
        self.on_export(ids)

    def _render(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected = set(self.manager.selected_model_ids())
        rows = self.manager.visible_rows()
        for index, row in enumerate(rows):
            self.tree.insert(
                "", "end", iid=str(row.model_id),
                values=(
                    "☑" if row.model_id in selected else "☐",
                    row.model_id,
                    row.futbin_id,
                    row.title,
                    "是" if row.is_rec == 1 else ("否" if row.is_rec == 0 else "待核实"),
                    ",".join(str(item) for item in row.tag_ids),
                    ", ".join(self.manager.tag_names_for(row)),
                    "启用" if row.status == 1 else ("关闭" if row.status == 0 else "待核实"),
                    "是" if row.auto_off == 1 else ("否" if row.auto_off == 0 else "待核实"),
                ),
                tags=(("stripe",) if index % 2 else ()),
            )
        if not self.manager.rows:
            self._status.configure(
                text="尚未加载后台模型；完成后台登录后将自动加载，也可点击右上角「获取/刷新后台模型」",
                foreground="#8a5a00",
            )
        else:
            self._status.configure(
                text=f"当前筛选显示 {len(rows)} / 后台总数 {len(self.manager.rows)}；已选择 {len(selected)}",
                foreground="#000000",
            )


__all__ = [
    "ExistingModelError",
    "ExistingModelFilter",
    "ExistingModelManager",
    "ExistingModelRow",
    "ExistingModelSelector",
    "UnlistBlocked",
    "UnlistPlan",
    "UnlistProductScope",
    "build_existing_action_preview",
    "build_unlist_action_preview",
    "build_unlist_plan",
    "format_futbin_id_export",
    "filter_model_rows",
    "normalize_model_rows",
    "selected_futbin_ids",
    "widget_is_descendant",
]
