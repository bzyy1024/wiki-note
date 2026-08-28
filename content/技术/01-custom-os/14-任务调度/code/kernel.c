#include "screen.h"
#include "idt.h"
#include "keyboard.h"
#include "pmm.h"
#include "vmm.h"
#include "process.h"
#include "timer.h"
#include "scheduler.h"

/* ============================================================
 * 示例任务
 * ============================================================ */

static void task_a(void) {
    int count = 0;
    while (1) {
        screen_set_color(VGA_COLOR_LIGHT_RED, VGA_COLOR_BLACK);
        screen_printf("[A:%d] ", count++);
        screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);
        /* 忙等待，让调度器有机会切换 */
        for (volatile int i = 0; i < 500000; i++);
    }
}

static void task_b(void) {
    int count = 0;
    while (1) {
        screen_set_color(VGA_COLOR_LIGHT_BLUE, VGA_COLOR_BLACK);
        screen_printf("[B:%d] ", count++);
        screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);
        for (volatile int i = 0; i < 500000; i++);
    }
}

static void task_c(void) {
    int count = 0;
    while (1) {
        screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
        screen_printf("[C:%d] ", count++);
        screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);
        for (volatile int i = 0; i < 500000; i++);
    }
}

/* ============================================================
 * 内核主函数
 * ============================================================ */

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v0.14 - Multitasking ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化子系统 */
    idt_init();
    keyboard_init();
    pmm_init(128 * 1024);
    vmm_init();

    /* 初始化进程和调度器 */
    process_init();
    scheduler_init();

    /* 创建任务并加入调度器 */
    process_t *pa = process_create("task_a", task_a);
    process_t *pb = process_create("task_b", task_b);
    process_t *pc = process_create("task_c", task_c);
    scheduler_add(pa);
    scheduler_add(pb);
    scheduler_add(pc);

    /* 显示进程列表 */
    process_list_all();

    screen_puts("\n[KERNEL] Starting timer and scheduler...\n");
    screen_puts("[KERNEL] You should see A, B, C printing alternately:\n\n");

    /* 启动定时器（100Hz，触发调度） */
    timer_init(TIMER_FREQ);

    /* idle循环 */
    while (1) {
        __asm__ volatile("hlt");
    }
}
