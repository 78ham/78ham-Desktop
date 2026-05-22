#!/usr/bin/env bash
set -euo pipefail

# 78HAM Desktop Linux 平台功能测试脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=== 78HAM Desktop Linux 平台功能测试 ==="
echo ""

# 1. Python 环境
echo "[1/6] 检查 Python 环境..."
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
    exit 1
fi
echo "  $PY_VER ($PYTHON_EXE)"

# 2. 依赖检查
echo "[2/6] 检查 Python 依赖..."
MISSING_PY_DEPS=()

if ! "$PYTHON_EXE" -c "import pyaudio" 2>/dev/null; then
    MISSING_PY_DEPS+=("pyaudio")
fi
if ! "$PYTHON_EXE" -c "import yaml" 2>/dev/null; then
    MISSING_PY_DEPS+=("pyyaml")
fi
if ! "$PYTHON_EXE" -c "import numpy" 2>/dev/null; then
    MISSING_PY_DEPS+=("numpy")
fi
if ! "$PYTHON_EXE" -c "import customtkinter" 2>/dev/null; then
    MISSING_PY_DEPS+=("customtkinter")
fi
if ! "$PYTHON_EXE" -c "import pynput" 2>/dev/null; then
    MISSING_PY_DEPS+=("pynput")
fi

if [ ${#MISSING_PY_DEPS[@]} -gt 0 ]; then
    echo "  警告: 缺少以下 Python 依赖:"
    for dep in "${MISSING_PY_DEPS[@]}"; do
        echo "    - $dep"
    done
    echo "  请运行: $PYTHON_EXE -m pip install -r requirements.txt"
else
    echo "  所有 Python 依赖已安装: OK"
fi

# 3. 平台检测
echo "[3/6] 检查平台适配..."
"$PYTHON_EXE" -c "
import sys
sys.path.insert(0, '.')
from core.protocol import get_default_dev_model, DevModel
model = get_default_dev_model()
expected = DevModel.LINUX if sys.platform == 'linux' else DevModel.WINDOWS
if model == expected:
    print(f'  平台模型: {model} ({"LINUX" if model == 104 else "WINDOWS"}={model}) OK')
else:
    print(f'  错误: 期望 {expected}, 实际 {model}')
    sys.exit(1)
" 2>/dev/null || echo "  警告: 无法导入 core.protocol（可能需要安装依赖）"

# 4. Opus 加载
echo "[4/6] 检查 Opus 库..."
"$PYTHON_EXE" -c "
import ctypes.util
lib = ctypes.util.find_library('opus')
if lib:
    print(f'  libopus: {lib} OK')
else:
    print('  libopus: NOT FOUND (将回退到 G.711)')
" 2>/dev/null || echo "  警告: 无法检查 Opus 库"

# 5. 热键
echo "[5/6] 检查 PTT 热键..."
"$PYTHON_EXE" -c "
import sys
sys.path.insert(0, '.')
from ptt.hotkey import PttController
ctrl = PttController(on_press=lambda: None, on_release=lambda: None)
print('  PttController: OK')
" 2>/dev/null || echo "  警告: 无法导入 ptt.hotkey"

# 6. 音频设备
echo "[6/6] 检查音频设备..."
if [ -f "$SCRIPT_DIR/main.py" ]; then
    "$PYTHON_EXE" "$SCRIPT_DIR/main.py" --list-audio 2>/dev/null || echo "  警告: 无法列出音频设备"
else
    echo "  警告: 未找到 main.py"
fi

echo ""
echo "=== 测试完成 ==="
echo ""
echo "如果所有检查通过，可以运行以下命令构建:"
echo "  ./build.sh"
echo "  ./package.sh"
echo ""
