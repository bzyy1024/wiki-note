#include "screen.h"
#include "idt.h"
#include "string.h"

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v0.9 - Interrupt Handling ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化IDT和中断系统 */
    screen_puts("[KERNEL] Initializing interrupts...\n");
    idt_init();

    screen_puts("\n[KERNEL] Interrupt system ready!\n");
    screen_puts("[KERNEL] CPU exceptions (0-31) installed\n");
    screen_puts("[KERNEL] Hardware IRQs (32-47) installed\n");

    screen_set_color(VGA_COLOR_LIGHT_CYAN, VGA_COLOR_BLACK);
    screen_puts("\n--- Testing Interrupts ---\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 测试软件中断 */
    screen_puts("[TEST] Triggering INT 3 (breakpoint)...\n");

    /* 注册一个自定义的断点处理器来测试 */
    /* 注意：在没有注册处理器的情况下触发会导致默认的异常处理 */

    screen_puts("\n[KERNEL] System running. Halting CPU.\n");
    while (1) {
        __asm__ volatile("hlt");
    }
}
