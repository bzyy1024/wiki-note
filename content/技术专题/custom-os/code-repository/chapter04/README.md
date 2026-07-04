# 第4章代码 - Bootloader

## 文件说明

| 文件 | 说明 |
|------|------|
| `boot.asm` | 主引导程序 |
| `print.asm` | 字符串打印函数 |
| `disk.asm` | 磁盘读取函数 |
| `Makefile` | 构建脚本 |

## 编译和运行

```bash
make        # 编译
make run    # 在QEMU中运行
```

## 预期输出

```
Booting MyOS...
Kernel loaded!
```
