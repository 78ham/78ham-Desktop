"""
78HAM 用户界面模块

新架构 GUI，基于 CustomTkinter + 组件化设计。
使用 TalkService/RoomService/LocationService 作为业务层。

注意：App 类需要 customtkinter，延迟导入以避免无 GUI 环境报错。
"""


def get_app_class():
    """获取 App 类（延迟导入）"""
    from ui.app import App
    return App


__all__ = ['get_app_class']
