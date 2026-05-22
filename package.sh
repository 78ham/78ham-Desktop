#!/usr/bin/env bash
set -euo pipefail

# 78HAM Desktop Linux 打包脚本
# 使用 fpm 将 PyInstaller 输出打包为 deb/rpm
#
# 依赖:
#   - Ruby: sudo apt-get install ruby
#   - fpm: sudo gem install fpm
#   - PyInstaller 输出: 先运行 ./build.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="78ham-desktop"
VERSION="2.1.0"
ITERATION="1"
MAINTAINER="78HAM Team <dev@78ham.com>"
DESCRIPTION="78HAM 业余无线电 PTT 对讲客户端"
URL="https://github.com/78HAM/78ham-Desktop"
LICENSE="MIT"
CATEGORY="hamradio"

DIST_DIR="$SCRIPT_DIR/dist/78HAM"
INSTALL_DIR="/opt/78ham-desktop"

# 检查构建输出
if [ ! -d "$DIST_DIR" ]; then
    echo "错误: dist/78HAM 目录不存在"
    echo "请先运行: ./build.sh"
    exit 1
fi

# 检查 fpm
if ! command -v fpm &>/dev/null; then
    echo "错误: 未找到 fpm"
    echo "请安装: sudo apt-get install ruby && sudo gem install fpm"
    exit 1
fi

echo ""
echo "  78HAM Desktop 打包"
echo "  Version: $VERSION-$ITERATION"
echo ""

# 构建 deb 包
echo "[1/2] 构建 deb 包..."
fpm -s dir -t deb \
    --name "$APP_NAME" \
    --version "$VERSION" \
    --iteration "$ITERATION" \
    --maintainer "$MAINTAINER" \
    --description "$DESCRIPTION" \
    --url "$URL" \
    --license "$LICENSE" \
    --category "$CATEGORY" \
    --depends "libportaudio2" \
    --depends "libopus0" \
    --depends "python3-tk" \
    --after-install "$SCRIPT_DIR/debian/postinst" \
    --before-remove "$SCRIPT_DIR/debian/prerm" \
    --config-files "/opt/78ham-desktop/config.yaml" \
    --package "$SCRIPT_DIR/dist/" \
    "$DIST_DIR/=$INSTALL_DIR/"

# 构建 rpm 包
echo "[2/2] 构建 rpm 包..."
fpm -s dir -t rpm \
    --name "$APP_NAME" \
    --version "$VERSION" \
    --iteration "$ITERATION" \
    --maintainer "$MAINTAINER" \
    --description "$DESCRIPTION" \
    --url "$URL" \
    --license "$LICENSE" \
    --category "$CATEGORY" \
    --depends "portaudio" \
    --depends "opus" \
    --package "$SCRIPT_DIR/dist/" \
    "$DIST_DIR/=$INSTALL_DIR/"

echo ""
echo "  打包完成!"
echo ""
ls -lh "$SCRIPT_DIR/dist/"*.deb "$SCRIPT_DIR/dist/"*.rpm 2>/dev/null || echo "请检查 dist/ 目录"
echo ""
