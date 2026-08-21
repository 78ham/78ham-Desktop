"""
配置对话框组件

配置文件的新建、编辑、加载功能。
从 gui_client_ctk.py 的 new_config/edit_config 方法提取。
"""
import customtkinter as ctk
from tkinter import filedialog, messagebox
from typing import Optional, Callable, Dict, List

from core.protocol import is_valid_callsign
from ui.theme import Fonts, Spacing

try:
    import yaml
except ImportError:
    yaml = None


class ConfigDialog(ctk.CTkToplevel):
    """配置编辑对话框

    支持新建和编辑模式。
    保存后通过回调通知主窗口。
    """

    def __init__(self, master,
                 initial_data: Optional[Dict] = None,
                 on_save: Optional[Callable[[str, Dict], None]] = None,
                 **kwargs):
        """
        Args:
            master: 父窗口
            initial_data: 编辑模式时的现有配置数据
            on_save: 保存回调 (filename, config_dict)
        """
        super().__init__(master, **kwargs)

        self._initial_data = initial_data or {}
        self._is_edit = bool(initial_data)
        self._on_save = on_save
        self._server_entries: List[Dict] = []
        self._server_vars: List[Dict[str, ctk.StringVar]] = []

        title = "编辑配置" if self._is_edit else "新建配置"
        self.title(title)
        self.geometry("650x700")
        self.transient(master)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # 主滚动区域
        self._scroll_frame = ctk.CTkScrollableFrame(self)
        self._scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_device_section()
        self._build_server_section()
        self._build_network_section()
        self._build_buttons()
    
    def _build_device_section(self):
        """设备配置区"""
        dev_data = self._initial_data.get('device', {})
        
        frame = ctk.CTkFrame(self._scroll_frame)
        frame.pack(fill="x", pady=Spacing.PAD_SM)
        
        ctk.CTkLabel(frame, text="设备配置",
                     font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold")
                     ).pack(anchor="w", padx=Spacing.PAD_SM, pady=(Spacing.PAD_XS, 0))
        
        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
        
        # 呼号
        ctk.CTkLabel(grid, text="呼号:").grid(row=0, column=0, sticky="w", pady=3)
        self._callsign_var = ctk.StringVar(value=dev_data.get('callsign', 'BH6XXX'))
        ctk.CTkEntry(grid, textvariable=self._callsign_var, width=150).grid(
            row=0, column=1, sticky="w", padx=5, pady=3)

        # SSID
        ctk.CTkLabel(grid, text="SSID:").grid(row=1, column=0, sticky="w", pady=3)
        self._ssid_var = ctk.StringVar(value=str(dev_data.get('ssid', 1)))
        ctk.CTkEntry(grid, textvariable=self._ssid_var, width=80).grid(
            row=1, column=1, sticky="w", padx=5, pady=3)

        # DMRID
        ctk.CTkLabel(grid, text="DMRID:").grid(row=2, column=0, sticky="w", pady=3)
        self._dmrid_var = ctk.StringVar(value=dev_data.get('dmr_id', '123456'))
        ctk.CTkEntry(grid, textvariable=self._dmrid_var, width=150).grid(
            row=2, column=1, sticky="w", padx=5, pady=3)

        # 设备密码
        ctk.CTkLabel(grid, text="设备密码:").grid(row=3, column=0, sticky="w", pady=3)
        self._password_var = ctk.StringVar(value=dev_data.get('password', ''))
        ctk.CTkEntry(grid, textvariable=self._password_var, width=150, show="*").grid(
            row=3, column=1, sticky="w", padx=5, pady=3)

    def _build_server_section(self):
        """服务器列表区"""
        servers_data = self._initial_data.get('servers', [
            {'name': '示例服务器', 'host': '', 'port': 60050, 'password': ''}
        ])

        frame = ctk.CTkFrame(self._scroll_frame)
        frame.pack(fill="x", pady=Spacing.PAD_SM)

        ctk.CTkLabel(frame, text="服务器列表",
                     font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold")
                     ).pack(anchor="w", padx=Spacing.PAD_SM, pady=(Spacing.PAD_XS, 0))

        # 填充初始数据
        for srv in servers_data:
            self._server_entries.append(srv.copy())
        self._server_form = ctk.CTkFrame(frame, fg_color="transparent")
        self._server_form.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
        self._refresh_server_display()

        # 按钮行
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=(0, Spacing.PAD_XS))

        ctk.CTkButton(btn_frame, text="添加", width=60,
                      command=self._add_server).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="删除末尾", width=70,
                      command=self._remove_last_server).pack(side="left", padx=2)

    def _build_network_section(self):
        """网络配置区"""
        net_data = self._initial_data.get('network', {})

        frame = ctk.CTkFrame(self._scroll_frame)
        frame.pack(fill="x", pady=Spacing.PAD_SM)

        ctk.CTkLabel(frame, text="网络配置",
                     font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold")
                     ).pack(anchor="w", padx=Spacing.PAD_SM, pady=(Spacing.PAD_XS, 0))

        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(grid, text="心跳间隔(秒):").grid(row=0, column=0, sticky="w", pady=3)
        self._heartbeat_var = ctk.StringVar(value=str(net_data.get('heartbeat_interval', 2)))
        ctk.CTkEntry(grid, textvariable=self._heartbeat_var, width=80).grid(
            row=0, column=1, sticky="w", padx=5, pady=3)

        ctk.CTkLabel(grid, text="缓冲区:").grid(row=0, column=2, sticky="w", padx=(15, 0), pady=3)
        self._buffer_var = ctk.StringVar(value=str(net_data.get('buffer_size', 4096)))
        ctk.CTkEntry(grid, textvariable=self._buffer_var, width=80).grid(
            row=0, column=3, sticky="w", padx=5, pady=3)

    def _build_buttons(self):
        """底部按钮"""
        btn_frame = ctk.CTkFrame(self._scroll_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=Spacing.PAD_MD)

        ctk.CTkButton(btn_frame, text="保存", width=100,
                      command=self._do_save).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="取消", width=80,
                      fg_color="gray",
                      command=self.destroy).pack(side="right", padx=5)

    # ==================== 内部方法 ====================

    def _refresh_server_display(self):
        """刷新可编辑的服务器列表。"""
        for child in self._server_form.winfo_children():
            child.destroy()
        self._server_vars = []
        headers = ("名称", "UDP主机", "UDP端口", "API地址", "账号", "Web密码")
        for column, header in enumerate(headers):
            ctk.CTkLabel(self._server_form, text=header).grid(
                row=0, column=column, padx=2, pady=(0, 3), sticky="w")
        widths = (100, 125, 65, 180, 100, 100)
        keys = ("name", "host", "port", "api_url", "username", "api_password")
        for row, server in enumerate(self._server_entries, start=1):
            variables = {}
            for column, (key, width) in enumerate(zip(keys, widths)):
                value = server.get(key, '')
                if key == 'port' and not value:
                    value = 60050
                variables[key] = ctk.StringVar(value=str(value))
                ctk.CTkEntry(
                    self._server_form,
                    textvariable=variables[key],
                    width=width,
                    show="*" if key == "api_password" else None,
                ).grid(row=row, column=column, padx=2, pady=2, sticky="ew")
            self._server_vars.append(variables)

    def _add_server(self):
        """添加服务器"""
        self._server_entries.append({
            'name': '新服务器', 'host': '', 'port': 60050,
            'api_url': '', 'username': '', 'api_password': '',
        })
        self._refresh_server_display()

    def _remove_last_server(self):
        """删除最后一个服务器"""
        if self._server_entries:
            self._server_entries.pop()
            self._refresh_server_display()

    def _do_save(self):
        """保存配置"""
        callsign = self._callsign_var.get().strip()
        callsign = callsign.upper()
        if not is_valid_callsign(callsign):
            messagebox.showerror("错误", "呼号须为 1-6 位大写字母或数字", parent=self)
            return
        if not self._server_entries:
            messagebox.showerror("错误", "请至少添加一个服务器", parent=self)
            return

        try:
            ssid = int(self._ssid_var.get() or 1)
            if not (0 <= ssid <= 15):
                messagebox.showerror("错误", "SSID 范围：0-15", parent=self)
                return
            heartbeat_interval = int(self._heartbeat_var.get() or 2)
            buffer_size = int(self._buffer_var.get() or 4096)
            if not (48 <= buffer_size <= 65535):
                raise ValueError
            if heartbeat_interval < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "数值字段无效或超出范围", parent=self)
            return

        servers = []
        for variables in self._server_vars:
            try:
                port = int(variables['port'].get() or 60050)
                if not 1 <= port <= 65535:
                    raise ValueError
            except ValueError:
                messagebox.showerror("错误", "服务器 UDP 端口无效", parent=self)
                return
            server = {key: variables[key].get().strip() for key in variables}
            server['port'] = port
            servers.append(server)

        config_data = {
            'device': {
                'callsign': callsign,
                'ssid': ssid,
                'dmr_id': self._dmrid_var.get(),
                'password': self._password_var.get(),
            },
            'servers': servers,
            'current_server': self._initial_data.get('current_server', 0),
            'platform_url': self._initial_data.get('platform_url', 'https://nrlptt.com'),
            'network': {
                'heartbeat_interval': heartbeat_interval,
                'buffer_size': buffer_size,
            },
        }

        if self._is_edit:
            # 编辑模式：直接回调
            if self._on_save:
                self._on_save("", config_data)
            self.destroy()
            return

        # 新建模式：选择保存路径
        filename = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
            initialfile="config.yaml",
        )
        if not filename:
            return

        if yaml:
            with open(filename, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
        else:
            messagebox.showerror("错误", "yaml 库未安装", parent=self)
            return

        if self._on_save:
            self._on_save(filename, config_data)
        self.destroy()
