"""
78HAM客户端Demo

基于78HAM项目开发的Python客户端，实现基本的业余无线电网络互联功能

功能特性:
- 设备上线注册
- 语音通信 (G.711编解码)
- 文本消息
- 心跳维持
- 音频设备管理
- 图形化界面

使用方法:
1. 配置config.yaml文件
2. 运行 python main.py
3. 点击"连接"按钮连接到服务器
4. 使用PTT按钮进行语音通信
5. 发送文本消息

协议说明:
- 基于NRL2协议
- UDP端口60050
- 支持G.711 A-law语音编解码
- 心跳间隔30秒
"""

import sys
import os
import argparse
import logging

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from nrl_client import get_os_display_name, OS_NAME_MAP
syskd = get_os_display_name()

def setup_logging(level=logging.INFO):
    """设置日志系统"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('nrl_client.log', encoding='utf-8')
        ]
    )

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='78HAM客户端Demo')
    parser.add_argument('--config', '-c', default='config.yaml',
                       help='配置文件路径 (默认: config.yaml)')
    parser.add_argument('--no-gui', action='store_true',
                       help='无GUI模式，使用命令行界面')
    parser.add_argument('--debug', action='store_true',
                       help='启用调试模式')
    parser.add_argument('--test-audio', action='store_true',
                       help='测试音频设备并退出')
    parser.add_argument('--list-audio', action='store_true',
                       help='列出音频设备并退出')
    parser.add_argument('--gui', choices=['ctk', 'tk'], default='ctk',
                       help='选择GUI类型: ctk (现代CustomTkinter, 默认) 或 tk (传统Tkinter)')
    
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(log_level)
    
    logger = logging.getLogger(__name__)
    
    try:
        # 音频设备测试
        if args.test_audio or args.list_audio:
            from audio_handler import AudioHandler
            audio_handler = AudioHandler()
            
            if args.list_audio:
                print("音频设备列表:")
                devices = audio_handler.list_audio_devices()
            else:
                print("开始音频设备测试...")
                audio_handler.test_audio_devices()
            
            audio_handler.close()
            return
        
        # GUI模式
        if not args.no_gui:
            try:
                if args.gui == 'ctk':
                    # 默认使用现代CustomTkinter GUI
                    from gui_client_ctk import NRLGUIClient
                    gui_type = "CustomTkinter"
                else:
                    from gui_client import NRLGUIClient
                    gui_type = "Tkinter"
                
                logger.info(f"启动78HAM客户端 ({gui_type} GUI模式)")
                app = NRLGUIClient()
                app.run()
                
            except ImportError:
                if args.gui == 'ctk':
                    logger.warning("CustomTkinter未安装，尝试回退到Tkinter GUI...")
                    try:
                        from gui_client import NRLGUIClient
                        logger.info("启动78HAM客户端 (Tkinter GUI模式 - 回退)")
                        app = NRLGUIClient()
                        app.run()
                    except ImportError:
                        logger.error("所有GUI组件导入失败，尝试使用命令行模式...")
                        args.no_gui = True
                else:
                    logger.error(f"GUI组件导入失败，尝试使用命令行模式...")
                    args.no_gui = True
        
        # 命令行模式
        if args.no_gui:
            from nrl_client import NRLClient
            
            logger.info("启动78HAM客户端 (命令行模式)")
            logger.info(f"系统类型: {syskd}")
            
            # 创建客户端
            client = NRLClient(args.config)
            
            # 简单的命令行界面
            print("\n78HAM客户端命令行界面")
            print(f"当前操作系统是：{syskd}")
            print("可用命令:")
            print("  connect - 连接到服务器")
            print("  disconnect - 断开连接")
            print("  status - 查看状态")
            print("  send <消息> - 发送文本消息")
            print("  rooms - 拉取房间列表")
            print("  join <房间ID> - 加入指定房间")
            print("  loc [lat lng] - 发送位置 (自动GPS或手动坐标)")
            print("  voice_start - 开始语音传输")
            print("  voice_stop - 停止语音传输")
            print("  help - 列出所有可用命令")
            print("  exit - 退出")
            print()
            
            while True:
                try:
                    command = input("> ").strip().lower()
                    
                    if command == 'exit':
                        break
                    elif command == 'connect':
                        if client.connect():
                            print("连接成功")
                        else:
                            print("连接失败")
                    elif command == 'disconnect':
                        client.disconnect()
                        print("已断开连接")
                    elif command == 'status':
                        status = client.get_status()
                        print(f"状态: {status}")
                    elif command.startswith('send '):
                        message = command[5:]
                        if client.send_text_message(message):
                            print(f"发送消息: {message}")
                        else:
                            print("发送失败")
                    elif command == 'voice_start':
                        if client.start_voice_transmission():
                            print("语音传输已启动")
                        else:
                            print("启动语音传输失败")
                    elif command == 'voice_stop':
                        client.stop_voice_transmission()
                        print("语音传输已停止")
                    elif command == 'rooms':
                        if not client.is_connected:
                            print("请先连接到服务器")
                        else:
                            # 设置回调打印结果
                            def _on_group_list(gl):
                                print(f"\n房间列表 (共 {len(gl)} 个):")
                                for g in gl:
                                    marker = " <-- 当前" if g['id'] == client.current_group_id else ""
                                    print(f"  {g['id']:>4}  {g['name']}{marker}")
                                print()
                            client.group_list_callback = _on_group_list
                            if client.request_group_list():
                                print("正在获取房间列表...")
                            else:
                                print("发送请求失败")
                    elif command.startswith('join '):
                        if not client.is_connected:
                            print("请先连接到服务器")
                        else:
                            try:
                                group_id = int(command[5:].strip())
                                # 设置回调打印结果
                                def _on_group_changed(gid, gname):
                                    if gid < 0 or gname == "error":
                                        print(f"加入房间失败: 服务器拒绝")
                                    else:
                                        print(f"已切换到房间: {gid}-{gname}")
                                client.group_change_callback = _on_group_changed
                                if client.join_group(group_id):
                                    print(f"正在加入房间 {group_id}...")
                                else:
                                    print("发送请求失败")
                            except ValueError:
                                print("用法: join <房间ID> (纯数字)")
                    elif command.startswith('loc'):
                        if not client.is_connected:
                            print("请先连接到服务器")
                        else:
                            parts = command.split()
                            if len(parts) == 3:
                                # loc <lat> <lng> 手动输入坐标
                                try:
                                    lat = float(parts[1])
                                    lng = float(parts[2])
                                    if client.send_location_message(lat, lng):
                                        print(f"已发送位置: {lat},{lng}")
                                    else:
                                        print("发送失败")
                                except ValueError:
                                    print("用法: loc <纬度> <经度> (如: loc 31.8612 117.2839)")
                            else:
                                # loc 自动获取GPS
                                print("正在获取位置...")
                                lat, lng, source = client.get_current_location()
                                if lat == 0.0 and lng == 0.0:
                                    print("定位失败: 无法获取当前位置")
                                else:
                                    source_name = {"gps": "GPS", "ip": "IP定位"}.get(source, source)
                                    print(f"当前位置: {lat:.6f},{lng:.6f} (来源: {source_name})")
                                    if client.send_location_message(lat, lng):
                                        print("位置消息已发送")
                                    else:
                                        print("发送失败")
                    elif command == 'help':
                        print("可用命令：")
                        print("  connect - 连接到服务器")
                        print("  disconnect - 断开连接")
                        print("  status - 查看状态")
                        print("  send <消息> - 发送文本消息")
                        print("  rooms - 拉取房间列表")
                        print("  join <房间ID> - 加入指定房间")
                        print("  loc [lat lng] - 发送位置 (自动GPS或手动坐标)")
                        print("  voice_start - 开始语音传输")
                        print("  voice_stop - 停止语音传输")
                        print("  help - 列出所有可用命令")
                        print("  exit - 退出")
                        print()
                    elif command == '':
                        continue
                    else:
                        print(f"未知命令: {command}")
                        print(f"键入 help 来列出所有可用的命令")
                except KeyboardInterrupt:
                    print("\n使用 'exit' 命令退出")
                except Exception as e:
                    logger.error(f"命令执行错误: {e}")
            
            # 关闭客户端
            client.close()
            logger.info("78HAM客户端已关闭")
    
    except KeyboardInterrupt:
        logger.info("用户中断程序")
    except Exception as e:
        logger.error(f"程序运行错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()