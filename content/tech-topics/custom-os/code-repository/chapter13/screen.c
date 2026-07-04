#include "screen.h"
#include "port.h"

static uint16_t *video_memory = (uint16_t*)VGA_MEMORY;
static int cursor_x = 0;
static int cursor_y = 0;
static uint8_t current_color = 0x0F;  /* 白色前景，黑色背景 */

static inline uint8_t make_color(uint8_t fg, uint8_t bg) {
    return fg | (bg << 4);
}

static inline uint16_t make_vgaentry(char c, uint8_t color) {
    return (uint16_t)c | ((uint16_t)color << 8);
}

/* 更新硬件光标位置 */
static void update_cursor(void) {
    uint16_t pos = cursor_y * VGA_WIDTH + cursor_x;
    outb(0x3D4, 14);
    outb(0x3D5, (uint8_t)(pos >> 8));
    outb(0x3D4, 15);
    outb(0x3D5, (uint8_t)(pos & 0xFF));
}

/* 滚屏：所有内容上移一行 */
static void scroll(void) {
    /* 将第1行到最后一行复制到第0行到倒数第二行 */
    for (int y = 0; y < VGA_HEIGHT - 1; y++) {
        for (int x = 0; x < VGA_WIDTH; x++) {
            video_memory[y * VGA_WIDTH + x] =
                video_memory[(y + 1) * VGA_WIDTH + x];
        }
    }

    /* 清空最后一行 */
    for (int x = 0; x < VGA_WIDTH; x++) {
        video_memory[(VGA_HEIGHT - 1) * VGA_WIDTH + x] =
            make_vgaentry(' ', current_color);
    }

    cursor_y = VGA_HEIGHT - 1;
}

void screen_init(void) {
    cursor_x = 0;
    cursor_y = 0;
    current_color = make_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);
    screen_clear();
}

void screen_clear(void) {
    for (int y = 0; y < VGA_HEIGHT; y++) {
        for (int x = 0; x < VGA_WIDTH; x++) {
            video_memory[y * VGA_WIDTH + x] = make_vgaentry(' ', current_color);
        }
    }
    cursor_x = 0;
    cursor_y = 0;
    update_cursor();
}

void screen_putchar(char c) {
    if (c == '\n') {
        cursor_x = 0;
        cursor_y++;
    } else if (c == '\r') {
        cursor_x = 0;
    } else if (c == '\t') {
        cursor_x = (cursor_x + 8) & ~7;
    } else if (c == '\b') {
        if (cursor_x > 0) {
            cursor_x--;
            int idx = cursor_y * VGA_WIDTH + cursor_x;
            video_memory[idx] = make_vgaentry(' ', current_color);
        }
    } else {
        int idx = cursor_y * VGA_WIDTH + cursor_x;
        video_memory[idx] = make_vgaentry(c, current_color);
        cursor_x++;
    }

    /* 换行检查 */
    if (cursor_x >= VGA_WIDTH) {
        cursor_x = 0;
        cursor_y++;
    }

    /* 滚屏检查 */
    if (cursor_y >= VGA_HEIGHT) {
        scroll();
    }

    update_cursor();
}

void screen_puts(const char *str) {
    for (int i = 0; str[i] != '\0'; i++) {
        screen_putchar(str[i]);
    }
}

void screen_set_color(uint8_t fg, uint8_t bg) {
    current_color = make_color(fg, bg);
}

/* 简易printf实现（支持 %s, %d, %x, %c） */
void screen_printf(const char *format, ...) {
    /* 使用GCC内建的可变参数机制 */
    __builtin_va_list args;
    __builtin_va_start(args, format);

    for (int i = 0; format[i] != '\0'; i++) {
        if (format[i] == '%' && format[i + 1] != '\0') {
            i++;
            switch (format[i]) {
                case 's': {
                    const char *s = __builtin_va_arg(args, const char*);
                    if (s) screen_puts(s);
                    else screen_puts("(null)");
                    break;
                }
                case 'c': {
                    char c = (char)__builtin_va_arg(args, int);
                    screen_putchar(c);
                    break;
                }
                case 'd': {
                    int val = __builtin_va_arg(args, int);
                    if (val < 0) {
                        screen_putchar('-');
                        val = -val;
                    }
                    if (val == 0) {
                        screen_putchar('0');
                    } else {
                        char buf[12];
                        int pos = 0;
                        while (val > 0) {
                            buf[pos++] = '0' + (val % 10);
                            val /= 10;
                        }
                        for (int j = pos - 1; j >= 0; j--) {
                            screen_putchar(buf[j]);
                        }
                    }
                    break;
                }
                case 'x': {
                    uint32_t val = __builtin_va_arg(args, uint32_t);
                    screen_puts("0x");
                    char hex[] = "0123456789ABCDEF";
                    int started = 0;
                    for (int j = 28; j >= 0; j -= 4) {
                        uint8_t nibble = (val >> j) & 0xF;
                        if (nibble || started || j == 0) {
                            screen_putchar(hex[nibble]);
                            started = 1;
                        }
                    }
                    break;
                }
                case '%':
                    screen_putchar('%');
                    break;
                default:
                    screen_putchar('%');
                    screen_putchar(format[i]);
                    break;
            }
        } else {
            screen_putchar(format[i]);
        }
    }

    __builtin_va_end(args);
}
