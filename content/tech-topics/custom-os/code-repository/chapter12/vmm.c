#include "vmm.h"
#include "pmm.h"
#include "string.h"
#include "screen.h"
#include "idt.h"

static page_directory_t *current_directory = NULL;
static page_directory_t *kernel_directory  = NULL;

/* ============================================================
 * TLB操作
 * ============================================================ */

void vmm_flush_tlb(uint32_t virt) {
    __asm__ volatile("invlpg (%0)" : : "r"(virt) : "memory");
}

/* ============================================================
 * 页映射
 * ============================================================ */

void vmm_map_page(page_directory_t *dir, uint32_t virt, uint32_t phys, uint32_t flags) {
    uint32_t pd_idx = PD_INDEX(virt);
    uint32_t pt_idx = PT_INDEX(virt);

    /* 如果页表不存在，创建一个 */
    if (!(dir->entries[pd_idx] & PAGE_PRESENT)) {
        page_table_t *new_table = (page_table_t *)kmalloc_aligned(sizeof(page_table_t));
        memset(new_table, 0, sizeof(page_table_t));

        dir->tables[pd_idx] = new_table;
        dir->entries[pd_idx] = (uint32_t)new_table | PAGE_PRESENT | PAGE_WRITABLE | flags;
    }

    /* 设置页表条目 */
    page_table_t *table = dir->tables[pd_idx];
    table->entries[pt_idx] = (phys & 0xFFFFF000) | (flags & 0xFFF) | PAGE_PRESENT;

    vmm_flush_tlb(virt);
}

void vmm_unmap_page(page_directory_t *dir, uint32_t virt) {
    uint32_t pd_idx = PD_INDEX(virt);
    uint32_t pt_idx = PT_INDEX(virt);

    if (!(dir->entries[pd_idx] & PAGE_PRESENT)) {
        return;
    }

    page_table_t *table = dir->tables[pd_idx];
    table->entries[pt_idx] = 0;

    vmm_flush_tlb(virt);
}

uint32_t vmm_get_physical(page_directory_t *dir, uint32_t virt) {
    uint32_t pd_idx = PD_INDEX(virt);
    uint32_t pt_idx = PT_INDEX(virt);

    if (!(dir->entries[pd_idx] & PAGE_PRESENT)) {
        return 0;
    }

    page_table_t *table = dir->tables[pd_idx];
    if (!(table->entries[pt_idx] & PAGE_PRESENT)) {
        return 0;
    }

    return (table->entries[pt_idx] & 0xFFFFF000) + (virt & 0xFFF);
}

/* ============================================================
 * 缺页异常处理
 * ============================================================ */

static void page_fault_handler(registers_t *regs) {
    /* 获取引起异常的地址 */
    uint32_t faulting_addr;
    __asm__ volatile("mov %%cr2, %0" : "=r"(faulting_addr));

    /* 解析错误码 */
    bool present = regs->err_code & 0x1;
    bool write   = regs->err_code & 0x2;
    bool user    = regs->err_code & 0x4;

    screen_set_color(VGA_COLOR_LIGHT_RED, VGA_COLOR_BLACK);
    screen_printf("\n!!! PAGE FAULT !!!\n");
    screen_printf("Address: 0x%x\n", faulting_addr);
    screen_printf("Cause: %s | %s | %s\n",
        present ? "protection-violation" : "not-present",
        write   ? "write" : "read",
        user    ? "user-mode" : "kernel-mode");
    screen_printf("EIP: 0x%x\n", regs->eip);
    screen_set_color(VGA_COLOR_LIGHT_GREY, VGA_COLOR_BLACK);

    /* 暂时挂起 */
    while (1) __asm__ volatile("hlt");
}

/* ============================================================
 * 页目录切换
 * ============================================================ */

void vmm_switch_directory(page_directory_t *dir) {
    current_directory = dir;
    __asm__ volatile("mov %0, %%cr3" : : "r"(dir->physical_addr));
}

page_directory_t *vmm_get_directory(void) {
    return current_directory;
}

/* ============================================================
 * 初始化
 * ============================================================ */

void vmm_init(void) {
    /* 创建内核页目录 */
    kernel_directory = (page_directory_t *)kmalloc_aligned(sizeof(page_directory_t));
    memset(kernel_directory, 0, sizeof(page_directory_t));
    kernel_directory->physical_addr = (uint32_t)kernel_directory;

    /* 恒等映射前4MB（包含内核、VGA、BIOS区域） */
    for (uint32_t addr = 0; addr < 0x400000; addr += PAGE_SIZE) {
        vmm_map_page(kernel_directory, addr, addr, PAGE_WRITABLE);
    }

    /* 注册缺页异常处理器 */
    register_interrupt_handler(14, page_fault_handler);

    /* 启用分页 */
    vmm_switch_directory(kernel_directory);

    uint32_t cr0;
    __asm__ volatile("mov %%cr0, %0" : "=r"(cr0));
    cr0 |= 0x80000000;
    __asm__ volatile("mov %0, %%cr0" : : "r"(cr0));

    screen_puts("[VMM] Paging enabled\n");
    screen_printf("[VMM] Kernel mapped at 0x0-0x400000 (4MB identity map)\n");
}
