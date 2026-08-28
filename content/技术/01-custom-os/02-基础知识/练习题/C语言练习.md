# C语言练习

## 🟢 基础练习

### 练习1：指针操作

写出以下代码的输出结果：

```c
#include <stdio.h>
#include <stdint.h>

int main() {
    uint8_t data[] = {0x41, 0x0F, 0x42, 0x0A};

    // 按 uint8_t 读取
    printf("data[0] = 0x%02X\n", data[0]);  // ?
    printf("data[1] = 0x%02X\n", data[1]);  // ?

    // 按 uint16_t 读取（注意字节序）
    uint16_t *ptr16 = (uint16_t*)data;
    printf("ptr16[0] = 0x%04X\n", ptr16[0]);  // ?
    printf("ptr16[1] = 0x%04X\n", ptr16[1]);  // ?

    return 0;
}
```

### 练习2：实现 memset

```c
void *my_memset(void *ptr, int value, uint32_t size) {
    // 在这里实现
}
```

**测试：**
```c
char buf[10];
my_memset(buf, 'A', 10);
// buf 应该全部是 'A'
```

### 练习3：位运算

回答以下问题：

```c
uint8_t flags = 0b10110100;

// 1. flags & 0x0F 的结果是？
// 2. flags | 0x01 的结果是？
// 3. flags >> 4 的结果是？
// 4. 如何检查第5位(从0开始)是否为1？
// 5. 如何只将第2位设为0，其他位不变？
```

## 🟡 进阶练习

### 练习4：packed 结构体

```c
#include <stdio.h>
#include <stdint.h>

struct A {
    uint8_t  x;
    uint32_t y;
    uint8_t  z;
};

struct __attribute__((packed)) B {
    uint8_t  x;
    uint32_t y;
    uint8_t  z;
};

int main() {
    printf("sizeof(A) = %lu\n", sizeof(struct A));  // ?
    printf("sizeof(B) = %lu\n", sizeof(struct B));  // ?
    return 0;
}
```

1. 写出两个 sizeof 的结果
2. 解释为什么不同
3. 什么场景下必须用 packed？

### 练习5：实现简单的 itoa

实现将整数转换为字符串的函数（不使用标准库）：

```c
// 将整数转为十进制字符串
// 返回写入的字符数
int my_itoa(int value, char *buffer) {
    // 在这里实现
}
```

## 🔴 挑战练习

### 练习6：模拟VGA输出

编写一个程序，模拟VGA文本模式的显存操作：

```c
#include <stdint.h>

// 模拟80x25的VGA显存
uint16_t fake_vga[80 * 25];

// 实现以下函数
void vga_clear(void);
void vga_putchar(int x, int y, char c, uint8_t color);
void vga_print(int x, int y, const char *str, uint8_t color);
void vga_dump(void);  // 打印显存内容到标准输出
```

**测试：**
```c
vga_clear();
vga_print(0, 0, "Hello, OS!", 0x0F);
vga_dump();
```
