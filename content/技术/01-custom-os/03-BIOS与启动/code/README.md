# 第3章代码 - 最简单的引导扇区

## 文件说明

| 文件 | 说明 |
|------|------|
| `boot.asm` | 引导扇区汇编源码 |
| `Makefile` | 构建脚本 |

## 编译

```bash
make
```

将生成 `boot.bin`（512字节的引导扇区映像）。

## 运行

```bash
make run
```

QEMU将启动并显示字符 `A`。

## 调试

```bash
# 启动QEMU并等待GDB连接
make debug

# 在另一个终端
gdb
(gdb) target remote localhost:1234
(gdb) break *0x7C00
(gdb) continue
(gdb) info registers
```

## 验证

编译后可以查看二进制内容：

```bash
make hexdump
```

你应该看到：
- 开头是你的代码
- 中间填充了0
- 最后两字节是 `55 AA`（引导签名）
