#!/bin/bash
# macOS 开发环境自动配置脚本

set -e

echo "====================================="
echo "  MyOS 开发环境配置 - macOS"
echo "====================================="
echo ""

# 检查 Homebrew
if ! command -v brew &> /dev/null; then
    echo "[0/4] 安装 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 安装交叉编译工具链
echo "[1/4] 安装交叉编译工具链..."
brew install i686-elf-gcc i686-elf-binutils

# 安装 NASM
echo "[2/4] 安装 NASM..."
brew install nasm

# 安装 QEMU
echo "[3/4] 安装 QEMU..."
brew install qemu

# 安装 GDB
echo "[4/4] 安装 GDB..."
brew install gdb

echo ""
echo "====================================="
echo "  验证安装"
echo "====================================="

check_tool() {
    if command -v "$1" &> /dev/null; then
        echo "  ✓ $1: $($1 --version 2>&1 | head -1)"
    else
        echo "  ✗ $1: 未找到"
        FAILED=1
    fi
}

FAILED=0
check_tool i686-elf-gcc
check_tool nasm
check_tool qemu-system-x86_64
check_tool make
check_tool gdb

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "所有工具安装成功！"
    echo ""
    echo "注意: macOS 上请使用 i686-elf-gcc 替代 gcc"
else
    echo "部分工具安装失败，请检查错误信息。"
    exit 1
fi
