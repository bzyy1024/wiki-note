#include "screen.h"
#include "idt.h"
#include "keyboard.h"
#include "pmm.h"
#include "vmm.h"
#include "process.h"
#include "timer.h"
#include "scheduler.h"
#include "tss.h"
#include "syscall.h"
#include "usermode.h"

extern void user_main(void);

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v1.0 - Complete OS Kernel ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化子系统 */
    idt_init();
    keyboard_init();
    pmm_init(128 * 1024);
    vmm_init();
    process_init();
    scheduler_init();

    /* 初始化TSS（使用GDT索引5，内核数据段0x10） */
    uint32_t kernel_stack = (uint32_t)kmalloc_aligned(4096) + 4096;
    tss_init(5, 0x10, kernel_stack);

    /* 初始化系统调用 */
    syscall_init();

    /* 启动定时器 */
    timer_init(100);

    /* 显示系统信息 */
    screen_set_color(VGA_COLOR_LIGHT_CYAN, VGA_COLOR_BLACK);
    screen_puts("\n=== System Ready ===\n");
    screen_printf("Free memory: %d MB\n",
                  pmm_free_frame_count() * 4096 / (1024 * 1024));
    screen_puts("Features: VGA, IDT, PIC, Keyboard, PMM, VMM, Processes,\n");
    screen_puts("          Scheduler, TSS, Syscalls, User Mode\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 注意：完整的用户模式切换需要正确配置GDT（含用户段和TSS段） */
    /* 以下演示在内核态运行user_main（简化版） */
    screen_puts("[KERNEL] Running user program (simplified demo)...\n\n");
    screen_set_color(VGA_COLOR_YELLOW, VGA_COLOR_BLACK);
    user_main();
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("\n=== OS Development Tutorial Complete! ===\n");
    screen_puts("You built an OS kernel from scratch!\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    while (1) {
        __asm__ volatile("hlt");
    }
}
