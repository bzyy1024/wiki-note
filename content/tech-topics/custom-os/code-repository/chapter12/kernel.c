#include "screen.h"
#include "idt.h"
#include "keyboard.h"
#include "pmm.h"
#include "vmm.h"

void kernel_main(void) {
    screen_init();

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("=== MyOS v0.12 - Virtual Memory ===\n\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 初始化子系统 */
    idt_init();
    keyboard_init();
    pmm_init(128 * 1024);

    /* 初始化虚拟内存（启用分页） */
    vmm_init();

    /* 测试分页 */
    screen_set_color(VGA_COLOR_LIGHT_CYAN, VGA_COLOR_BLACK);
    screen_puts("\n--- Paging Test ---\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 测试1：验证恒等映射 */
    uint32_t phys = vmm_get_physical(vmm_get_directory(), 0xB8000);
    screen_printf("VGA (0xB8000) maps to: 0x%x (should be 0xB8000)\n", phys);

    /* 测试2：映射新页 */
    uint32_t new_frame = pmm_alloc_frame();
    vmm_map_page(vmm_get_directory(), 0x500000, new_frame, PAGE_WRITABLE);
    screen_printf("Mapped virtual 0x500000 -> physical 0x%x\n", new_frame);

    /* 测试3：写入映射的页 */
    uint32_t *test_ptr = (uint32_t *)0x500000;
    *test_ptr = 0xDEADBEEF;
    screen_printf("Wrote 0xDEADBEEF, read back: 0x%x\n", *test_ptr);

    screen_set_color(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK);
    screen_puts("\n[KERNEL] Virtual memory ready!\n");
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    while (1) {
        __asm__ volatile("hlt");
    }
}
