# 第1章：环境准备

> 搭建完整的操作系统开发环境

## 学习目标

1. 安装所有必需的开发工具
2. 了解每个工具的作用
3. 验证环境配置正确
4. 配置代码编辑器

## 预计时间

⏱️ 1-2小时

## 前置要求

- 一台运行 Linux、macOS 或 Windows（WSL）的电脑
- 基本的命令行操作能力

## 需要的工具

| 工具 | 版本要求 | 作用 |
|------|---------|------|
| GCC | 9.0+ | C语言编译器 |
| NASM | 2.14+ | x86汇编器 |
| QEMU | 4.0+ | 虚拟机（测试OS） |
| Make | 4.0+ | 构建自动化 |
| GDB | 8.0+ | 调试器 |
| 编辑器 | - | VSCode / Vim / Emacs |

## 配置方式

你可以选择以下任一方式：

### 方式一：手动配置（推荐新手）

→ 详见 [手动配置指南.md](手动配置指南.md)

### 方式二：自动化脚本

```bash
# Ubuntu/Debian
./自动化脚本/setup-ubuntu.sh

# macOS
./自动化脚本/setup-macos.sh

# Windows WSL
./自动化脚本/setup-windows-wsl.sh
```

### 方式三：Docker环境

```bash
docker-compose up -d
docker exec -it os-dev bash
```

→ 详见 [Dockerfile](Dockerfile) 和 [docker-compose.yml](docker-compose.yml)

## 验证安装

所有工具安装完成后，运行验证：

```bash
# 检查各工具版本
gcc --version
nasm --version
qemu-system-x86_64 --version
make --version
gdb --version
```

所有命令都应该正常输出版本信息。

## 成果检查

- ✅ GCC 能正常编译C程序
- ✅ NASM 能正常汇编
- ✅ QEMU 能正常启动
- ✅ Make 能正常构建
- ✅ 编辑器配置完成

## 常见问题

→ 详见 [常见问题.md](常见问题.md)

## 下一步

环境准备好后，前往 [02-基础知识](../02-基础知识/README.md) 学习必备的前置知识。
