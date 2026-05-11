"""
78HAM客户端GUI界面 (CustomTkinter版本)
提供图形化界面操作客户端
"""
import customtkinter as ctk
from tkinter import messagebox, filedialog
import sys
import threading
import time
import logging
import os
import yaml #type: ignore
import shutil
from typing import Dict, Any, Optional

from nrl_client import NRLClient, get_os_display_name
from nrl_protocol import OpusCodec

# 设置CustomTkinter外观
ctk.set_appearance_mode("dark")  # "light" or "dark"
ctk.set_default_color_theme("blue")  # "blue", "green", "dark-blue"


class NRLGUIClient:
    """78HAM客户端GUI类 (CustomTkinter版本)"""
    
    def __init__(self):
        # 设置窗口
        self.root = ctk.CTk()
        self.root.title("78HAM Desktop 客户端")
        
        # 设置窗口图标（兼容 PyInstaller 打包后路径）
        try:
            if getattr(sys, 'frozen', False):
                ico_path = os.path.join(sys._MEIPASS, 'app.ico')
            else:
                ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.ico')
            if os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
        except Exception:
            pass
        
        # 根据操作系统设置窗口大小
        self.system_kind = os.name
        self.root.geometry({"nt": "850x650", "posix": "850x750"}.get(self.system_kind, "850x700"))
        
        # 客户端
        self.client = None
        
        # UI组件
        self.main_frame = None
        self.status_frame = None
        self.control_frame = None
        self.log_frame = None
        self.audio_frame = None
        
        # 状态变量
        self.connection_status = ctk.StringVar(value="未连接")
        self.device_info = ctk.StringVar(value="正在获取...")
        self.audio_level = ctk.DoubleVar(value=0.0)
        self.ptt_active = ctk.BooleanVar(value=False)
        # 播放状态
        self.is_playing = False
        # 发射编码格式
        self.codec_var = ctk.StringVar(value="g711")
        
        # 定时器
        self.update_timer = None
        
        # 服务器列表
        self.servers_list = []
        self.current_server_var = ctk.StringVar(value="")
        
        # 配置文件管理
        self.current_config_file = ctk.StringVar(value="config.yaml")
        self.config_history = []
        
        # 日志
        self.setup_logging()
        
        # 初始化UI
        self.setup_ui()
        
    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 创建日志处理器用于GUI显示
        self.log_handler = GUILogHandler(self.log_message, self.root)
        self.log_handler.setLevel(logging.INFO)
        
        # 获取根日志记录器
        root_logger = logging.getLogger()
        root_logger.addHandler(self.log_handler)
    
    def setup_ui(self):
        """设置UI界面"""
        # 创建主框架
        self.main_frame = ctk.CTkFrame(self.root)
        self.main_frame.grid(row=0, column=0, sticky=(ctk.W, ctk.E, ctk.N, ctk.S), padx=10, pady=10)
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(3, weight=1)  # 日志区域占用剩余空间)
        
        # 状态栏
        self.create_status_frame()
        
        # 控制面板
        self.create_control_frame()
        
        # 音频控制
        self.create_audio_frame()
        
        # 日志区域
        self.create_log_frame()
        
        # 底部状态栏
        self.create_bottom_status_bar()
        
        # 菜单
        self.create_menu()
        
        # 启动实时状态更新（时间等）
        self.start_status_update()
    
    def create_status_frame(self):
        """创建状态栏"""
        self.status_frame = ctk.CTkFrame(self.main_frame)
        self.status_frame.grid(row=0, column=0, sticky=(ctk.W, ctk.E), pady=(0, 10), padx=(0, 0))
        
        # 标题
        status_title = ctk.CTkLabel(self.status_frame, text="状态", font=("Arial", 14, "bold"))
        status_title.grid(row=0, column=0, columnspan=6, sticky="w", padx=15, pady=(8, 8))
        
        # 内容行 - 使用统一的间距和对齐
        content_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        content_frame.grid(row=1, column=0, columnspan=6, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 8))
        
        # 连接状态
        ctk.CTkLabel(content_frame, text="连接状态:").grid(row=0, column=0, sticky=ctk.W, padx=(0, 5))
        status_label = ctk.CTkLabel(content_frame, textvariable=self.connection_status, 
                                   font=('Arial', 11, 'bold'))
        status_label.grid(row=0, column=1, sticky=ctk.W, padx=(0, 20))
        
        # 设备信息 - 分开显示各个字段
        ctk.CTkLabel(content_frame, text="呼号:").grid(row=0, column=2, sticky=ctk.W, padx=(0, 3))
        self.callsign_value_label = ctk.CTkLabel(content_frame, text="(未配置)", font=('Arial', 11))
        self.callsign_value_label.grid(row=0, column=3, sticky=ctk.W, padx=(0, 15))
        
        ctk.CTkLabel(content_frame, text="SSID:").grid(row=0, column=4, sticky=ctk.W, padx=(0, 3))
        self.ssid_value_label = ctk.CTkLabel(content_frame, text="1", font=('Arial', 11))
        self.ssid_value_label.grid(row=0, column=5, sticky=ctk.W, padx=(0, 15))
        
        ctk.CTkLabel(content_frame, text="DMRID:").grid(row=0, column=6, sticky=ctk.W, padx=(0, 3))
        self.dmr_id_value_label = ctk.CTkLabel(content_frame, text="(未配置)", font=('Arial', 11))
        self.dmr_id_value_label.grid(row=0, column=7, sticky=ctk.W, padx=(0, 15))

        # 操作系统
        ctk.CTkLabel(content_frame, text="操作系统:").grid(row=0, column=8, sticky=ctk.W, padx=(0, 3))
        os_label = ctk.CTkLabel(content_frame, text=get_os_display_name(), font=('Arial', 11, 'bold'))
        os_label.grid(row=0, column=9, sticky=ctk.W, padx=(0, 0))
    
    def create_control_frame(self):
        """创建控制面板"""
        self.control_frame = ctk.CTkFrame(self.main_frame)
        self.control_frame.grid(row=1, column=0, sticky=(ctk.W, ctk.E), pady=(0, 10), padx=(0, 0))
        self.control_frame.grid_columnconfigure(0, weight=1)
        
        # 标题
        control_title = ctk.CTkLabel(self.control_frame, text="控制", font=("Arial", 14, "bold"))
        control_title.grid(row=0, column=0, sticky="w", padx=15, pady=(8, 8))
        
        # 服务器选择行
        server_frame = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        server_frame.grid(row=1, column=0, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 10))
        server_frame.grid_columnconfigure(1, weight=1)  # 下拉框可伸展
        
        ctk.CTkLabel(server_frame, text="服务器:").grid(row=0, column=0, sticky=ctk.W, padx=(0, 8))
        self.server_combo = ctk.CTkComboBox(server_frame, variable=self.current_server_var,
                                           state="readonly")
        self.server_combo.grid(row=0, column=1, padx=(0, 15), sticky=(ctk.W, ctk.E))
        self.server_combo.bind("<Configure>", self.on_server_changed)
        
        # 连接按钮
        self.connect_button = ctk.CTkButton(server_frame, text="连接", 
                                          command=self.connect_to_server, width=90)
        self.connect_button.grid(row=0, column=2, padx=(0, 5))
        
        self.disconnect_button = ctk.CTkButton(server_frame, text="断开", 
                                            command=self.disconnect_from_server,
                                            state=ctk.DISABLED, width=90)
        self.disconnect_button.grid(row=0, column=3, padx=(0, 0))
        
        # 调试模式变量（菜单中控制）
        self.debug_force_decode_var = ctk.BooleanVar(value=False)
        
        # 消息发送行
        message_frame = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        message_frame.grid(row=2, column=0, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 10))
        message_frame.grid_columnconfigure(1, weight=1)  # 输入框可伸展
        
        ctk.CTkLabel(message_frame, text="消息:").grid(row=0, column=0, sticky=ctk.W, padx=(0, 8))
        self.message_entry = ctk.CTkEntry(message_frame, placeholder_text="输入要发送的消息...")
        self.message_entry.grid(row=0, column=1, sticky=(ctk.W, ctk.E), padx=(0, 10))
        
        self.send_message_button = ctk.CTkButton(message_frame, text="发送", 
                                               command=self.send_text_message,
                                               state=ctk.DISABLED, width=80)
        self.send_message_button.grid(row=0, column=2, padx=(0, 5))
        
        self.send_location_button = ctk.CTkButton(message_frame, text="📍发送位置",
                                                   command=self.send_location,
                                                   state=ctk.DISABLED, width=100)
        self.send_location_button.grid(row=0, column=3, padx=(0, 0))
        
        # 房间选择行
        room_frame = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        room_frame.grid(row=3, column=0, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 10))
        room_frame.grid_columnconfigure(1, weight=1)  # 下拉框可伸展
        
        ctk.CTkLabel(room_frame, text="房间:").grid(row=0, column=0, sticky=ctk.W, padx=(0, 8))
        self.room_var = ctk.StringVar(value="公共大厅 (0)")
        self.room_combo = ctk.CTkComboBox(room_frame, variable=self.room_var,
                                          values=["公共大厅 (0)"], state="readonly")
        self.room_combo.grid(row=0, column=1, padx=(0, 15), sticky=(ctk.W, ctk.E))
        
        self.refresh_rooms_button = ctk.CTkButton(room_frame, text="刷新房间列表",
                                                   command=self.refresh_room_list,
                                                   state=ctk.DISABLED, width=110)
        self.refresh_rooms_button.grid(row=0, column=2, padx=(0, 5))
        
        self.join_room_button = ctk.CTkButton(room_frame, text="加入房间",
                                               command=self.join_selected_room,
                                               state=ctk.DISABLED, width=90)
        self.join_room_button.grid(row=0, column=3, padx=(0, 0))
    
    def create_audio_frame(self):
        """创建音频控制面板"""
        self.audio_frame = ctk.CTkFrame(self.main_frame)
        self.audio_frame.grid(row=2, column=0, sticky=(ctk.W, ctk.E), pady=(0, 10), padx=(0, 0))
        self.audio_frame.grid_columnconfigure(0, weight=1)
        
        # 标题
        audio_title = ctk.CTkLabel(self.audio_frame, text="音频控制", font=("Arial", 14, "bold"))
        audio_title.grid(row=0, column=0, sticky="w", padx=15, pady=(8, 8))
        
        # 设备选择行
        device_frame = ctk.CTkFrame(self.audio_frame, fg_color="transparent")
        device_frame.grid(row=1, column=0, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 10))
        device_frame.grid_columnconfigure((1, 3), weight=1)  # 两个下拉框均可伸展
        
        # 输入设备
        ctk.CTkLabel(device_frame, text="输入设备:").grid(row=0, column=0, sticky=ctk.W, padx=(0, 8))
        self.input_device_var = ctk.StringVar()
        self.input_device_combo = ctk.CTkComboBox(device_frame, variable=self.input_device_var,
                                                state="readonly")
        self.input_device_combo.grid(row=0, column=1, sticky=(ctk.W, ctk.E), padx=(0, 15))
        
        # 输出设备
        ctk.CTkLabel(device_frame, text="输出设备:").grid(row=0, column=2, sticky=ctk.W, padx=(0, 8))
        self.output_device_var = ctk.StringVar()
        self.output_device_combo = ctk.CTkComboBox(device_frame, variable=self.output_device_var,
                                                 state="readonly")
        self.output_device_combo.grid(row=0, column=3, sticky=(ctk.W, ctk.E), padx=(0, 15))
        
        # 刷新按钮
        ctk.CTkButton(device_frame, text="刷新设备", 
                     command=self.refresh_audio_devices, width=90).grid(row=0, column=4, padx=(0, 15))
        
        # 发射编码格式
        codec_values = ["G.711 (8kHz)", "Opus (16kHz)"]
        if not OpusCodec.is_available():
            codec_values = ["G.711 (8kHz)"]
        
        ctk.CTkLabel(device_frame, text="发射编码:").grid(row=0, column=5, sticky=ctk.W, padx=(0, 8))
        self.codec_combo = ctk.CTkComboBox(device_frame, variable=self.codec_var,
                                           values=codec_values, state="readonly", width=140,
                                           command=self.on_codec_changed)
        self.codec_combo.grid(row=0, column=6, sticky=ctk.W)
        
        # 根据当前配置设置初始值
        if self.client and self.client.audio_config:
            if self.client.audio_config.codec == 'opus':
                self.codec_var.set("Opus (16kHz)")
            else:
                self.codec_var.set("G.711 (8kHz)")
        
        # PTT控制行
        ptt_frame = ctk.CTkFrame(self.audio_frame, fg_color="transparent")
        ptt_frame.grid(row=2, column=0, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 10))
        
        self.ptt_button = ctk.CTkButton(ptt_frame, text="按住说话 (PTT)", 
                                      command=self.toggle_ptt, width=150, height=40)
        self.ptt_button.pack(side=ctk.LEFT, padx=(0, 20))
        
        # PTT状态指示
        self.ptt_status_label = ctk.CTkLabel(ptt_frame, text="PTT: 未激活", 
                                           font=('Arial', 12, 'bold'))
        self.ptt_status_label.pack(side=ctk.LEFT, padx=(0, 30))
        
        # 播放按钮
        self.play_toggle_button = ctk.CTkButton(ptt_frame, text="开始播放", 
                              command=self.toggle_playback, width=120, height=40)
        self.play_toggle_button.pack(side=ctk.LEFT, padx=(0, 0))
        
        # 音频缓冲区监控（PTT行右侧）
        self.buffer_status_label = ctk.CTkLabel(
            ptt_frame, text="缓冲: -",
            font=('Consolas', 11), text_color="gray"
        )
        self.buffer_status_label.pack(side=ctk.RIGHT, padx=(0, 5))
    
    def create_log_frame(self):
        """创建日志区域"""
        self.log_frame = ctk.CTkFrame(self.main_frame)
        self.log_frame.grid(row=3, column=0, sticky=(ctk.W, ctk.E, ctk.N, ctk.S), pady=(0, 10), padx=(0, 0))
        self.log_frame.grid_rowconfigure(1, weight=1)  # 日志文本框占据剩余空间
        self.log_frame.grid_columnconfigure(0, weight=1)
        
        # 标题
        log_title = ctk.CTkLabel(self.log_frame, text="日志", font=("Arial", 14, "bold"))
        log_title.grid(row=0, column=0, sticky="w", padx=15, pady=(8, 8))
        
        # 日志文本框
        self.log_text = ctk.CTkTextbox(self.log_frame, wrap=ctk.WORD)
        self.log_text.grid(row=1, column=0, sticky=(ctk.W, ctk.E, ctk.N, ctk.S), padx=15, pady=(0, 8))
        
        # 日志控制行
        log_control_frame = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        log_control_frame.grid(row=2, column=0, sticky=(ctk.W, ctk.E), padx=15, pady=(0, 8))
        
        ctk.CTkLabel(log_control_frame, text="日志级别:").pack(side=ctk.LEFT, padx=(0, 8))
        self.log_level_var = ctk.StringVar(value="INFO")
        log_level_combo = ctk.CTkComboBox(log_control_frame, variable=self.log_level_var,
                                       values=["DEBUG", "INFO", "WARNING", "ERROR"],
                                       state="readonly", width=100)
        log_level_combo.pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkButton(log_control_frame, text="清空日志", 
                     command=self.clear_log, width=90).pack(side=ctk.RIGHT, padx=(0, 0))
    
    def create_bottom_status_bar(self):
        """创建底部状态栏"""
        # 创建底部状态栏框架
        bottom_frame = ctk.CTkFrame(self.root, fg_color="#2b2b2b", height=45)
        bottom_frame.grid(row=1, column=0, sticky=(ctk.W, ctk.E), padx=10, pady=(5, 10))
        bottom_frame.grid_propagate(False)
        
        # 使用 pack 布局，左侧用 LEFT，右侧用 LEFT（整体 RIGHT 对齐）
        # 左侧区域
        left_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        left_frame.pack(side=ctk.LEFT, fill=ctk.X, expand=True, padx=(15, 0), pady=8)
        
        ctk.CTkLabel(left_frame, text="呼号-SSID:", font=('Arial', 10), text_color="gray").pack(side=ctk.LEFT, padx=(0, 5))
        self.callsign_ssid_label = ctk.CTkLabel(left_frame, text="未连接", font=('Arial', 12, 'bold'))
        self.callsign_ssid_label.pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(left_frame, text="•", font=('Arial', 14), text_color="gray").pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(left_frame, text="服务器:", font=('Arial', 10), text_color="gray").pack(side=ctk.LEFT, padx=(0, 5))
        self.server_name_label = ctk.CTkLabel(left_frame, text="未连接", font=('Arial', 12))
        self.server_name_label.pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(left_frame, text="•", font=('Arial', 14), text_color="gray").pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(left_frame, text="包数:", font=('Arial', 10), text_color="gray").pack(side=ctk.LEFT, padx=(0, 5))
        self.packet_count_label = ctk.CTkLabel(left_frame, text="↑0 ↓0", font=('Arial', 11))
        self.packet_count_label.pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(left_frame, text="•", font=('Arial', 14), text_color="gray").pack(side=ctk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(left_frame, text="房间:", font=('Arial', 10), text_color="gray").pack(side=ctk.LEFT, padx=(0, 5))
        self.room_label = ctk.CTkLabel(left_frame, text="0-公共大厅", font=('Arial', 11))
        self.room_label.pack(side=ctk.LEFT)
        
        # 右侧区域 — 全部用 side=LEFT 按自然顺序排列
        right_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        right_frame.pack(side=ctk.RIGHT, padx=(0, 15), pady=8)

        ctk.CTkLabel(right_frame, text="当前时间:", font=('Arial', 10), text_color="gray").pack(side=ctk.LEFT, padx=(0, 5))
        self.current_time_label = ctk.CTkLabel(right_frame, text="--:--:--", font=('Arial', 11))
        self.current_time_label.pack(side=ctk.LEFT, padx=(0, 15))
        
        ctk.CTkLabel(right_frame, text="•", font=('Arial', 14), text_color="gray").pack(side=ctk.LEFT, padx=(0, 15))
        
        self.debug_status_label = ctk.CTkLabel(right_frame, text="调试:关闭", font=('Arial', 11),
                                            text_color="gray")
        self.debug_status_label.pack(side=ctk.LEFT, padx=(0, 15))
        
        ctk.CTkLabel(right_frame, text="•", font=('Arial', 14), text_color="gray").pack(side=ctk.LEFT, padx=(0, 15))
        
        self.bottom_connection_status = ctk.CTkLabel(right_frame, text="离线", font=('Arial', 12, 'bold'),
                                                   text_color="#ff5555")
        self.bottom_connection_status.pack(side=ctk.LEFT, padx=(0, 0))
    
    def create_menu(self):
        """创建菜单 - CustomTkinter没有内置菜单，保留tkinter菜单"""
        # 由于CustomTkinter不提供菜单栏，将使用tkinter的菜单系统
        import tkinter as tk
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="新建配置", command=self.new_config)
        file_menu.add_command(label="编辑配置", command=self.edit_config)
        file_menu.add_command(label="加载配置", command=self.load_config)
        file_menu.add_command(label="配置管理器", command=self.show_config_manager)
        
        # 最近使用的配置
        self.recent_configs_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="最近使用的配置", menu=self.recent_configs_menu)
        self.update_recent_configs_menu()
        
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_closing)
        
        # 工具菜单（包含调试开关）
        self.tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="工具", menu=self.tools_menu)
        self.tools_menu.add_command(label="音频设备测试", command=self.test_audio_devices)
        self.tools_menu.add_command(label="网络测试", command=self.test_network)
        self.tools_menu.add_separator()
        # 调试开关：强制解码空包（在菜单中控制）
        self.tools_menu.add_checkbutton(label="[调试]强制解码空包", 
                        variable=self.debug_force_decode_var,
                        onvalue=True, offvalue=False,
                        command=self.menu_toggle_debug)
        #配置菜单
        self.config_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="配置", menu=self.config_menu)
        self.config_menu.add_command(label="配置总览", command=self.show_device_config)
        
        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="关于", command=self.show_about)
    
    def log_message(self, message: str):
        """记录消息到日志区域"""
        if self.log_text:
            self.log_text.insert(ctk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
            self.log_text.see(ctk.END)
    
    def _auto_refresh_room_list(self):
        """连接成功后自动刷新房间列表"""
        if self.client and self.client.is_connected:
            self.refresh_room_list()
    
    def refresh_room_list(self):
        """刷新房间列表"""
        if not self.client or not self.client.is_connected:
            self.log_message("未连接到服务器，无法刷新房间列表")
            return
        if self.client.request_group_list():
            self.log_message("已发送房间列表请求...")
        else:
            self.log_message("发送房间列表请求失败")
    
    def join_selected_room(self):
        """加入选中的房间"""
        if not self.client or not self.client.is_connected:
            self.log_message("未连接到服务器，无法切换房间")
            return
        selected = self.room_var.get()
        # 从 "房间名 (ID)" 格式中提取 ID
        try:
            group_id = int(selected.split("(")[-1].rstrip(")"))
        except (ValueError, IndexError):
            self.log_message(f"无法解析房间ID: {selected}")
            return
        if self.client.join_group(group_id):
            self.log_message(f"正在加入房间: {group_id}...")
        else:
            self.log_message(f"发送加入房间请求失败")
    
    def on_group_list_updated(self, group_list: list):
        """房间列表更新回调（从接收线程调用，需切换到主线程）"""
        self.root.after(0, self._update_room_list_ui, group_list)
    
    def _update_room_list_ui(self, group_list: list):
        """在主线程中更新房间下拉框"""
        if not group_list:
            self.log_message("房间列表为空")
            return
        room_values = [f"{g['name']} ({g['id']})" for g in group_list]
        self.room_combo.configure(values=room_values)
        # 保持选中当前房间
        current_text = f"{self.client.current_group_name} ({self.client.current_group_id})"
        if current_text in room_values:
            self.room_var.set(current_text)
        else:
            self.room_var.set(room_values[0])
        self.log_message(f"房间列表已更新: 共 {len(group_list)} 个房间")
    
    def on_group_changed(self, group_id: int, group_name: str):
        """房间切换结果回调（从接收线程调用，需切换到主线程）"""
        self.root.after(0, self._update_room_change_ui, group_id, group_name)
    
    def _update_room_change_ui(self, group_id: int, group_name: str):
        """在主线程中更新房间切换结果"""
        if group_id < 0 or group_name == "error":
            self.log_message("加入房间失败: 服务器拒绝（可能无权限或房间不存在）")
            return
        self.room_label.configure(text=f"{group_id}-{group_name}")
        self.room_var.set(f"{group_name} ({group_id})")
        self.log_message(f"已切换到房间: {group_id}-{group_name}")
    
    def connect_to_server(self):
        """连接到服务器"""
        try:
            if not self.client:
                config_file = self.current_config_file.get()
                self.client = NRLClient(config_file)
                
                # 设置回调
                self.client.set_message_callback(self.on_message_received)
                self.client.set_voice_callback(self.on_voice_received)
                self.client.set_status_callback(self.on_status_changed)
                self.client.group_list_callback = self.on_group_list_updated
                self.client.group_change_callback = self.on_group_changed
                
                # 同步发射编码下拉框
                if self.client.audio_config.codec == 'opus':
                    self.codec_var.set("Opus (16kHz)")
                else:
                    self.codec_var.set("G.711 (8kHz)")
            
            if self.client.connect():
                self.connection_status.set("已连接")
                self.connect_button.configure(state=ctk.DISABLED)
                self.disconnect_button.configure(state=ctk.NORMAL)
                self.send_message_button.configure(state=ctk.NORMAL)
                self.refresh_rooms_button.configure(state=ctk.NORMAL)
                self.join_room_button.configure(state=ctk.NORMAL)
                self.send_location_button.configure(state=ctk.NORMAL)
                
                # 连接成功后刷新音频设备
                if self.client and self.client.audio_handler:
                    try:
                        self.refresh_audio_devices()
                        self.log_message("音频设备已刷新")
                    except Exception as e:
                        self.log_message(f"刷新音频设备失败: {str(e)}")
                
                self.log_message("连接到服务器成功")
                
                # 连接成功后自动请求房间列表
                self.root.after(1000, self._auto_refresh_room_list)
            else:
                messagebox.showerror("连接失败", "无法连接到服务器")
                
        except Exception as e:
            messagebox.showerror("连接错误", f"连接失败: {str(e)}")
            self.log_message(f"连接错误: {str(e)}")
            # 异常时重置 client 状态
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
    
    def disconnect_from_server(self):
        """断开服务器连接"""
        try:
            if self.client:
                self.client.disconnect()
                self.client = None
            
            self.connection_status.set("未连接")
            self.callsign_ssid_label.configure(text="未连接")
            self.callsign_value_label.configure(text="(未配置)")
            self.ssid_value_label.configure(text="1")
            self.dmr_id_value_label.configure(text="(未配置)")
            self.server_name_label.configure(text="未连接")
            self.packet_count_label.configure(text="↑0 ↓0")
            self.debug_status_label.configure(text="调试:关闭", text_color="gray")
            self.bottom_connection_status.configure(text="离线", text_color="red")
            self.connect_button.configure(state=ctk.NORMAL)
            self.disconnect_button.configure(state=ctk.DISABLED)
            self.send_message_button.configure(state=ctk.DISABLED)
            self.refresh_rooms_button.configure(state=ctk.DISABLED)
            self.join_room_button.configure(state=ctk.DISABLED)
            self.send_location_button.configure(state=ctk.DISABLED)
            
            self.log_message("已断开服务器连接")
            
        except Exception as e:
            messagebox.showerror("断开错误", f"断开连接失败: {str(e)}")
    
    def on_codec_changed(self, choice=None):
        """发射编码格式切换"""
        if not self.client:
            return
        
        selected = self.codec_var.get()
        new_codec = "opus" if "Opus" in selected else "g711"
        
        # PTT 激活中不允许切换
        if self.ptt_active.get():
            messagebox.showwarning("切换失败", "请先停止PTT（按住说话）再切换发射编码")
            current = self.client.audio_config.codec
            self.codec_var.set("Opus (16kHz)" if current == "opus" else "G.711 (8kHz)")
            return
        
        if new_codec == self.client.audio_config.codec:
            return
        
        if new_codec == "opus" and not OpusCodec.is_available():
            messagebox.showerror("切换失败", "opuslib 未安装，无法使用Opus编码。\n请运行: pip install opuslib")
            self.codec_var.set("G.711 (8kHz)")
            return
        
        if self.client.set_codec(new_codec):
            self.log_message(f"发射编码已切换为: {selected}（已保存到配置文件）")
            self.refresh_audio_devices()
        else:
            messagebox.showerror("切换失败", "切换发射编码失败，请查看日志")
            current = self.client.audio_config.codec
            self.codec_var.set("Opus (16kHz)" if current == "opus" else "G.711 (8kHz)")
    
    def toggle_ptt(self):
        """切换PTT状态"""
        if not self.client:
            messagebox.showwarning("未连接", "请先连接到服务器")
            return
        
        if not self.ptt_active.get():
            # 开始语音传输
            if self.client.start_voice_transmission():
                self.ptt_active.set(True)
                self.ptt_status_label.configure(text="PTT: 激活", text_color="red")
                self.log_message("PTT激活 - 开始语音传输")
        else:
            # 停止语音传输
            self.client.stop_voice_transmission()
            self.ptt_active.set(False)
            self.ptt_status_label.configure(text="PTT: 未激活", text_color="white")
            self.log_message("PTT释放 - 停止语音传输")
    
    def start_playback(self):
        """开始播放"""
        if self.client and self.client.audio_handler:
            try:
                self.client.audio_handler.start_playback()
                self.log_message("开始播放")
            except Exception as e:
                messagebox.showerror("播放错误", f"开始播放失败: {str(e)}")
    
    def stop_playback(self):
        """停止播放"""
        if self.client and self.client.audio_handler:
            try:
                self.client.audio_handler.stop_playback()
                self.log_message("停止播放")
            except Exception as e:
                messagebox.showerror("播放错误", f"停止播放失败: {str(e)}")
    
    def toggle_playback(self):
        """切换播放状态：开始或停止播放"""
        if not self.client or not getattr(self.client, 'audio_handler', None):
            messagebox.showwarning("未初始化", "音频处理器未初始化")
            return

        if not self.is_playing:
            try:
                self.start_playback()
                self.is_playing = True
                self.play_toggle_button.configure(text="停止播放")
            except Exception as e:
                messagebox.showerror("播放错误", f"开始播放失败: {str(e)}")
        else:
            try:
                self.stop_playback()
                self.is_playing = False
                self.play_toggle_button.configure(text="开始播放")
            except Exception as e:
                messagebox.showerror("播放错误", f"停止播放失败: {str(e)}")
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete("0.0", ctk.END)
    
    def on_log_level_changed(self, event):
        """日志级别改变事件"""
        level = self.log_level_var.get()
        self.log_message(f"日志级别设置为: {level}")
    
    def on_input_device_changed(self, event):
        """输入设备改变事件"""
        device = self.input_device_var.get()
        self.log_message(f"输入设备已切换到: {device}")
    
    def on_output_device_changed(self, event):
        """输出设备改变事件"""
        device = self.output_device_var.get()
        self.log_message(f"输出设备已切换到: {device}")
    
    def refresh_audio_devices(self):
        """刷新音频设备列表"""
        if self.client and self.client.audio_handler:
            try:
                devices = self.client.audio_handler.list_audio_devices()
                
                # 更新输入设备列表
                input_devices = [d['name'] for d in devices if d['max_input_channels'] > 0]
                self.input_device_combo.configure(values=input_devices)
                if input_devices:
                    self.input_device_combo.set(input_devices[0])
                
                # 更新输出设备列表
                output_devices = [d['name'] for d in devices if d['max_output_channels'] > 0]
                self.output_device_combo.configure(values=output_devices)
                if output_devices:
                    self.output_device_combo.set(output_devices[0])
                    
                self.log_message(f"找到 {len(input_devices)} 个输入设备, {len(output_devices)} 个输出设备")
            except Exception as e:
                self.log_message(f"刷新音频设备失败: {str(e)}")
        else:
            self.log_message("音频处理器未初始化")
    
    def send_text_message(self):
        """发送文本消息"""
        if not self.client:
            messagebox.showwarning("未连接", "请先连接到服务器")
            return
        
        message = self.message_entry.get()
        if not message.strip():
            messagebox.showwarning("警告", "请输入要发送的消息")
            return
        
        try:
            if self.client.send_text_message(message):
                self.log_message(f"发送消息: {message}")
                self.message_entry.delete(0, ctk.END)
            else:
                messagebox.showerror("发送失败", "消息发送失败")
        except Exception as e:
            messagebox.showerror("发送错误", f"消息发送失败: {str(e)}")
    
    def send_location(self):
        """发送当前位置"""
        if not self.client:
            messagebox.showwarning("未连接", "请先连接到服务器")
            return
        self.log_message("正在获取位置...")
        self.send_location_button.configure(state=ctk.DISABLED, text="定位中...")
        threading.Thread(target=self._send_location_thread, daemon=True).start()
    
    def _send_location_thread(self):
        """在子线程中获取位置并发送（优先自动，回退默认配置，最后手动）"""
        try:
            lat, lng, source = self.client.resolve_location()
            if lat == 0.0 and lng == 0.0:
                self.root.after(0, lambda: self.log_message("所有定位方式均不可用，请手动输入坐标..."))
                self.root.after(0, self._prompt_manual_location)
                return
            if self.client.send_location_message(lat, lng):
                source_name = {"gps": "GPS", "ip": "IP定位", "default": "默认配置", "unavailable": "未知"}.get(source, source)
                self.root.after(0, lambda: self.log_message(f"已发送位置: {lat:.6f},{lng:.6f} (来源: {source_name})"))
            else:
                self.root.after(0, lambda: self.log_message("位置消息发送失败"))
        except Exception as e:
            self.root.after(0, lambda: self.log_message(f"获取位置失败: {e}"))
        finally:
            self.root.after(0, lambda: self.send_location_button.configure(state=ctk.NORMAL, text="📍发送位置"))

    def _prompt_manual_location(self):
        """在主线程中弹出对话框让用户手动输入坐标"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("手动输入位置")
        dialog.geometry("320x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="自动定位失败，请手动输入坐标：").pack(pady=(14, 8))

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(pady=4)
        ctk.CTkLabel(frame, text="纬度:").grid(row=0, column=0, padx=5, sticky="e")
        lat_entry = ctk.CTkEntry(frame, width=160, placeholder_text="如 31.861200")
        lat_entry.grid(row=0, column=1, padx=5, pady=3)

        ctk.CTkLabel(frame, text="经度:").grid(row=1, column=0, padx=5, sticky="e")
        lng_entry = ctk.CTkEntry(frame, width=160, placeholder_text="如 117.283900")
        lng_entry.grid(row=1, column=1, padx=5, pady=3)

        def on_ok():
            try:
                lat = float(lat_entry.get())
                lng = float(lng_entry.get())
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字", parent=dialog)
                return
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                messagebox.showerror("输入错误", "纬度范围 -90~90，经度范围 -180~180", parent=dialog)
                return
            dialog.destroy()
            self.log_message("正在发送手动输入的位置...")
            self.send_location_button.configure(state=ctk.DISABLED, text="发送中...")
            threading.Thread(target=self._do_send_manual_location, args=(lat, lng), daemon=True).start()

        def on_cancel():
            dialog.destroy()
            self.send_location_button.configure(state=ctk.NORMAL, text="📍发送位置")

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=12)
        ctk.CTkButton(btn_frame, text="发送", width=80, command=on_ok).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="取消", width=80, command=on_cancel).pack(side="left", padx=10)

        lat_entry.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    def _do_send_manual_location(self, lat: float, lng: float):
        """在子线程中发送手动输入的位置"""
        try:
            if self.client.send_location_message(lat, lng):
                self.root.after(0, lambda: self.log_message(f"已发送位置: {lat:.6f},{lng:.6f} (来源: 手动输入)"))
            else:
                self.root.after(0, lambda: self.log_message("位置消息发送失败"))
        except Exception as e:
            self.root.after(0, lambda: self.log_message(f"发送位置失败: {e}"))
        finally:
            self.root.after(0, lambda: self.send_location_button.configure(state=ctk.NORMAL, text="📍发送位置"))
    
    def on_message_received(self, message):
        """收到消息回调，根据子类型增强显示"""
        if isinstance(message, dict):
            subtype = message.get('subtype', 'text')
            sender = message.get('from', '未知')
            if subtype == 'loc':
                lat = message.get('lat', 0.0)
                lng = message.get('lng', 0.0)
                map_url = message.get('map_url', '')
                self.log_message(f"📍 [{sender}] 位置: {lat:.6f}, {lng:.6f}")
                if map_url:
                    self.log_message(f"   地图: {map_url}")
            else:
                self.log_message(f"收到消息 [{sender}]: {message.get('data', message)}")
        else:
            self.log_message(f"收到消息: {message}")
    
    def on_voice_received(self, data: bytes):
        """收到语音回调"""
        # 在主线程中处理
        self.root.after(0, lambda: self.log_message("收到语音数据"))
    
    def on_status_changed(self, key: str, value):
        """状态改变回调 - 由 nrl_client._update_status(key, value) 触发"""
        # 在主线程中更新 UI
        self.root.after(0, self.update_status_display)
    
    def update_status_display(self):
        """更新状态显示"""
        # 更新当前时间（始终更新，不依赖 client）
        try:
            self.current_time_label.configure(text=time.strftime("%H:%M:%S"))
        except Exception:
            pass
        
        if self.client and self.client.device_config:
            dc = self.client.device_config
            ss = self.client.device_status
            
            # 更新呼号-SSID（底部状态栏）
            self.callsign_ssid_label.configure(text=f"{dc.callsign}-{dc.ssid}")
            
            # 更新顶部状态栏：呼号、SSID、DMRID
            self.callsign_value_label.configure(text=dc.callsign)
            self.ssid_value_label.configure(text=str(dc.ssid))
            self.dmr_id_value_label.configure(text=dc.dmr_id)
            
            # 更新设备信息
            self.device_info.set(
                f"呼号: {dc.callsign}  SSID: {dc.ssid}  DMRID: {dc.dmr_id}  型号: {dc.model}"
            )
            
            # 更新包计数
            tx = ss.get('packets_sent', 0)
            rx = ss.get('packets_received', 0)
            self.packet_count_label.configure(text=f"↑{tx} ↓{rx}")
            
            # 更新服务器名称
            if self.client.server_config:
                self.server_name_label.configure(
                    text=f"{self.client.server_config.host}:{self.client.server_config.port}"
                )
            
            # 更新连接状态
            if self.client.is_connected:
                self.bottom_connection_status.configure(text="在线", text_color="green")
            else:
                self.bottom_connection_status.configure(text="离线", text_color="red")
            
            # 更新音频缓冲区状态
            try:
                buf = self.client.get_audio_buffer_status()
                play_depth = buf.get('play_depth', 0)
                play_ms = buf.get('play_ms', 0)
                rec_bytes = buf.get('record_cache_bytes', 0)
                
                # 颜色：绿色=正常，黄色=偏高，红色=过高
                if play_depth <= 3:
                    color = "#55ff55"  # 绿色
                elif play_depth <= 6:
                    color = "#ffff55"  # 黄色
                else:
                    color = "#ff5555"  # 红色
                
                self.buffer_status_label.configure(
                    text=f"缓冲:{play_depth}帧({play_ms}ms) 缓存:{rec_bytes}B",
                    text_color=color
                )
            except Exception:
                pass
    
    def start_status_update(self):
        """开始状态更新（包括实时时间），安全防重复调用"""
        if self.update_timer is not None:
            return  # 已在运行
        self.update_status_periodically()
    
    def update_status_periodically(self):
        """定期更新状态（每秒刷新时间 + 设备信息）"""
        self.update_status_display()
        self.update_timer = self.root.after(1000, self.update_status_periodically)
    
    def stop_status_update(self):
        """停止状态更新"""
        if self.update_timer:
            self.root.after_cancel(self.update_timer)
            self.update_timer = None
    
    def menu_toggle_debug(self):
        """菜单切换调试模式"""
        enabled = self.debug_force_decode_var.get()
        if self.client:
            self.client.debug_force_decode = enabled
            self.debug_status_label.configure(text="调试:开启" if enabled else "调试:关闭", 
                                           text_color="red" if enabled else "gray")
            self.log_message(f"调试模式: {'开启' if enabled else '关闭'}")
        else:
            self.log_message(f"调试模式: {'开启' if enabled else '关闭'} (将在下次连接时生效)")

    def show_about(self):
        """显示关于信息"""
        about_text = """
78HAM Desktop 客户端
Last Update: 2026-05-10
本项目由78HAM团队开发维护

基于NRL协议开发的Python客户端
支持功能:
- 设备上线注册
- 服务器选择和切换
- 语音通信
- 支持触发DMR转发BM（实验性）
- 支持Opus高清语音（实验性）
- 支持上报位置信息
- 支持房间列表和加入房间（实验性）
- 文本消息
- 心跳维持
- 音频设备选择


本程序为测试版本，不建议在正式环境中使用。
        """
        messagebox.showinfo("关于", about_text.strip())
    
    def on_closing(self):
        """窗口关闭处理 — 确保进程干净退出"""
        import logging as _logging
        _logger = _logging.getLogger(__name__)
        
        # 1) 启动保底强制退出定时器（10秒后无条件终止进程）
        #    必须放在最前面，因为后续任何步骤都可能阻塞
        import threading as _threading
        _kill_timer = _threading.Timer(4.0, lambda: os._exit(0))
        _kill_timer.daemon = True
        _kill_timer.start()
        
        # 2) 停止定时器
        self.stop_status_update()
        
        # 3) 后台关闭客户端（预留 5 秒，正常应在 3 秒内完成）
        if self.client:
            close_done = _threading.Event()
            def _close():
                try:
                    self.client.close()
                except Exception as ex:
                    _logger.error(f"close() 异常: {ex}")
                close_done.set()
            _threading.Thread(target=_close, daemon=True).start()
            if not close_done.wait(timeout=2.0):
                _logger.warning("client.close() 超时（>2s），强制继续")
            else:
                _kill_timer.cancel()  # 正常关闭，取消强制退出定时器
        
        # 4) 刷新日志
        try:
            _logging.shutdown()
        except Exception:
            pass
        
        # 5) 销毁窗口后退出
        try:
            self.root.destroy()
        except Exception:
            pass
        
        os._exit(0)
    
    def update_recent_configs_menu(self):
        """更新最近使用的配置菜单"""
        # 清空现有菜单项
        import tkinter as tk
        self.recent_configs_menu.delete(0, tk.END)
        
        # 添加历史记录
        if self.config_history:
            for i, config_file in enumerate(self.config_history[:5]):  # 只显示最近5个
                # 获取文件名（不含路径）
                filename = os.path.basename(config_file)
                self.recent_configs_menu.add_command(
                    label=f"{i+1}. {filename}",
                    command=lambda f=config_file: self.load_config_file(f)
                )
        else:
            self.recent_configs_menu.add_command(label="无最近使用的配置", state=tk.DISABLED)
        
        # 添加分隔符和清除历史选项
        if self.config_history:
            self.recent_configs_menu.add_separator()
            self.recent_configs_menu.add_command(label="清除历史记录", command=self.clear_config_history)
    
    def update_config_display(self):
        """更新配置信息显示"""
        config_file = self.current_config_file.get()
        filename = os.path.basename(config_file)
        self.log_message(f"当前配置文件: {filename}")
    
    def clear_config_history(self):
        """清除配置历史记录"""
        if messagebox.askyesno("确认", "确定要清除最近使用的配置历史记录吗？"):
            self.config_history.clear()
            self.update_recent_configs_menu()
            self.log_message("已清除配置历史记录")
    
    def show_config_manager(self):
        """显示配置管理器"""
        import tkinter as tk
        import tkinter.ttk as ttk
        manager_window = tk.Toplevel(self.root)
        manager_window.title("配置管理器")
        manager_window.geometry("600x400")
        manager_window.transient(self.root)
        
        # 创建主框架
        main_frame = ttk.Frame(manager_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = ttk.Label(main_frame, text="配置文件管理", font=('Arial', 14, 'bold'))
        title_label.pack(pady=(0, 10))
        
        # 配置列表框架
        list_frame = ttk.LabelFrame(main_frame, text="配置文件列表", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 创建Treeview显示配置信息
        columns = ('文件名', '呼号', '当前服务器', '修改时间')
        self.config_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', height=8)
        
        # 设置列
        self.config_tree.heading('#0', text='')
        self.config_tree.heading('文件名', text='配置文件')
        self.config_tree.heading('呼号', text='呼号')
        self.config_tree.heading('当前服务器', text='当前服务器')
        self.config_tree.heading('修改时间', text='修改时间')
        
        # 设置列宽和对齐
        self.config_tree.column('#0', width=0, stretch=tk.NO)
        self.config_tree.column('文件名', width=150, anchor=tk.W)
        self.config_tree.column('呼号', width=80, anchor=tk.CENTER)
        self.config_tree.column('当前服务器', width=150, anchor=tk.W)
        self.config_tree.column('修改时间', width=120, anchor=tk.CENTER)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.config_tree.yview)
        self.config_tree.configure(yscrollcommand=scrollbar.set)
        
        self.config_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        # 功能按钮
        ttk.Button(button_frame, text="加载配置", command=self.load_selected_config).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="新建配置", command=self.new_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="删除配置", command=self.delete_selected_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="刷新列表", command=self.refresh_config_list).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=manager_window.destroy).pack(side=tk.RIGHT, padx=(5, 0))
        
        # 绑定双击事件
        self.config_tree.bind('<Double-Button-1>', lambda e: self.load_selected_config())
        
        # 刷新配置列表
        self.refresh_config_list()
    
    def refresh_config_list(self):
        """刷新配置列表"""
        # 清空现有项目
        import tkinter as tk
        for item in self.config_tree.get_children():
            self.config_tree.delete(item)
        
        # 获取配置文件列表
        config_files = []
        
        # 添加当前目录的yaml文件
        for file in os.listdir('.'):
            if file.endswith(('.yaml', '.yml')):
                config_files.append(os.path.abspath(file))
        
        # 添加历史记录中的文件
        for config_file in self.config_history:
            if os.path.exists(config_file) and config_file not in config_files:
                config_files.append(config_file)
        
        # 添加每个配置到列表
        for config_file in config_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                # 获取配置信息
                filename = os.path.basename(config_file)
                callsign = config.get('device', {}).get('callsign', 'N/A')
                current_server_idx = config.get('current_server', 0)
                servers = config.get('servers', [])
                
                if 0 <= current_server_idx < len(servers):
                    current_server = servers[current_server_idx].get('name', '未知服务器')
                else:
                    current_server = '未知服务器'
                
                # 获取文件修改时间
                mod_time = os.path.getmtime(config_file)
                mod_time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(mod_time))
                
                # 添加到Treeview
                self.config_tree.insert('', tk.END, values=(filename, callsign, current_server, mod_time_str))
                
            except Exception as e:
                self.log_message(f"读取配置文件 {config_file} 失败: {str(e)}")
    
    def load_selected_config(self):
        """加载选中的配置"""
        import tkinter as tk
        selection = self.config_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个配置文件")
            return
        
        # 获取选中的文件名
        item = self.config_tree.item(selection[0])
        filename = item['values'][0]
        
        # 查找完整路径
        config_file = None
        for file in os.listdir('.'):
            if file == filename:
                config_file = os.path.abspath(file)
                break
        
        if not config_file:
            messagebox.showerror("错误", f"找不到配置文件: {filename}")
            return
        
        # 加载配置
        self.load_config_file(config_file)
    
    def delete_selected_config(self):
        """删除选中的配置"""
        import tkinter as tk
        selection = self.config_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个配置文件")
            return
        
        # 获取选中的文件名
        item = self.config_tree.item(selection[0])
        filename = item['values'][0]
        
        # 确认删除
        if not messagebox.askyesno("确认删除", f"确定要删除配置文件 {filename} 吗？"):
            return
        
        try:
            # 查找完整路径
            config_file = None
            for file in os.listdir('.'):
                if file == filename:
                    config_file = os.path.abspath(file)
                    break
            
            if config_file:
                os.remove(config_file)
                self.log_message(f"已删除配置文件: {filename}")
                
                # 从历史记录中移除
                if config_file in self.config_history:
                    self.config_history.remove(config_file)
                    self.update_recent_configs_menu()
                
                # 刷新列表
                self.refresh_config_list()
            else:
                messagebox.showerror("错误", f"找不到配置文件: {filename}")
                
        except Exception as e:
            messagebox.showerror("错误", f"删除配置文件失败: {str(e)}")
    
    def run(self):
        """运行GUI应用"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 初始化客户端并加载服务器列表
        try:
            self.client = NRLClient()
            self.refresh_servers_list()
        except Exception as e:
            messagebox.showerror("初始化错误", f"客户端初始化失败: {str(e)}")
            self.log_message(f"客户端初始化失败: {str(e)}")
        
        self.log_message("78HAM客户端已启动")
        self.log_message("请先连接到服务器开始使用")
        
        # 初始化配置显示
        self.update_config_display()
        
        self.root.mainloop()
    
    def refresh_servers_list(self):
        """刷新服务器列表"""
        try:
            if not self.client:
                self.client = NRLClient()
            
            # 获取服务器列表
            servers = self.client.get_servers_list()
            self.servers_list = servers
            
            # 更新下拉框
            server_names = [f"{server.name} ({server.host}:{server.port})" for server in servers]
            self.server_combo.configure(values=server_names)
            
            # 设置当前选择的服务器
            current_server = self.client.get_current_server_info()
            if current_server:
                current_name = f"{current_server.name} ({current_server.host}:{current_server.port})"
                if current_name in server_names:
                    self.current_server_var.set(current_name)
                else:
                    self.current_server_var.set(server_names[0] if server_names else "")
            else:
                self.current_server_var.set(server_names[0] if server_names else "")
                
            self.log_message(f"已加载 {len(servers)} 个服务器")
            
        except Exception as e:
            self.log_message(f"刷新服务器列表失败: {str(e)}")
            messagebox.showerror("错误", f"刷新服务器列表失败: {str(e)}")
    
    def on_server_changed(self, event):
        """服务器选择改变事件"""
        try:
            if not self.client:
                return
            
            # 获取选中的服务器索引
            selected_name = self.current_server_var.get()
            selected_index = -1
            
            for i, server in enumerate(self.servers_list):
                server_name = f"{server.name} ({server.host}:{server.port})"
                if server_name == selected_name:
                    selected_index = i
                    break
            
            if selected_index >= 0:
                # 检查是否已连接
                if self.client.is_connected:
                    # 询问用户是否断开当前连接并切换服务器
                    server = self.servers_list[selected_index]
                    result = messagebox.askyesno(
                        "切换服务器",
                        f"当前已连接到服务器，是否要断开当前连接并切换到 {server.name}？"
                    )
                    if not result:
                        # 用户取消，恢复原选择
                        self.refresh_servers_list()
                        return
                
                # 切换服务器
                if self.client.switch_server(selected_index):
                    server = self.servers_list[selected_index]
                    self.log_message(f"已切换到服务器: {server.name} ({server.host}:{server.port})")
                else:
                    messagebox.showerror("切换失败", "服务器切换失败")
                    self.refresh_servers_list()
            
        except Exception as e:
            self.log_message(f"服务器切换失败: {str(e)}")
            messagebox.showerror("错误", f"服务器切换失败: {str(e)}")
            self.refresh_servers_list()

    def new_config(self, initial_data: dict = None):
        """新建或编辑配置（动态服务器列表）"""
        # 使用tkinter对话框，因为CustomTkinter可能没有对应的组件
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox

        is_edit = initial_data is not None
        
        try:
            # 创建新配置窗口
            new_config_window = tk.Toplevel(self.root)
            title = "编辑配置" if is_edit else "新建配置"
            new_config_window.title(title)
            new_config_window.geometry("650x700")
            new_config_window.transient(self.root)
            new_config_window.grab_set()
            
            # 主滚动画布
            canvas = tk.Canvas(new_config_window, borderwidth=0)
            scrollbar = ttk.Scrollbar(new_config_window, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # 鼠标滚轮支持
            def _on_mousewheel(event):
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            def _unbind_mw(event):
                canvas.unbind_all("<MouseWheel>")
            canvas.bind("<Destroy>", _unbind_mw)
            
            # ---- 配置信息 ----
            config_frame = ttk.LabelFrame(scrollable_frame, text="配置信息", padding="10")
            config_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
            
            ttk.Label(config_frame, text="配置名称:").grid(row=0, column=0, sticky=tk.W, pady=5)
            config_name_var = tk.StringVar(value=os.path.basename(self.current_config_file.get()).replace('.yaml','') if is_edit else "新配置")
            ttk.Entry(config_frame, textvariable=config_name_var, width=30).grid(row=0, column=1, sticky=tk.W, pady=5, padx=(5, 0))
            
            # ---- 设备配置 ----
            dev_defaults = initial_data.get('device', {}) if is_edit else {}
            device_frame = ttk.LabelFrame(config_frame, text="设备配置", padding="5")
            device_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
            
            ttk.Label(device_frame, text="呼号:").grid(row=0, column=0, sticky=tk.W, pady=3)
            callsign_var = tk.StringVar(value=dev_defaults.get('callsign', 'BH6XXX'))
            ttk.Entry(device_frame, textvariable=callsign_var, width=15).grid(row=0, column=1, sticky=tk.W, pady=3, padx=(5, 0))
            
            ttk.Label(device_frame, text="SSID:").grid(row=1, column=0, sticky=tk.W, pady=3)
            ssid_var = tk.IntVar(value=dev_defaults.get('ssid', 1))
            ttk.Entry(device_frame, textvariable=ssid_var, width=15).grid(row=1, column=1, sticky=tk.W, pady=3, padx=(5, 0))
            
            ttk.Label(device_frame, text="DMRID:").grid(row=2, column=0, sticky=tk.W, pady=3)
            dmr_id_var = tk.StringVar(value=dev_defaults.get('dmr_id', '123456'))
            ttk.Entry(device_frame, textvariable=dmr_id_var, width=15).grid(row=2, column=1, sticky=tk.W, pady=3, padx=(5, 0))
            
            ttk.Label(device_frame, text="密码:").grid(row=3, column=0, sticky=tk.W, pady=3)
            pwd_var = tk.StringVar(value=dev_defaults.get('password', ''))
            pwd_entry = ttk.Entry(device_frame, textvariable=pwd_var, width=15, show="*")
            pwd_entry.grid(row=3, column=1, sticky=tk.W, pady=3, padx=(5, 0))
            
            ttk.Label(device_frame, text="型号:").grid(row=4, column=0, sticky=tk.W, pady=3)
            model_var = tk.IntVar(value=dev_defaults.get('model', 1))
            ttk.Entry(device_frame, textvariable=model_var, width=15).grid(row=4, column=1, sticky=tk.W, pady=3, padx=(5, 0))
            
            # ---- 服务器列表（动态） ----
            servers_outer = ttk.LabelFrame(scrollable_frame, text="服务器列表", padding="5")
            servers_outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            columns = ('名称', '地址', '端口', '密码')
            server_tree = ttk.Treeview(servers_outer, columns=columns, show='headings', height=5)
            server_tree.heading('名称', text='名称')
            server_tree.heading('地址', text='地址')
            server_tree.heading('端口', text='端口')
            server_tree.heading('密码', text='密码')
            server_tree.column('名称', width=120)
            server_tree.column('地址', width=160)
            server_tree.column('端口', width=70)
            server_tree.column('密码', width=80)
            
            tree_scroll = ttk.Scrollbar(servers_outer, orient=tk.VERTICAL, command=server_tree.yview)
            server_tree.configure(yscrollcommand=tree_scroll.set)
            server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            
            server_entries = []
            
            servers_data = initial_data.get('servers', []) if is_edit else [
                {'name': '示例服务器', 'host': '', 'port': 60050, 'password': ''},
            ]
            for srv in servers_data:
                row = {
                    'name': tk.StringVar(value=str(srv.get('name', ''))),
                    'host': tk.StringVar(value=str(srv.get('host', ''))),
                    'port': tk.StringVar(value=str(srv.get('port', 60050))),
                    'password': tk.StringVar(value=str(srv.get('password', ''))),
                }
                server_entries.append(row)
                server_tree.insert('', tk.END, values=(
                    row['name'].get(), row['host'].get(), row['port'].get(),
                    '****' if row['password'].get() else ''
                ))
            
            # 服务器操作按钮
            srv_btn_frame = ttk.Frame(servers_outer)
            srv_btn_frame.pack(fill=tk.X, pady=(5, 0))
            
            def add_server_entry():
                row = {
                    'name': tk.StringVar(value='新服务器'),
                    'host': tk.StringVar(value=''),
                    'port': tk.StringVar(value='60050'),
                    'password': tk.StringVar(value=''),
                }
                server_entries.append(row)
                server_tree.insert('', tk.END, values=(row['name'].get(), row['host'].get(), row['port'].get(), ''))
            
            def edit_server_entry():
                sel = server_tree.selection()
                if not sel:
                    messagebox.showwarning("提示", "请先选中一个服务器")
                    return
                idx = server_tree.index(sel[0])
                row = server_entries[idx]
                
                edit_win = tk.Toplevel(new_config_window)
                edit_win.title("编辑服务器")
                edit_win.geometry("380x200")
                edit_win.transient(new_config_window)
                edit_win.grab_set()
                
                f = ttk.Frame(edit_win, padding="10")
                f.pack(fill=tk.BOTH, expand=True)
                
                ttk.Label(f, text="名称:").grid(row=0, column=0, sticky=tk.W, pady=3)
                ttk.Entry(f, textvariable=row['name'], width=25).grid(row=0, column=1, padx=(5, 0), pady=3)
                
                ttk.Label(f, text="地址:").grid(row=1, column=0, sticky=tk.W, pady=3)
                ttk.Entry(f, textvariable=row['host'], width=25).grid(row=1, column=1, padx=(5, 0), pady=3)
                
                ttk.Label(f, text="端口:").grid(row=2, column=0, sticky=tk.W, pady=3)
                ttk.Entry(f, textvariable=row['port'], width=25).grid(row=2, column=1, padx=(5, 0), pady=3)
                
                ttk.Label(f, text="密码:").grid(row=3, column=0, sticky=tk.W, pady=3)
                ttk.Entry(f, textvariable=row['password'], width=25, show="*").grid(row=3, column=1, padx=(5, 0), pady=3)
                
                def save_edit():
                    server_tree.item(sel[0], values=(
                        row['name'].get(), row['host'].get(), row['port'].get(),
                        '****' if row['password'].get() else ''
                    ))
                    edit_win.destroy()
                
                btn_f = ttk.Frame(f)
                btn_f.grid(row=4, column=0, columnspan=2, pady=(15, 0))
                ttk.Button(btn_f, text="确定", command=save_edit).pack(side=tk.LEFT, padx=5)
                ttk.Button(btn_f, text="取消", command=edit_win.destroy).pack(side=tk.LEFT, padx=5)
            
            def remove_server_entry():
                sel = server_tree.selection()
                if not sel:
                    messagebox.showwarning("提示", "请先选中一个服务器")
                    return
                if not messagebox.askyesno("确认", "确定要删除该服务器吗？"):
                    return
                idx = server_tree.index(sel[0])
                server_tree.delete(sel[0])
                server_entries.pop(idx)
            
            def move_up():
                sel = server_tree.selection()
                if not sel:
                    return
                idx = server_tree.index(sel[0])
                if idx == 0:
                    return
                server_entries[idx], server_entries[idx-1] = server_entries[idx-1], server_entries[idx]
                server_tree.move(sel[0], '', idx-1)
            
            def move_down():
                sel = server_tree.selection()
                if not sel:
                    return
                idx = server_tree.index(sel[0])
                if idx >= len(server_entries) - 1:
                    return
                server_entries[idx], server_entries[idx+1] = server_entries[idx+1], server_entries[idx]
                server_tree.move(sel[0], '', idx+1)
            
            ttk.Button(srv_btn_frame, text="添加", command=add_server_entry, width=8).pack(side=tk.LEFT, padx=(0, 3))
            ttk.Button(srv_btn_frame, text="编辑", command=edit_server_entry, width=8).pack(side=tk.LEFT, padx=3)
            ttk.Button(srv_btn_frame, text="删除", command=remove_server_entry, width=8).pack(side=tk.LEFT, padx=3)
            ttk.Button(srv_btn_frame, text="上移", command=move_up, width=6).pack(side=tk.LEFT, padx=3)
            ttk.Button(srv_btn_frame, text="下移", command=move_down, width=6).pack(side=tk.LEFT, padx=3)
            
            # ---- 音频配置 ----
            audio_defaults = initial_data.get('audio', {}) if is_edit else {}
            audio_frame = ttk.LabelFrame(scrollable_frame, text="音频配置", padding="5")
            audio_frame.pack(fill=tk.X, padx=10, pady=5)
            
            ttk.Label(audio_frame, text="采样率:").grid(row=0, column=0, sticky=tk.W, pady=3)
            sr_var = tk.IntVar(value=audio_defaults.get('sample_rate', 8000))
            ttk.Entry(audio_frame, textvariable=sr_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=3, padx=(5, 15))
            
            ttk.Label(audio_frame, text="声道数:").grid(row=0, column=2, sticky=tk.W, pady=3)
            ch_var = tk.IntVar(value=audio_defaults.get('channels', 1))
            ttk.Entry(audio_frame, textvariable=ch_var, width=8).grid(row=0, column=3, sticky=tk.W, pady=3, padx=(5, 15))
            
            ttk.Label(audio_frame, text="块大小:").grid(row=1, column=0, sticky=tk.W, pady=3)
            ck_var = tk.IntVar(value=audio_defaults.get('chunk_size', 500))
            ttk.Entry(audio_frame, textvariable=ck_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=3, padx=(5, 15))
            
            ttk.Label(audio_frame, text="格式:").grid(row=1, column=2, sticky=tk.W, pady=3)
            fmt_var = tk.StringVar(value=audio_defaults.get('format', 'paInt16'))
            ttk.Entry(audio_frame, textvariable=fmt_var, width=10).grid(row=1, column=3, sticky=tk.W, pady=3, padx=(5, 15))
            
            # ---- 网络配置 ----
            net_defaults = initial_data.get('network', {}) if is_edit else {}
            net_frame = ttk.LabelFrame(scrollable_frame, text="网络配置", padding="5")
            net_frame.pack(fill=tk.X, padx=10, pady=5)
            
            ttk.Label(net_frame, text="缓冲区大小:").grid(row=0, column=0, sticky=tk.W, pady=3)
            buf_var = tk.IntVar(value=net_defaults.get('buffer_size', 4096))
            ttk.Entry(net_frame, textvariable=buf_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=3, padx=(5, 15))
            
            ttk.Label(net_frame, text="心跳间隔(秒):").grid(row=0, column=2, sticky=tk.W, pady=3)
            hb_var = tk.IntVar(value=net_defaults.get('heartbeat_interval', 2))
            ttk.Entry(net_frame, textvariable=hb_var, width=8).grid(row=0, column=3, sticky=tk.W, pady=3, padx=(5, 15))
            
            # ---- 底部按钮 ----
            button_frame = ttk.Frame(scrollable_frame)
            button_frame.pack(fill=tk.X, padx=10, pady=(10, 15))
            
            def create_config():
                try:
                    if not server_entries:
                        messagebox.showerror("错误", "请至少添加一个服务器")
                        return
                    if not callsign_var.get().strip():
                        messagebox.showerror("错误", "请输入设备呼号")
                        return
                    
                    servers_list = []
                    for row in server_entries:
                        servers_list.append({
                            'name': row['name'].get(),
                            'host': row['host'].get(),
                            'port': int(row['port'].get()) if row['port'].get().isdigit() else row['port'].get(),
                            'password': row['password'].get(),
                        })
                    
                    config_data = {
                        'servers': servers_list,
                        'current_server': 0,
                        'device': {
                            'callsign': callsign_var.get().strip(),
                            'ssid': ssid_var.get(),
                            'dmr_id': dmr_id_var.get(),
                            'password': pwd_var.get(),
                            'model': model_var.get()
                        },
                        'audio': {
                            'sample_rate': sr_var.get(),
                            'channels': ch_var.get(),
                            'chunk_size': ck_var.get(),
                            'format': fmt_var.get()
                        },
                        'network': {
                            'buffer_size': buf_var.get(),
                            'heartbeat_interval': hb_var.get()
                        }
                    }
                    
                    if is_edit:
                        filename = self.current_config_file.get()
                        with open(filename, 'w', encoding='utf-8') as f:
                            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
                        self.log_message(f"配置已更新: {filename}")
                        messagebox.showinfo("成功", f"配置已更新:\n{filename}")
                        new_config_window.destroy()
                        self.load_config_file(filename)
                        return
                    
                    filename = filedialog.asksaveasfilename(
                        defaultextension=".yaml",
                        filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
                        initialfile=f"{config_name_var.get()}.yaml"
                    )
                    
                    if not filename:
                        return
                    
                    with open(filename, 'w', encoding='utf-8') as f:
                        yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)
                    
                    self.log_message(f"配置已保存到: {filename}")
                    messagebox.showinfo("成功", f"配置已成功保存到:\n{filename}")
                    
                    if filename not in self.config_history:
                        self.config_history.insert(0, filename)
                        if len(self.config_history) > 10:
                            self.config_history = self.config_history[:10]
                    else:
                        self.config_history.remove(filename)
                        self.config_history.insert(0, filename)
                    
                    self.update_recent_configs_menu()
                    self.update_config_display()
                    new_config_window.destroy()
                    
                    if messagebox.askyesno("加载配置", "是否要立即加载新创建的配置？"):
                        self.load_config_file(filename)
                    
                except Exception as e:
                    messagebox.showerror("错误", f"创建配置失败: {str(e)}")
                    self.log_message(f"创建配置失败: {str(e)}")
            
            def cancel_create():
                new_config_window.destroy()
            
            ttk.Button(button_frame, text="保存", command=create_config, width=10).pack(side=tk.RIGHT, padx=(5, 0))
            ttk.Button(button_frame, text="取消", command=cancel_create).pack(side=tk.RIGHT)
            
        except Exception as e:
            messagebox.showerror("错误", f"打开新建配置窗口失败: {str(e)}")
            self.log_message(f"打开新建配置窗口失败: {str(e)}")

    def edit_config(self):
        """编辑当前配置"""
        import tkinter as tk
        from tkinter import messagebox
        try:
            config_file = self.current_config_file.get()
            if not os.path.exists(config_file):
                messagebox.showerror("错误", f"配置文件不存在: {config_file}")
                return
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f) or {}
            
            self.new_config(initial_data=config_data)
            
        except Exception as e:
            messagebox.showerror("错误", f"编辑配置失败: {str(e)}")
            self.log_message(f"编辑配置失败: {str(e)}")

    def load_config(self):
        """加载配置"""
        import tkinter as tk
        from tkinter import filedialog, messagebox
        
        try:
            filename = filedialog.askopenfilename(
                title="选择配置文件",
                filetypes=[("YAML files", "*.yaml"), ("YAML files", "*.yml"), ("All files", "*.*")]
            )
            
            if filename:
                self.load_config_file(filename)
        except Exception as e:
            messagebox.showerror("错误", f"加载配置失败: {str(e)}")
            self.log_message(f"加载配置失败: {str(e)}")

    def load_config_file(self, filename):
        """加载配置文件"""
        try:
            # 加载配置文件
            with open(filename, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 更新当前配置文件
            self.current_config_file.set(filename)
            
            # 更新配置历史记录
            if filename not in self.config_history:
                self.config_history.insert(0, filename)
                # 限制历史记录数量
                if len(self.config_history) > 10:
                    self.config_history = self.config_history[:10]
            else:
                # 如果已存在，移到最前面
                self.config_history.remove(filename)
                self.config_history.insert(0, filename)
            
            # 更新最近使用菜单
            self.update_recent_configs_menu()
            
            # 更新配置显示
            self.update_config_display()
            
            self.log_message(f"配置已加载: {filename}")
            
            # 如果已有客户端实例，尝试重新初始化
            if self.client:
                self.client.close()
                self.client = None
            
            # 重新初始化客户端
            self.client = NRLClient(filename)
            
            # 设置回调
            self.client.set_message_callback(self.on_message_received)
            self.client.set_voice_callback(self.on_voice_received)
            self.client.set_status_callback(self.on_status_changed)
            self.client.group_list_callback = self.on_group_list_updated
            self.client.group_change_callback = self.on_group_changed
            self.client.debug_force_decode = self.debug_force_decode_var.get()
            
            # 立即更新状态显示（呼号等）
            self.update_status_display()
            
            # 刷新服务器列表
            self.refresh_servers_list()
            
        except Exception as e:
            messagebox.showerror("错误", f"加载配置文件失败: {str(e)}")
            self.log_message(f"加载配置文件失败: {str(e)}")

    def test_audio_devices(self):
        """测试音频设备"""
        try:
            if self.client and self.client.audio_handler:
                self.client.audio_handler.test_audio_devices()
                self.log_message("音频设备测试完成")
            else:
                messagebox.showwarning("警告", "音频处理器未初始化")
        except Exception as e:
            messagebox.showerror("错误", f"音频设备测试失败: {str(e)}")
            self.log_message(f"音频设备测试失败: {str(e)}")

    def test_network(self):
        """网络测试"""
        try:
            if self.client:
                # 这里可以实现具体的网络测试逻辑
                self.log_message("网络测试功能待实现")
            else:
                messagebox.showwarning("警告", "客户端未初始化")
        except Exception as e:
            messagebox.showerror("错误", f"网络测试失败: {str(e)}")
            self.log_message(f"网络测试失败: {str(e)}")

    def show_device_config(self):
        """显示设备配置总览"""
        try:
            if not self.client:
                messagebox.showwarning("警告", "客户端未初始化")
                return
            
            c = self.client
            config = {}
            
            # 设备配置
            if c.device_config:
                config['设备'] = {
                    '呼号': c.device_config.callsign,
                    'SSID': c.device_config.ssid,
                    'DMRID': c.device_config.dmr_id,
                    '型号': c.device_config.model,
                }
            
            # 服务器配置
            if c.server_config:
                config['服务器'] = {
                    '地址': c.server_config.host,
                    '端口': c.server_config.port,
                }
            
            # 音频配置
            if c.audio_config:
                config['音频'] = {
                    '采样率': f"{c.audio_config.sample_rate} Hz",
                    '声道数': c.audio_config.channels,
                    '发射编码': c.audio_config.codec,
                    '格式': c.audio_config.format,
                }
            
            # 网络配置
            if c.network_config:
                config['网络'] = {
                    '缓冲区大小': c.network_config.buffer_size,
                    '心跳间隔': f"{c.network_config.heartbeat_interval} 秒",
                }
            
            # 服务器列表
            if c.servers_list:
                servers = []
                for i, s in enumerate(c.servers_list):
                    prefix = "→ " if i == c.current_server_index else "  "
                    servers.append(f"{prefix}{s.name} ({s.host}:{s.port})")
                config['服务器列表'] = servers
            
            config_str = yaml.dump(config, default_flow_style=False, allow_unicode=True)
            
            # 创建显示窗口
            import tkinter as tk
            from tkinter import scrolledtext
            
            config_window = tk.Toplevel(self.root)
            config_window.title("配置总览")
            config_window.geometry("500x420")
            config_window.transient(self.root)
            
            text_area = scrolledtext.ScrolledText(config_window, wrap=tk.WORD,
                                                  font=('Consolas', 10))
            text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            text_area.insert(tk.END, config_str)
            text_area.config(state=tk.DISABLED)
            
        except Exception as e:
            messagebox.showerror("错误", f"显示配置总览失败: {str(e)}")
            self.log_message(f"显示配置总览失败: {str(e)}")


class GUILogHandler(logging.Handler):
    """GUI日志处理器 - 线程安全，带限流防止GUI卡死"""
    
    def __init__(self, callback, root=None):
        super().__init__()
        self.callback = callback
        self.root = root
        self._last_emit_time = 0.0
        self._min_interval = 0.05  # 最短 50ms 间隔
    
    def emit(self, record):
        """发送日志记录 - 限流 + 崩溃保护"""
        try:
            now = time.time()
            if now - self._last_emit_time < self._min_interval:
                return
            self._last_emit_time = now
            
            msg = self.format(record)
            if self.callback:
                if self.root:
                    self.root.after(0, self.callback, msg)
                else:
                    self.callback(msg)
        except Exception:
            # root 可能已被销毁，静默忽略
            pass

# 在 GUILogHandler 类之后，NRLGUIClient 类内部添加缺失的方法
# （注意：这些方法应与类中的其他方法具有相同的缩进级别）

# 以下是 NRLGUIClient 类中缺失的方法


def main():
    """主函数"""
    app = NRLGUIClient()
    app.run()


if __name__ == "__main__":
    main()