"""PlayerMaintenanceApp 的后台登录对话框。"""

from __future__ import annotations

from PIL import Image
from PIL import ImageTk
import base64
from io import BytesIO
import threading
from tkinter import StringVar
from tkinter import Toplevel
from tkinter import messagebox
from tkinter import ttk
from typing import Optional
from 球员维护工具.adapters import LoginRequest
import sys
from pathlib import Path

if __package__:
    from .login_dialog import AdminLoginController, _save_login_shape_diagnostic
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.login_dialog import AdminLoginController, _save_login_shape_diagnostic

class LoginMixin:
    def _backend_login(self) -> None:
        """打开内存登录表单；没有注入真实适配器时不发起网络请求。"""

        if isinstance(self.backend_login_handler, AdminLoginController):
            self.status_var.set("正在获取验证码…")

            def worker() -> None:
                try:
                    captcha = self.backend_login_handler.prepare_captcha()
                    self.events.put(("captcha_ready", captcha))
                except Exception as exc:
                    self.events.put(("captcha_error", str(exc)))

            threading.Thread(target=worker, name="fc27-captcha", daemon=True).start()
            return
        self._show_login_dialog(None)

    def _show_login_dialog(self, captcha_bytes: Optional[bytes]) -> None:
        login_window = Toplevel(self.root)
        login_window.title("后台登录")
        login_window.resizable(False, False)
        login_window.transient(self.root)
        login_window.grab_set()
        username_var = StringVar()
        password_var = StringVar()
        captcha_var = StringVar()
        fields = (("账号", username_var, ""), ("密码", password_var, "*"), ("验证码", captcha_var, ""))
        for row, (label, variable, show) in enumerate(fields):
            ttk.Label(login_window, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=6)
            ttk.Entry(login_window, textvariable=variable, show=show, width=32).grid(row=row, column=1, padx=10, pady=6)
        captcha_image = None
        if captcha_bytes:
            try:
                try:
                    from io import BytesIO
                    from PIL import Image, ImageTk

                    captcha_image = ImageTk.PhotoImage(Image.open(BytesIO(captcha_bytes)))
                except Exception:
                    captcha_image = __import__("tkinter").PhotoImage(data=base64.b64encode(captcha_bytes).decode("ascii"))
                captcha_label = ttk.Label(login_window, image=captcha_image)
                captcha_label.image = captcha_image
                captcha_label.grid(row=2, column=2, padx=6, pady=6)
            except Exception:
                ttk.Label(login_window, text="验证码图片无法显示，请重新获取").grid(row=2, column=2, padx=6, pady=6)

        login_button = ttk.Button(login_window, text="登录")

        def submit() -> None:
            username = username_var.get().strip()
            password = password_var.get()
            captcha = captcha_var.get().strip()
            if not username or not password:
                messagebox.showwarning("后台登录", "账号和密码不能为空", parent=login_window)
                return
            login_button.configure(state="disabled")
            request = LoginRequest(username, password, captcha, getattr(self.backend_login_handler, "captcha_id", ""))
            password_var.set("")

            def worker() -> None:
                try:
                    session = self.backend_login_handler.login(request)
                    self.events.put(("login_success", (session, login_window)))
                except Exception as exc:
                    _save_login_shape_diagnostic(exc)
                    self.events.put(("login_error", (str(exc), login_window)))

            threading.Thread(target=worker, name="fc27-admin-login", daemon=True).start()

        login_button.configure(command=submit)
        login_button.grid(row=3, column=0, columnspan=2, pady=(4, 10))
        login_window.protocol("WM_DELETE_WINDOW", login_window.destroy)


