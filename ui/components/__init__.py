"""
UI 组件包

所有可复用的 GUI 组件。
每个组件是独立的 CTkFrame 子类，通过回调与外部通信。

注意：组件依赖 customtkinter，仅在 GUI 模式下导入。
"""
# 延迟导入，避免无 GUI 环境报错
# 使用时直接 from ui.components.xxx import Xxx
