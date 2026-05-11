"""
78HAM 桌面客户端入口

基于模块化架构，使用 TalkService 作为核心业务编排层。
"""
import sys
import os
import argparse
import logging

# 添加当前目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)


def setup_logging(level=logging.INFO):
    """设置日志系统"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('78ham.log', encoding='utf-8'),
        ]
    )


def main():
    parser = argparse.ArgumentParser(description='78HAM 桌面客户端')
    parser.add_argument('--config', '-c', default='config.yaml',
                        help='配置文件路径 (默认: config.yaml)')
    parser.add_argument('--no-gui', action='store_true',
                        help='命令行模式')
    parser.add_argument('--debug', action='store_true',
                        help='启用调试模式')
    parser.add_argument('--test-audio', action='store_true',
                        help='测试音频设备并退出')
    parser.add_argument('--list-audio', action='store_true',
                        help='列出音频设备并退出')

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(log_level)
    logger = logging.getLogger(__name__)

    try:
        # 音频设备测试
        if args.test_audio or args.list_audio:
            from audio.audio_manager import AudioManager
            mgr = AudioManager()
            if args.list_audio:
                print("音频设备列表:")
                mgr.list_devices()
            else:
                print("开始音频设备测试...")
            mgr.close()
            return

        # GUI 模式
        if not args.no_gui:
            try:
                from ui.app import App
                logger.info("启动 78HAM 客户端 (GUI)")
                app = App(args.config)
                app.run()
                return
            except ImportError as e:
                logger.warning(f"GUI 启动失败 ({e})，回退到命令行模式")
                args.no_gui = True

        # 命令行模式
        if args.no_gui:
            _run_cli(args)

    except KeyboardInterrupt:
        logger.info("用户中断程序")
    except Exception as e:
        logger.error(f"程序运行错误: {e}")
        sys.exit(1)


def _run_cli(args):
    """命令行模式"""
    from config.settings import Settings
    from services.talk_service import TalkService
    from services.room_service import RoomService
    from services.location_service import LocationService
    from services.aprs_service import AprsService

    logger = logging.getLogger(__name__)

    # 加载配置
    settings = Settings.load(args.config)

    # 创建服务
    talk = TalkService(settings)
    room = RoomService(settings, talk.udp_client)
    location = LocationService(settings)
    aprs = AprsService(settings, location)

    # 注册回调
    def _on_msg(msg):
        if msg.get('type') == 'group_response':
            room.handle_group_response(msg.get('data', b''))
        else:
            print(f"\n[{msg.get('from', '?')}] {msg.get('content', '')}")
    talk.on_message = _on_msg
    talk.on_voice_data = lambda pcm, info: print(
        f"\r[voice] {info.get('from', '?')}", end='', flush=True)

    room.on_group_list = lambda gl: print(
        f"\n房间列表 ({len(gl)} 个): " +
        ", ".join(f"{g['id']}-{g['name']}" for g in gl))
    room.on_group_changed = lambda gid, name: print(
        f"\n已切换到房间: {gid}-{name}")

    print("\n78HAM 桌面客户端 (CLI)")
    print(f"呼号: {settings.device.callsign}-{settings.device.ssid}")
    print(f"服务器: {settings.server.host}:{settings.server.port}")
    print(f"编码: {settings.audio.codec}")
    print("\n命令: connect | disconnect | status | send <msg> | rooms | join <id> | loc | codec <g711|opus> | aprs | exit\n")

    while True:
        try:
            cmd = input("> ").strip()
            if not cmd:
                continue

            if cmd == 'exit':
                break
            elif cmd == 'connect':
                if talk.start():
                    print("连接成功")
                    location.on_send_location = talk.send_location
                    location.start_auto_report()
                else:
                    print("连接失败")
            elif cmd == 'disconnect':
                location.stop_auto_report()
                talk.stop()
                print("已断开")
            elif cmd == 'status':
                print(talk.get_status())
            elif cmd.startswith('send '):
                msg = cmd[5:]
                if talk.send_text_message(msg):
                    print(f"已发送: {msg}")
                else:
                    print("发送失败")
            elif cmd == 'rooms':
                room.request_group_list()
            elif cmd.startswith('join '):
                try:
                    gid = int(cmd[5:].strip())
                    room.join_group(gid)
                except ValueError:
                    print("用法: join <房间ID>")
            elif cmd == 'loc':
                lat, lng, src = location.get_location()
                if lat != 0.0 or lng != 0.0:
                    print(f"位置: {lat:.6f},{lng:.6f} (来源: {src})")
                    talk.send_location(lat, lng)
                else:
                    print("定位失败")
            elif cmd.startswith('codec '):
                codec = cmd[6:].strip()
                if talk.set_codec(codec):
                    print(f"编码已切换: {codec}")
                else:
                    print("切换失败")
            elif cmd == 'aprs':
                if aprs.is_connected:
                    aprs.stop()
                    print("APRS 已停止")
                else:
                    if aprs.start():
                        print("APRS 上报已启动 (60s 间隔)")
                    else:
                        print("APRS 启动失败")
            else:
                print(f"未知命令: {cmd}")

        except KeyboardInterrupt:
            print("\n使用 'exit' 退出")
        except Exception as e:
            logger.error(f"命令执行错误: {e}")

    # 清理
    aprs.stop()
    location.stop_auto_report()
    talk.stop()
    print("78HAM 客户端已关闭")


if __name__ == "__main__":
    main()
