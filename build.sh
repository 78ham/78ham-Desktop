#!/usr/bin/env bash
set -euo pipefail

# 78HAM Desktop Linux Build Script
# 用法: ./build.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPEC_FILE="$SCRIPT_DIR/78HAM.spec"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
APP_NAME="78HAM"
VERSION="2.1.0"

echo ""
echo "  78HAM Desktop Build (Linux)"
echo "  Version: $VERSION"
echo ""

# 1. 检查环境
echo "[1/6] 检查环境..."
PYTHON_EXE=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" --version 2>&1)
        if [[ "$PY_VER" == Python\ 3.* ]]; then
            PYTHON_EXE="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXE" ]; then
    echo "  错误: 未找到 Python 3"
    echo "  请安装: sudo apt-get install python3 python3-pip python3-tk"
    exit 1
fi
echo "  Python: $PY_VER ($PYTHON_EXE)"

# 检查 PyInstaller
if ! "$PYTHON_EXE" -c "import PyInstaller" 2>/dev/null; then
    echo "  错误: 未找到 PyInstaller"
    echo "  请安装: $PYTHON_EXE -m pip install pyinstaller"
    exit 1
fi
echo "  PyInstaller: OK"

# 检查系统依赖
echo "  检查系统库..."
MISSING_DEPS=()
if ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
    MISSING_DEPS+=("libportaudio2 (apt: sudo apt-get install libportaudio2)")
fi
if ! ldconfig -p 2>/dev/null | grep -q libopus; then
    MISSING_DEPS+=("libopus0 (apt: sudo apt-get install libopus0)")
fi
if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "  警告: 缺少以下系统库:"
    for dep in "${MISSING_DEPS[@]}"; do
        echo "    - $dep"
    done
    echo "  继续构建..."
fi

# 2. 清理
echo "[2/6] 清理旧文件..."
rm -rf "$BUILD_DIR"
rm -rf "$DIST_DIR/$APP_NAME"

# 3. 构建
echo "[3/6] 使用 PyInstaller 构建..."
cd "$SCRIPT_DIR"
"$PYTHON_EXE" -m PyInstaller --clean "$SPEC_FILE"
if [ $? -ne 0 ]; then
    echo "  构建失败!"
    exit 1
fi

# 4. 复制配置模板和 .desktop 文件
echo "[4/6] 复制资源文件..."
CONFIG_PATH="$DIST_DIR/$APP_NAME/config.yaml"
cat > "$CONFIG_PATH" << 'YAML_EOF'
# 78HAM 配置文件
servers:
  - name: "示例服务器"
    host: ""
    port: 60050
    password: ""

device:
  callsign: "N0CALL"
  ssid: 1
  dmr_id: "123456"
  password: ""

audio:
  codec: "g711"
  sample_rate: 8000
  opus_bitrate: 36000

tail_tone:
  enabled: false
  tail_type: "default"
  custom_file: ""
  mdc_id: 0
  amplitude: 0.2

network:
  heartbeat_interval: 2
  buffer_size: 4096

location:
  auto_report: true
  report_interval: 120
  default_lat: 0.0
  default_lng: 0.0
YAML_EOF

# 复制 .desktop 文件
if [ -f "$SCRIPT_DIR/78HAM.desktop" ]; then
    cp "$SCRIPT_DIR/78HAM.desktop" "$DIST_DIR/$APP_NAME/"
fi

# 5. 设置权限
echo "[5/6] 设置权限..."
chmod +x "$DIST_DIR/$APP_NAME/78HAM"

# 6. 打包
echo "[6/6] 打包..."
TARBALL="$DIST_DIR/${APP_NAME}_v${VERSION}_linux.tar.gz"
cd "$DIST_DIR"
tar czf "$TARBALL" "$APP_NAME"

APP_SIZE=$(du -sh "$DIST_DIR/$APP_NAME" | cut -f1)
TARBALL_SIZE=$(du -sh "$TARBALL" | cut -f1)

echo ""
echo "  构建完成!"
echo "  应用大小: $APP_SIZE"
echo "  压缩包  : $TARBALL_SIZE"
echo "  输出目录: dist/$APP_NAME/"
echo "  压缩包  : $TARBALL"
echo ""

cd "$SCRIPT_DIR"
