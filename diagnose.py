"""
诊断脚本：检查gui_client_ctk模块中的问题
"""
import sys
import traceback

try:
    from gui_client_ctk import NRLGUIClient
    print("✓ 成功导入 NRLGUIClient 类")
    
    # 检查类的所有方法
    methods = [method for method in dir(NRLGUIClient) if not method.startswith('_')]
    print(f"类中包含的方法数量: {len(methods)}")
    
    # 检查特定方法是否存在
    required_methods = ['new_config', 'load_config', 'load_config_file', 'test_audio_devices', 'test_network', 'show_device_config']
    for method in required_methods:
        if hasattr(NRLGUIClient, method):
            print(f"✓ 方法 {method} 存在")
        else:
            print(f"✗ 方法 {method} 不存在")
    
    # 尝试创建实例
    print("\n尝试创建实例...")
    app = NRLGUIClient()
    print("✓ 成功创建 NRLGUIClient 实例")
    
    # 检查实例上的方法
    for method in required_methods:
        if hasattr(app, method):
            print(f"✓ 实例上有方法 {method}")
        else:
            print(f"✗ 实例上没有方法 {method}")
    
    print("\n初始化成功！")
    
except Exception as e:
    print(f"✗ 错误: {e}")
    print("详细错误信息:")
    traceback.print_exc()