#include "screen.h"
#include "idt.h"
#include "keyboard.h"
#include "pmm.h"

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v0.11 - Physical Memory Manager ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化中断 */
    idt_init();
    keyboard_init();

    /* 初始化物理内存管理器 (假设128MB) */
    pmm_init(128 * 1024);

    /* 测试：分配几个页帧 */
    screen_set_color(VGA_COLOR_LIGHT_CYAN, VGA_COLOR_BLACK);
    screen_puts("\n--- PMM Test ---\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    uint32_t frame1 = pmm_alloc_frame();
    uint32_t frame2 = pmm_alloc_frame();
    uint32_t frame3 = pmm_alloc_frame();

    screen_printf("Allocated frame 1: 0x%x\n", frame1);
    screen_printf("Allocated frame 2: 0x%x\n", frame2);
    screen_printf("Allocated frame 3: 0x%x\n", frame3);
    screen_printf("Free frames: %d\n", pmm_free_frame_count());

    /* 释放第二个帧 */
    pmm_free_frame(frame2);
    screen_printf("After freeing frame 2: %d free\n", pmm_free_frame_count());

    /* 重新分配，应该得到刚释放的帧 */
    uint32_t frame4 = pmm_alloc_frame();
    screen_printf("Re-allocated: 0x%x (should be 0x%x)\n", frame4, frame2);

    /* kmalloc 测试 */
    screen_puts("\n--- kmalloc Test ---\n");
    void *ptr1 = kmalloc(64);
    void *ptr2 = kmalloc(128);
    void *ptr3 = kmalloc_aligned(256);
    screen_printf("kmalloc(64)  = 0x%x\n", (uint32_t)ptr1);
    screen_printf("kmalloc(128) = 0x%x\n", (uint32_t)ptr2);
    screen_printf("kmalloc_aligned(256) = 0x%x (page-aligned)\n", (uint32_t)ptr3);

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("\n[KERNEL] Memory management ready!\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    while (1) {
        __asm__ volatile("hlt");
    }
}
