#!/bin/bash
# Ubuntu/Debian 开发环境自动配置脚本

set -e

echo "====================================="
echo "  MyOS 开发环境配置 - Ubuntu/Debian"
echo "====================================="
echo ""

# 更新包管理器
echo "[1/5] 更新系统包..."
sudo apt update -y

# 安装编译工具链
echo "[2/5] 安装编译工具链..."
sudo apt install -y build-essential gcc-multilib nasm

# 安装 QEMU
echo "[3/5] 安装 QEMU 虚拟机..."
sudo apt install -y qemu-system-x86

# 安装调试工具
echo "[4/5] 安装调试工具..."
sudo apt install -y gdb

# 安装辅助工具
echo "[5/5] 安装辅助工具..."
sudo apt install -y mtools

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
check_tool gcc
check_tool nasm
check_tool qemu-system-x86_64
check_tool make
check_tool gdb

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "所有工具安装成功！可以开始学习了。"
else
    echo "部分工具安装失败，请检查错误信息。"
    exit 1
fi
