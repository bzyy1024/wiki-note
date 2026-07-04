#include "screen.h"
#include "idt.h"
#include "keyboard.h"
#include "pmm.h"
#include "vmm.h"
#include "process.h"

/* 示例任务函数 */
static void task_a(void) {
    while (1) {
        screen_puts("[Task A] running\n");
        for (volatile int i = 0; i < 1000000; i++);
    }
}

static void task_b(void) {
    while (1) {
        screen_puts("[Task B] running\n");
        for (volatile int i = 0; i < 1000000; i++);
    }
}

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v0.13 - Process Management ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化子系统 */
    idt_init();
    keyboard_init();
    pmm_init(128 * 1024);
    vmm_init();

    /* 初始化进程管理 */
    process_init();

    /* 创建测试进程 */
    process_create("task_a", task_a);
    process_create("task_b", task_b);

    /* 显示进程列表 */
    process_list_all();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("\n[KERNEL] Process management ready!\n");
    screen_puts("[KERNEL] Next step: implement scheduler (ch14)\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    while (1) {
        __asm__ volatile("hlt");
    }
}
