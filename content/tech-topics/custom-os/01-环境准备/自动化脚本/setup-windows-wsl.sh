#!/bin/bash
# Windows WSL 开发环境自动配置脚本
# 请在 WSL2 Ubuntu 环境中运行

set -e

echo "====================================="
echo "  MyOS 开发环境配置 - Windows WSL"
echo "====================================="
echo ""

# 检查是否在 WSL 中运行
if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo "警告: 似乎不在 WSL 环境中运行。"
    echo "请在 WSL2 Ubuntu 中运行此脚本。"
    echo "继续运行? (y/n)"
    read -r answer
    if [ "$answer" != "y" ]; then
        exit 1
    fi
fi

# 与 Ubuntu 脚本相同的安装步骤
echo "[1/5] 更新系统包..."
sudo apt update -y

echo "[2/5] 安装编译工具链..."
sudo apt install -y build-essential gcc-multilib nasm

echo "[3/5] 安装 QEMU 虚拟机..."
sudo apt install -y qemu-system-x86

echo "[4/5] 安装调试工具..."
sudo apt install -y gdb

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
    echo "所有工具安装成功！"
    echo ""
    echo "提示: Windows 11 WSL2 自带图形支持(WSLg)。"
    echo "Windows 10 用户需要安装 X Server (如 VcXsrv) 来显示 QEMU 窗口。"
else
    echo "部分工具安装失败，请检查错误信息。"
    exit 1
fi
