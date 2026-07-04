#include "screen.h"

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("Welcome to MyOS!\n");

    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);
    screen_puts("Kernel initialized successfully.\n\n");

    /* 测试printf */
    screen_printf("VGA Text Mode: %dx%d\n", VGA_WIDTH, VGA_HEIGHT);
    screen_printf("Video Memory:  %x\n", VGA_MEMORY);

    screen_set_color(VGA_COLOR_YELLOW, VGA_COLOR_BLACK);
    screen_puts("\nSystem ready.\n");

    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    while (1) {
        __asm__ volatile("hlt");
    }
}
