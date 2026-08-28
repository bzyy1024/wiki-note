#ifndef KEYBOARD_H
#define KEYBOARD_H

#include "types.h"

/* 键盘端口 */
#define KEYBOARD_DATA_PORT   0x60
#define KEYBOARD_STATUS_PORT 0x64

/* 特殊键扫描码 */
#define SC_ESC       0x01
#define SC_BACKSPACE 0x0E
#define SC_TAB       0x0F
#define SC_ENTER     0x1C
#define SC_LCTRL     0x1D
#define SC_LSHIFT    0x2A
#define SC_RSHIFT    0x36
#define SC_LALT      0x38
#define SC_SPACE     0x39
#define SC_CAPSLOCK  0x3A

/* 输入缓冲区大小 */
#define KB_BUFFER_SIZE 256

/* 初始化键盘 */
void keyboard_init(void);

/* 从缓冲区读取一个字符（非阻塞，无数据返回0） */
char keyboard_getchar(void);

/* 检查缓冲区是否有数据 */
bool keyboard_has_input(void);

#endif
