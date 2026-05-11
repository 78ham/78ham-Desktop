# 78HAM Desktop 桌面客户端

78HAM  — 基于 Python 的跨平台业余无线电网络对讲应用，本项目适用于 Windows 桌面平台。

基于项目：

[github.com/hicaoc/nrllink](https://github.com/hicaoc/nrllink) — NRLLink 服务端
[github.com/hicaoc/nrllink-mp](https://github.com/hicaoc/nrllink-mp) — NRLLink 微信小程序客户端

## 功能特性

- **PTT 对讲** — 按住说话，支持 G.711 A-law 语音编解码
- **语音通信** — 实时语音传输与接收，网络抖动缓冲
- **频道/房间** — 支持多服务器/多房间切换
- **文本消息** — UTF-8 文本消息收发
- **位置上报** — 多级定位（Windows Location API → IP 地理定位 → 配置默认坐标），支持手动发送与自动上报
- **自动重连** — 连接断开后自动重试
- **双 GUI 框架** — CustomTkinter 现代化界面（默认，暗色/浅色主题切换）+ Tkinter 传统界面（兼容备选）
- **CLI 模式** — 支持纯命令行运行
- **诊断工具** — 内置音频设备测试、协议一致性验证

> **注意：**
> - 本项目目前仍处于测试阶段，仅为学习和研究目的，不建议在生产环境中使用。
> - 目前仅在 Windows 10/11 平台测试通过，其他平台不保证正常运行。
> - 连接到任何业余无线电服务器时，请确保你拥有合法的 Amateur Radio License（业余无线电执照）和有效的 Callsign（呼号）。

## 技术栈

- **语言:** Python 3.8+
- **UI:** CustomTkinter / Tkinter
- **音频:** PyAudio + G.711 A-law 编解码
- **协议:** NRL2（UDP，48 字节头部 + 数据载荷）
- **打包:** PyInstaller（一键构建 exe）

## 项目结构

```
78HAM_Desktop/
├── main.py                  # 主程序入口（CLI 参数解析、GUI 回退逻辑）
├── launcher.py              # GUI 启动器
├── nrl_client.py            # NRL 客户端核心（连接、收发、语音传输）
├── nrl_protocol.py          # NRL2 协议编解码
├── audio_handler.py         # 音频处理（录音/播放、G.711 编解码、抖动缓冲）
├── gui_client_ctk.py        # CustomTkinter 图形界面（默认）
├── gui_client.py            # Tkinter 图形界面（备选）
├── diagnose.py              # 诊断脚本
├── config.yaml              # 配置文件
├── build.ps1                # 一键构建脚本
├── requirements.txt         # Python 依赖
├── LICENSE                  # MIT 许可证
└── README.md                # 自述文件
```

## 使用说明

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 编辑 `config.yaml`，填写服务器地址、呼号等信息

```yaml
servers:
  - name: "示例服务器"
    host: "example.com"
    port: 60050
    password: ""

device:
  callsign: "YOURCALL"   # 呼号
  ssid: 1
  dmr_id: "1234567"      # DMR ID
  password: ""           # 密码（留空则不认证）
  model: 1               # 设备型号
```

3. 启动应用

```bash
# 默认 CustomTkinter GUI
python main.py

# 传统 Tkinter GUI
python main.py --gui tk

# 命令行模式
python main.py --no-gui

# 调试模式
python main.py --debug
```

4. 登录后选择服务器，即可开始对讲

5. 按住 PTT 按钮说话，松开结束

### 命令行参数

| 参数 | 说明 |
|------|------|
| `--config`, `-c` | 指定配置文件路径（默认: `config.yaml`） |
| `--gui ctk\|tk` | 选择 GUI 框架（默认: ctk） |
| `--no-gui` | 命令行界面模式 |
| `--debug` | 启用调试模式 |
| `--test-audio` | 测试音频设备 |
| `--list-audio` | 列出所有音频设备 |

## 编译打包

### 环境要求

- Python 3.10（推荐）
- PyInstaller
- Windows 10/11

### 一键构建

```powershell
.\build.ps1
```

脚本自动完成以下步骤：
1. 激活 conda 环境 `nrllink_3.10`
2. 清理旧的构建输出
3. 通过 PyInstaller 打包为 exe
4. 复制 `config.yaml` 到输出目录
5. 打包为 zip 发布包

生成的 zip 包位于 `build/` 目录。

### 手动构建

```bash
pip install pyinstaller
pyinstaller 78HAM_Client_Preview.spec
```

## 依赖

| 依赖 | 说明 |
|------|------|
| `pyaudio` | 音频采集与播放（底层依赖 PortAudio） |
| `pyyaml` | 配置文件解析 |
| `numpy` | 音频数据处理 |
| `customtkinter` | 现代化 GUI 框架（可选，未安装时自动回退到 Tkinter） |
| `requests` | IP 地理定位回退方案 |
| `winrt-Windows-Devices-Geolocation` | Windows Location API，GPS 定位（可选，仅 Windows） |

## License

MIT License — 详见 [LICENSE](LICENSE) 文件。
