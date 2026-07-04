#include "screen.h"
#include "idt.h"
#include "keyboard.h"

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v0.10 - Keyboard Input ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化中断系统 */
    idt_init();

    /* 初始化键盘驱动 */
    keyboard_init();

    screen_set_color(VGA_COLOR_LIGHT_CYAN, VGA_COLOR_BLACK);
    screen_puts("\nType something! Your input will be echoed:\n");
    screen_set_color(VGA_COLOR_WHITE, VGA_COLOR_BLACK);
    screen_puts("> ");

    /* 主循环 */
    while (1) {
        __asm__ volatile("hlt");
    }
}
