"""
UI 主题与样式常量

集中管理颜色、字体、间距等视觉参数。
支持亮色/暗色主题切换（CustomTkinter 原生支持）。
"""


class Colors:
    """颜色常量"""
    # 状态颜色
    CONNECTED = "#2ecc71"
    DISCONNECTED = "#e74c3c"
    CONNECTING = "#f39c12"
    TRANSMITTING = "#e74c3c"
    RECEIVING = "#3498db"

    # PTT 按钮
    PTT_IDLE = "#2c3e50"
    PTT_ACTIVE = "#c0392b"
    PTT_HOVER = "#34495e"

    # 文本
    TEXT_PRIMARY = "#ecf0f1"
    TEXT_SECONDARY = "#bdc3c7"
    TEXT_MUTED = "#7f8c8d"

    # 背景
    BG_DARK = "#1a1a2e"
    BG_CARD = "#16213e"
    BG_INPUT = "#0f3460"

    # 强调色
    ACCENT = "#e94560"
    ACCENT_HOVER = "#ff6b6b"

    # 日志级别
    LOG_INFO = "#ecf0f1"
    LOG_WARNING = "#f39c12"
    LOG_ERROR = "#e74c3c"
    LOG_DEBUG = "#95a5a6"


class Fonts:
    """字体常量"""
    FAMILY_MONO = "Consolas"
    FAMILY_UI = "Microsoft YaHei UI"
    FAMILY_FALLBACK = "Arial"

    SIZE_TITLE = 16
    SIZE_HEADING = 13
    SIZE_BODY = 11
    SIZE_SMALL = 9
    SIZE_LOG = 10


class Spacing:
    """间距常量"""
    PAD_XS = 2
    PAD_SM = 5
    PAD_MD = 10
    PAD_LG = 15
    PAD_XL = 20

    FRAME_PAD = 10
    WIDGET_GAP = 5


class Sizes:
    """尺寸常量"""
    WINDOW_WIDTH = 900
    WINDOW_HEIGHT = 700
    WINDOW_MIN_WIDTH = 750
    WINDOW_MIN_HEIGHT = 550

    PTT_BUTTON_WIDTH = 200
    PTT_BUTTON_HEIGHT = 60

    LOG_MAX_LINES = 500
    CHAT_MAX_MESSAGES = 200
