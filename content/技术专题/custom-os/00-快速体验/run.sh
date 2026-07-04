#!/bin/bash
# MyOS 快速体验运行脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMG_FILE="$SCRIPT_DIR/预编译镜像/os.img"

# 检查QEMU是否安装
if ! command -v qemu-system-x86_64 &> /dev/null; then
    echo "错误: 未找到 qemu-system-x86_64"
    echo ""
    echo "请先安装QEMU:"
    echo "  Ubuntu/Debian: sudo apt install qemu-system-x86"
    echo "  macOS:         brew install qemu"
    echo "  Windows WSL:   sudo apt install qemu-system-x86"
    exit 1
fi

# 检查镜像文件
if [ ! -f "$IMG_FILE" ]; then
    echo "错误: 未找到预编译镜像文件"
    echo "文件路径: $IMG_FILE"
    echo ""
    echo "请确保 预编译镜像/os.img 文件存在。"
    echo "你可以先学习教程，在完成第15章后生成自己的镜像。"
    exit 1
fi

echo "启动 MyOS..."
echo "按 Ctrl+Alt+Q 退出QEMU"
echo ""

qemu-system-x86_64 -drive format=raw,file="$IMG_FILE" -m 128M
