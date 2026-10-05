"""登录控制器、登录诊断与 Tk 样式配置。"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import sys
from typing import Any
from typing import Mapping
from typing import Optional
import zipfile
from tkinter import ttk
from tkinter import font as tkfont
from 球员维护工具.adapters import LoginRequest
from 球员维护工具.admin_client import AdminClient
from 球员维护工具.storage import atomic_write_json

if __package__:
    from .app_constants import APP_DIR
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_constants import APP_DIR

class AdminLoginController:
    """把 AdminClient 的验证码登录流程封装为 GUI 内存接口。"""

    def __init__(self, client: Optional[AdminClient] = None) -> None:
        self.client = client or AdminClient()
        self.captcha_id = ""

    def prepare_captcha(self) -> bytes:
        self.client.get_login_config()
        self.captcha_id = secrets.token_urlsafe(16)
        return self.client.fetch_captcha(self.captcha_id)

    def login(self, request: LoginRequest) -> object:
        if not request.captcha_id or request.captcha_id != self.captcha_id:
            raise ValueError("验证码已失效，请刷新后重试")
        return self.client.login(request.username, request.password, request.captcha, request.captcha_id, keep=False)


def _save_login_shape_diagnostic(exc: BaseException) -> None:
    """只保存认证响应的安全结构摘要，不保存账号、响应值或 token。"""

    diagnostic = getattr(exc, "diagnostic", None)
    if not isinstance(diagnostic, Mapping):
        return

    def storage_shape(value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "fields" and isinstance(item, Mapping):
                result["fields"] = [
                    {"name": str(field_name), **storage_shape(field_shape)}
                    for field_name, field_shape in item.items()
                    if isinstance(field_shape, Mapping)
                ]
            else:
                result[str(key)] = storage_shape(item)
        return result

    try:
        atomic_write_json(
            APP_DIR / "admin_state" / "diagnostics" / "login_shape.json",
            {"error_type": type(exc).__name__, "diagnostic": storage_shape(diagnostic)},
        )
    except (OSError, TypeError, ValueError):
        # 登录错误本身仍按正常中文错误展示，诊断落盘失败不覆盖原错误。
        return


def configure_tk() -> None:
    """在当前工具自己的 .runtime 解开 Python ZIP 版 Tcl/Tk 资源。"""

    base = Path(sys.base_prefix) / "tcl"
    runtime = APP_DIR / ".runtime"
    for name, marker, variable in (("tcl", "init.tcl", "TCL_LIBRARY"), ("tk", "tk.tcl", "TK_LIBRARY")):
        if variable in os.environ:
            continue
        archives = sorted(base.glob(f"lib{name}*.zip"))
        if not archives:
            continue
        target = runtime / archives[-1].stem
        library = target / f"{name}_library"
        if not (library / marker).is_file():
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archives[-1]) as archive:
                archive.extractall(target)
        if (library / marker).is_file():
            os.environ[variable] = str(library)




def apply_styles(root: Any) -> None:
    """应用级 ttk 样式：表格行高、表头加粗，提升长列表可读性。"""
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=26)
    base = tkfont.nametofont("TkDefaultFont")
    family = base.actual("family")
    size = base.actual("size")
    style.configure("Treeview.Heading", font=(family, size, "bold"))
    style.configure("TLabelframe.Label", font=(family, size, "bold"))
