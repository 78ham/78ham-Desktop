# 78HAM Desktop 桌面客户端

78HAM — 基于 Python 的跨平台业余无线电网络对讲应用

基于项目：

[github.com/hicaoc/nrllink](https://github.com/hicaoc/nrllink) — NRLLink 服务端
[github.com/hicaoc/nrllink-mp](https://github.com/hicaoc/nrllink-mp) — NRLLink 微信小程序客户端

## 功能特性

- **PTT 对讲** — 按住说话，支持 G.711 A-law / Opus 双编码
- **语音通信** — 实时语音传输与接收，网络抖动缓冲
- **音频设备选择** — 运行时切换麦克风/扬声器设备
- **Opus 码率配置** — 支持 16~64 kbps 码率运行时切换
- **尾音功能** — PTT 松开后自动发送尾音，支持三种模式：
  - 默认尾音：DTMF "91" 双音提示
  - 自定义尾音：导入 WAV/PCM 音频文件
  - MDC 尾音：MDC1200 PTT ID 信令，可自定义设备 ID
- **MDC1200 信令** — PTT ID、呼叫、紧急告警等带内 FSK 信令
- **频道/房间** — 多服务器/多房间切换
- **文本消息** — UTF-8 文本消息收发
- **位置上报** — 多级定位（GPS → IP → 默认坐标），自动定时上报
- **HTTP API** — 登录认证、房间列表、设备管理
- **全局热键** — F5 一键 PTT（可自定义）
- **自动重连** — 连接断开后自动重试
- **GUI + CLI** — CustomTkinter 现代界面 / 纯命令行模式

> **注意：**
> - 本项目仍处于测试阶段，仅供学习和研究。
> - 目前仅在 Windows 10/11 测试通过。
> - 连接业余无线电服务器时，请确保持有合法的业余无线电执照和有效呼号。

## 技术栈

- **语言:** Python 3.10+
- **UI:** CustomTkinter（暗色主题）
- **音频:** PyAudio + G.711 A-law / Opus 编解码
- **协议:** NRL2（UDP 48 字节头部 + 载荷）
- **网络:** HTTP REST API
- **打包:** PyInstaller

## 项目结构

```
78ham-Desktop/
├── main.py                         # 入口（GUI / CLI）
├── core/                           # 协议层
│   ├── protocol.py                 #   数据结构、常量、PacketType
│   ├── codec.py                    #   G.711 / Opus 编解码器
│   ├── packet_factory.py           #   构包
│   └── packet_parser.py            #   解包
├── config/
│   └── settings.py                 #   YAML 配置加载
├── network/                        # 网络层
│   ├── udp_client.py               #   UDP 收发 + 心跳 + 重连
│   ├── connection_manager.py       #   连接状态机
│   └── api_client.py               #   HTTP REST API 客户端
├── services/                       # 业务层
│   ├── talk_service.py             #   核心编排（语音/文本/PTT）
│   ├── room_service.py             #   房间管理
│   ├── location_service.py         #   定位 + 自动上报
│   ├── tail_tone_service.py        #   尾音服务（DTMF/自定义/MDC）
│   └── mdc1200.py                  #   MDC1200 信令编码器
├── audio/                          # 音频
│   ├── audio_handler.py            #   PyAudio 录放音
│   └── audio_manager.py            #   封装层
├── ptt/
│   └── hotkey.py                   #   全局热键 PTT
├── ui/                             # GUI
│   ├── theme.py                    #   样式常量
│   ├── app.py                      #   主窗口
│   └── components/                 #   独立组件
│       ├── status_bar.py
│       ├── ptt_button.py
│       ├── chat_panel.py
│       ├── room_selector.py
│       ├── audio_panel.py
│       └── config_dialog.py
├── libs/                           # 本地 DLL（opus.dll 等）
├── utils/                          # 工具（预留）
├── config.yaml                     # 配置文件（gitignore）
├── requirements.txt                # 依赖
├── build.ps1                       # 构建脚本
├── 78HAM.spec                      # PyInstaller 打包配置
└── LICENSE                         # MIT
```

## 使用说明

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml`：

```yaml
servers:
  - name: "示例服务器"
    host: "example.com"
    port: 60050
    password: ""

device:
  callsign: "YOURCALL"
  ssid: 1
  dmr_id: "1234567"
  password: ""

audio:
  codec: "g711"        # g711 或 opus
  sample_rate: 8000    # g711=8000, opus=16000
  opus_bitrate: 36000  # Opus 码率 (bps)，范围 16000~64000

tail_tone:
  enabled: false           # 是否启用尾音
  tail_type: "default"     # default(91双音) / custom(自定义文件) / mdc(MDC1200信令)
  custom_file: ""          # 自定义尾音文件路径 (WAV/PCM)
  mdc_id: 0                # MDC 设备 ID (0 表示使用 device.dmr_id)
  amplitude: 0.2           # MDC 尾音音量 (0.05~1.0)

location:
  auto_report: true
  report_interval: 120
```

### 3. 启动

```bash
# GUI 模式（默认）
python main.py

# 命令行模式
python main.py --no-gui

# 调试模式
python main.py --debug

# 列出音频设备
python main.py --list-audio
```

### CLI 命令

| 命令 | 说明 |
|------|------|
| `connect` | 连接服务器 |
| `disconnect` | 断开连接 |
| `status` | 查看状态 |
| `send <msg>` | 发送文本消息 |
| `rooms` | 获取房间列表 |
| `join <id>` | 加入房间 |
| `loc` | 获取并发送位置 |
| `codec <g711\|opus>` | 切换编码 |
| `exit` | 退出 |

### 命令行参数

| 参数 | 说明 |
|------|------|
| `--config`, `-c` | 配置文件路径（默认: `config.yaml`） |
| `--no-gui` | 命令行模式 |
| `--debug` | 调试日志 |
| `--test-audio` | 测试音频设备 |
| `--list-audio` | 列出音频设备 |

## 编译打包

```powershell
.\build.ps1
```

或手动：

```bash
pip install pyinstaller
pyinstaller 78HAM.spec
```

## 依赖

| 包 | 说明 |
|------|------|
| `pyaudio` | 音频 I/O |
| `pyyaml` | 配置解析 |
| `numpy` | 音频处理 |
| `customtkinter` | GUI（可选，未安装回退 CLI） |
| `requests` | HTTP API + IP 定位（可选） |
| `keyboard` | 全局热键（可选，仅 Windows） |
| `opuslib` | 原生 Opus 绑定（可选） |
| `av` | PyAV/FFmpeg Opus 支持（可选） |
| `winrt-Windows.Devices.Geolocation` | GPS 定位（可选，仅 Windows） |

## 近期更新

### 2026-05-17

- **移除麦克风增益功能** — 删除软件增益控制（`mic_gain`），相关 UI 滑块、配置项、代码全部移除
- **新增 Opus 码率配置** — 支持 16/24/32/36/48/64 kbps 码率运行时切换，配置持久化到 `config.yaml`
- **新增音频设备选择** — 音频面板新增麦克风/扬声器下拉菜单，支持运行时切换输入/输出设备
- **修复 PTT 按钮行为** — 改用全局鼠标释放事件，解决鼠标移出按钮区域后松开无法停止发射的问题
- **改进音频缓冲** — 修正 `frames_per_buffer` 计算，统一使用 20ms 帧大小（采样率 × 0.02）
- **优化 Opus DLL 加载** — 自动搜索 `libs/` 目录，支持 PyInstaller 打包后的路径解析
- **自动获取房间列表** — 连接和重连成功后自动拉取可用房间列表
- **改进编码切换逻辑** — 增加 Opus 可用性检查、发射状态检查等前置校验，提供更详细的错误提示
- **构建配置更新** — `78HAM.spec` 中将 `libs/opus.dll` 加入打包二进制文件
- **AudioManager API 扩展** — 新增 `get_input_devices()`、`get_output_devices()`、`set_input_device()`、`set_output_device()` 等设备管理方法

## License

MIT License — 详见 [LICENSE](LICENSE)
