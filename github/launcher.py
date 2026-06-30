from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Optional

from werkzeug.serving import make_server

from server.app import create_app
from server.config import APP_DISPLAY_NAME, APP_VERSION, resource_dir
from server.data_store import JsonStore
from server.env_check import check_runtime_environment, check_startup_environment, format_environment_report, has_errors
from server.network import get_primary_lan_ip


class ServiceController:
    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self.server = None
        self.thread: Optional[threading.Thread] = None
        self.port = int(self.store.get_config().get("port", 8080))

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, port: int) -> None:
        if self.running:
            raise RuntimeError("服务已经在运行")
        self.port = port
        self.store.set_port(port)
        app = create_app(self.store)
        self.server = make_server("0.0.0.0", port, app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.store.append_audit("launcher", "service_start", str(port))

    def stop(self) -> None:
        if not self.running or self.server is None:
            return
        self.server.shutdown()
        if self.thread:
            self.thread.join(timeout=3)
        self.store.append_audit("launcher", "service_stop", str(self.port))
        self.server = None
        self.thread = None

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def lan_url(self) -> str:
        return f"http://{get_primary_lan_ip()}:{self.port}"


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.store = JsonStore()
        self.service = ServiceController(self.store)
        self.title(f"{APP_DISPLAY_NAME}启动器 {APP_VERSION}")
        self.minsize(920, 620)
        self.geometry("1040x680")
        self.configure(bg="#F4F7FB")
        self._set_window_icon()
        self._setup_styles()
        self._build_layout()
        self._refresh_admins()
        self._refresh_status()
        self.after(700, self._run_environment_check_async)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self) -> None:
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Root.TFrame", background="#F4F7FB")
        style.configure("Panel.TFrame", background="#FFFFFF", borderwidth=0)
        style.configure("Muted.TLabel", background="#FFFFFF", foreground="#64748B")
        style.configure("Title.TLabel", background="#F4F7FB", foreground="#0F172A", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#F4F7FB", foreground="#64748B", font=("Microsoft YaHei UI", 10))
        style.configure("PanelTitle.TLabel", background="#FFFFFF", foreground="#0F172A", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("Value.TLabel", background="#FFFFFF", foreground="#0F766E", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("StatusOn.TLabel", background="#DCFCE7", foreground="#166534", padding=(12, 6), font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("StatusOff.TLabel", background="#FFE4E6", foreground="#9F1239", padding=(12, 6), font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Primary.TButton", background="#0F766E", foreground="#FFFFFF", padding=(18, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#115E59"), ("disabled", "#94A3B8")])
        style.configure("Secondary.TButton", background="#E2E8F0", foreground="#0F172A", padding=(16, 8))
        style.map("Secondary.TButton", background=[("active", "#CBD5E1")])
        style.configure("Danger.TButton", background="#DC2626", foreground="#FFFFFF", padding=(16, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Danger.TButton", background=[("active", "#B91C1C"), ("disabled", "#FCA5A5")])
        style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor="#CBD5E1", padding=7)
        style.configure("TCombobox", fieldbackground="#FFFFFF", bordercolor="#CBD5E1", padding=7)

    def _set_window_icon(self) -> None:
        icon_path = resource_dir() / "assets" / "app-icon.ico"
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

    def _panel(self, parent, row: int, column: int, **grid):
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=22)
        frame.grid(row=row, column=column, sticky="nsew", padx=10, pady=10, **grid)
        return frame

    def _build_layout(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame", padding=24)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, style="Root.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)

        title_block = ttk.Frame(header, style="Root.TFrame")
        title_block.grid(row=0, column=0, sticky="w")
        ttk.Label(title_block, text=APP_DISPLAY_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_block, text="本地 JSON 存储 · 局域网 Web 服务 · PDF / Excel 登记核对", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))

        self.status_label = ttk.Label(header, text="服务未启动", style="StatusOff.TLabel")
        self.status_label.grid(row=0, column=1, sticky="e")

        service_panel = self._panel(root, 1, 0)
        service_panel.columnconfigure(1, weight=1)
        ttk.Label(service_panel, text="服务控制", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(service_panel, text="端口号", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(22, 6))
        self.port_var = tk.StringVar(value=str(self.store.get_config().get("port", 8080)))
        self.port_entry = ttk.Entry(service_panel, textvariable=self.port_var)
        self.port_entry.grid(row=1, column=1, sticky="ew", pady=(22, 6), padx=(12, 0))
        self.save_port_button = ttk.Button(service_panel, text="保存端口", style="Secondary.TButton", command=self._save_port)
        self.save_port_button.grid(row=1, column=2, padx=(12, 0), pady=(22, 6))

        buttons = ttk.Frame(service_panel, style="Panel.TFrame")
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(14, 18))
        self.start_button = ttk.Button(buttons, text="启动服务", style="Primary.TButton", command=self._start_service)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="停止服务", style="Danger.TButton", command=self._stop_service)
        self.stop_button.pack(side="left", padx=(10, 0))
        self.open_button = ttk.Button(buttons, text="打开网页", style="Secondary.TButton", command=self._open_web)
        self.open_button.pack(side="left", padx=(10, 0))
        self.env_button = ttk.Button(buttons, text="环境检测", style="Secondary.TButton", command=lambda: self._run_environment_check(show_success=True))
        self.env_button.pack(side="left", padx=(10, 0))

        ttk.Label(service_panel, text="本机访问", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.local_url_label = ttk.Label(service_panel, text="-", style="Value.TLabel")
        self.local_url_label.grid(row=3, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=(8, 2))
        ttk.Label(service_panel, text="局域网访问", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=2)
        self.lan_url_label = ttk.Label(service_panel, text="-", style="Value.TLabel")
        self.lan_url_label.grid(row=4, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=2)

        notes = tk.Text(service_panel, height=8, wrap="word", relief="flat", bg="#F8FAFC", fg="#475569", padx=14, pady=12)
        notes.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(22, 0))
        notes.insert(
            "1.0",
            "使用说明：启动服务后，财务人员可在同网段电脑浏览器打开局域网地址访问。"
            "如需修改端口，请先停止服务再保存端口。数据文件保存在本程序目录 data 文件夹内。",
        )
        notes.configure(state="disabled")
        service_panel.rowconfigure(5, weight=1)

        admin_panel = self._panel(root, 1, 1)
        admin_panel.columnconfigure(1, weight=1)
        ttk.Label(admin_panel, text="管理员管理", style="PanelTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(admin_panel, text="当前管理员", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(22, 6))
        self.actor_var = tk.StringVar()
        self.actor_combo = ttk.Combobox(admin_panel, textvariable=self.actor_var, state="readonly")
        self.actor_combo.grid(row=1, column=1, sticky="ew", pady=(22, 6), padx=(12, 0))

        ttk.Label(admin_panel, text="当前密码", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.actor_password_var = tk.StringVar()
        ttk.Entry(admin_panel, textvariable=self.actor_password_var, show="*").grid(row=2, column=1, sticky="ew", pady=6, padx=(12, 0))

        ttk.Label(admin_panel, text="目标管理员", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(20, 6))
        self.target_admin_var = tk.StringVar()
        self.target_admin_combo = ttk.Combobox(admin_panel, textvariable=self.target_admin_var)
        self.target_admin_combo.grid(row=3, column=1, sticky="ew", pady=(20, 6), padx=(12, 0))

        ttk.Label(admin_panel, text="新密码", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        self.new_password_var = tk.StringVar()
        ttk.Entry(admin_panel, textvariable=self.new_password_var, show="*").grid(row=4, column=1, sticky="ew", pady=6, padx=(12, 0))

        admin_buttons = ttk.Frame(admin_panel, style="Panel.TFrame")
        admin_buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 14))
        ttk.Button(admin_buttons, text="新增管理员", style="Primary.TButton", command=self._add_admin).pack(side="left")
        ttk.Button(admin_buttons, text="修改密码", style="Secondary.TButton", command=self._change_password).pack(side="left", padx=(10, 0))

        help_text = tk.Text(admin_panel, height=8, wrap="word", relief="flat", bg="#F8FAFC", fg="#475569", padx=14, pady=12)
        help_text.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(18, 0))
        help_text.insert(
            "1.0",
            "初始管理员：管理员1\n初始密码：123456\n\n"
            "新增管理员和修改密码都需要先选择当前管理员并输入当前密码。"
            "建议首次部署后立即修改默认密码。",
        )
        help_text.configure(state="disabled")
        admin_panel.rowconfigure(6, weight=1)

        footer = ttk.Frame(root, style="Root.TFrame")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, text=f"{APP_DISPLAY_NAME} {APP_VERSION}", style="Subtitle.TLabel").grid(row=0, column=0, sticky="w")

    def _parse_port(self) -> int:
        try:
            port = int(self.port_var.get().strip())
        except ValueError as exc:
            raise ValueError("端口号必须是数字") from exc
        if port < 1 or port > 65535:
            raise ValueError("端口号必须在 1 到 65535 之间")
        return port

    def _save_port(self) -> None:
        if self.service.running:
            messagebox.showwarning("端口修改", "请先停止服务，再修改端口。")
            return
        try:
            port = self._parse_port()
            self.store.set_port(port)
            self.service.port = port
            self._refresh_status()
            messagebox.showinfo("端口修改", "端口已保存。")
        except Exception as exc:
            messagebox.showerror("端口修改失败", str(exc))

    def _start_service(self) -> None:
        try:
            issues = check_startup_environment()
            if has_errors(issues):
                messagebox.showerror("启动检查失败", format_environment_report(issues))
                return
            self.service.start(self._parse_port())
            self._refresh_status()
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))

    def _stop_service(self) -> None:
        try:
            self.service.stop()
            self._refresh_status()
        except Exception as exc:
            messagebox.showerror("停止失败", str(exc))

    def _open_web(self) -> None:
        if not self.service.running:
            messagebox.showwarning("服务未启动", "请先启动服务。")
            return
        webbrowser.open(self.service.local_url())

    def _run_environment_check(self, show_success: bool = True) -> bool:
        issues = check_runtime_environment()
        report = format_environment_report(issues)
        if has_errors(issues):
            messagebox.showerror("环境检测失败", report)
            return False
        if show_success or issues:
            messagebox.showinfo("环境检测", report)
        return True

    def _run_environment_check_async(self) -> None:
        threading.Thread(target=self._environment_check_worker, daemon=True).start()

    def _environment_check_worker(self) -> None:
        issues = check_runtime_environment()
        if not has_errors(issues):
            return
        report = format_environment_report(issues)
        try:
            self.after(0, lambda: messagebox.showerror("环境检测失败", report))
        except tk.TclError:
            pass

    def _refresh_admins(self) -> None:
        admins = self.store.list_admins()
        self.actor_combo.configure(values=admins)
        self.target_admin_combo.configure(values=admins)
        if admins:
            self.actor_var.set(admins[0])
            self.target_admin_var.set(admins[0])

    def _admin_inputs(self):
        return (
            self.actor_var.get().strip(),
            self.actor_password_var.get(),
            self.target_admin_var.get().strip(),
            self.new_password_var.get(),
        )

    def _add_admin(self) -> None:
        actor, actor_password, target, new_password = self._admin_inputs()
        try:
            self.store.add_admin(actor, actor_password, target, new_password)
            self._refresh_admins()
            self.new_password_var.set("")
            messagebox.showinfo("新增管理员", "管理员已新增。")
        except Exception as exc:
            messagebox.showerror("新增失败", str(exc))

    def _change_password(self) -> None:
        actor, actor_password, target, new_password = self._admin_inputs()
        try:
            self.store.change_admin_password(actor, actor_password, target, new_password)
            self.new_password_var.set("")
            messagebox.showinfo("修改密码", "密码已修改。")
        except Exception as exc:
            messagebox.showerror("修改失败", str(exc))

    def _refresh_status(self) -> None:
        self.service.port = int(self.store.get_config().get("port", 8080))
        running = self.service.running
        self.status_label.configure(text="服务运行中" if running else "服务未启动", style="StatusOn.TLabel" if running else "StatusOff.TLabel")
        self.local_url_label.configure(text=self.service.local_url())
        self.lan_url_label.configure(text=self.service.lan_url())
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.open_button.configure(state="normal" if running else "disabled")
        self.save_port_button.configure(state="disabled" if running else "normal")

    def _on_close(self) -> None:
        if self.service.running:
            if not messagebox.askyesno("退出", "服务正在运行，退出会停止服务。确认退出？"):
                return
            self.service.stop()
        self.destroy()


def main() -> None:
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
