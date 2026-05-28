# 78HAM Desktop

> 基于 Python 的跨平台业余无线电网络对讲客户端，支持 NRL2 协议

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey.svg)]()

78HAM Desktop 是一款轻量级业余无线电网络对讲应用，通过 UDP 与 NRLLink 服务器通信，实现语音/文本消息的实时收发。支持 G.711 A-law 和 Opus 双编码，提供现代化 GUI 界面和纯 CLI 两种使用方式。

**相关项目：**

- [nrllink](https://github.com/hicaoc/nrllink) — NRLLink 服务端
- [nrllink-mp](https://github.com/hicaoc/nrllink-mp) — NRLLink 微信小程序客户端

---

## 功能特性

| 功能 | 说明 |
|------|------|
| **PTT 对讲** | 按住说话，支持 G.711 A-law / Opus 双编码 |
| **尾音功能** | DTMF "91" 双音 / 自定义 WAV 文件 / MDC1200 信令 |
| **MDC1200 信令** | PTT ID、呼叫、紧急告警等带内 FSK 信令 |
| **音频设备选择** | 运行时切换麦克风/扬声器，Opus 码率 16~64 kbps |
| **频道/房间** | 多服务器、多房间切换 |
| **文本消息** | UTF-8 文本消息收发 |
| **位置上报** | GPS → IP → 默认坐标多级定位，自动定时上报 |
| **全局热键** | F5 一键 PTT（可自定义），支持 Windows / Linux |
| **自动重连** | 连接断开后自动重试 |
| **双模式** | CustomTkinter 暗色主题 GUI / 纯命令行 CLI |

---

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourname/78HAM-Desktop.git
cd 78HAM-Desktop/78ham-Desktop

# 安装依赖
pip install -r requirements.txt
```

<details>
<summary>Linux 额外依赖（Ubuntu/Debian）</summary>

```bash
sudo apt-get install python3 python3-pip python3-tk portaudio19-dev
pip3 install -r requirements.txt
```
</details>

### 配置

复制并编辑配置文件：

```bash
cp config.example.yaml config.yaml
```

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
  sample_rate: 8000
  opus_bitrate: 36000  # 16000~64000 bps
```

### 启动

```bash
python main.py            # GUI 模式
python main.py --no-gui   # 命令行模式
python main.py --debug    # 调试模式
python main.py --list-audio  # 列出音频设备
```

---

## 命令行用法

### 启动参数

| 参数 | 说明 |
|------|------|
| `--config`, `-c` | 指定配置文件路径（默认: `config.yaml`） |
| `--no-gui` | 纯命令行模式 |
| `--debug` | 启用调试日志 |
| `--test-audio` | 测试音频设备 |
| `--list-audio` | 列出所有音频设备 |

### CLI 命令

| 命令 | 说明 |
|------|------|
| `connect` | 连接服务器 |
| `disconnect` | 断开连接 |
| `status` | 查看当前状态 |
| `send <msg>` | 发送文本消息 |
| `rooms` | 获取房间列表 |
| `join <id>` | 加入指定房间 |
| `loc` | 获取并发送位置 |
| `codec <g711\|opus>` | 切换编码格式 |
| `exit` | 退出程序 |

---

## 编译打包

### Windows

```powershell
.\build.ps1
```

或手动使用 PyInstaller：

```bash
pip install pyinstaller
pyinstaller 78HAM.spec
```

### Linux

```bash
# 构建可执行文件
chmod +x build.sh
./build.sh

# 打包 deb/rpm（需要 fpm）
chmod +x package.sh
./package.sh

# 安装
sudo dpkg -i dist/78HAM_*.deb    # Debian/Ubuntu
sudo rpm -i dist/78HAM_*.rpm     # Fedora/RHEL
```

---

## 项目结构

```
78ham-Desktop/
├── main.py                 # 程序入口
├── core/                   # 协议层 — NRL2 数据结构与编解码
├── config/                 # YAML 配置加载
├── network/                # 网络层 — UDP 收发、连接管理、REST API
├── services/               # 业务层 — PTT 编排、房间、定位、MDC1200
├── audio/                  # 音频 — PyAudio 录放音封装
├── ptt/                    # 全局热键 PTT 控制器
├── ui/                     # GUI — CustomTkinter 暗色主题界面
│   └── components/         #   独立 UI 组件
├── libs/                   # 本地动态库（opus.dll / libopus.so）
├── debian/                 # Linux 打包配置
├── config.yaml             # 运行时配置（已 gitignore）
├── requirements.txt        # Python 依赖
├── build.ps1               # Windows 构建脚本
├── build.sh                # Linux 构建脚本
├── package.sh              # Linux fpm 打包脚本
└── 78HAM.spec              # PyInstaller 打包配置
```

---

## 依赖说明

| 包 | 用途 | 是否必须 |
|----|------|----------|
| `pyaudio` | 音频 I/O | 是 |
| `pyyaml` | 配置解析 | 是 |
| `numpy` | 音频处理 | 是 |
| `customtkinter` | GUI 界面 | 否（未安装回退 CLI） |
| `requests` | HTTP API + IP 定位 | 否 |
| `keyboard` | 全局热键（Windows） | 否 |
| `pynput` | 全局热键（Linux） | 否 |
| `opuslib` | 原生 Opus 编解码 | 否 |
| `av` | PyAV/FFmpeg Opus 支持 | 否 |
| `winrt-Windows.Devices.Geolocation` | GPS 定位（Windows） | 否 |

---

## 相关资源

- [NRLLink 服务端](https://github.com/hicaoc/nrllink)
- [NRLLink 微信小程序客户端](https://github.com/hicaoc/nrllink-mp)

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

> **注意：** 连接业余无线电服务器时，请确保持有合法的业余无线电执照和有效呼号。本项目仅供学习和研究用途。
