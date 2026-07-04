#ifndef VMM_H
#define VMM_H

#include "types.h"

/* 页表项标志 */
#define PAGE_PRESENT    0x001
#define PAGE_WRITABLE   0x002
#define PAGE_USER       0x004
#define PAGE_WRITETHROUGH 0x008
#define PAGE_NOCACHE    0x010
#define PAGE_ACCESSED   0x020
#define PAGE_DIRTY      0x040
#define PAGE_SIZE_4MB   0x080  /* 页目录专用 */

/* 页表大小 */
#define PAGES_PER_TABLE  1024
#define TABLES_PER_DIR   1024
#define PAGE_SIZE        4096

/* 地址操作宏 */
#define PAGE_ALIGN_DOWN(addr) ((addr) & ~0xFFF)
#define PAGE_ALIGN_UP(addr)   (((addr) + 0xFFF) & ~0xFFF)
#define PD_INDEX(addr)        (((uint32_t)(addr) >> 22) & 0x3FF)
#define PT_INDEX(addr)        (((uint32_t)(addr) >> 12) & 0x3FF)

/* 页表 */
typedef struct {
    uint32_t entries[PAGES_PER_TABLE];
} page_table_t;

/* 页目录 */
typedef struct {
    uint32_t entries[TABLES_PER_DIR];        /* 页目录条目 */
    page_table_t *tables[TABLES_PER_DIR];    /* 页表虚拟地址（内核使用） */
    uint32_t physical_addr;                   /* 页目录物理地址 */
} page_directory_t;

/* 初始化虚拟内存管理器 */
void vmm_init(void);

/* 映射虚拟地址到物理地址 */
void vmm_map_page(page_directory_t *dir, uint32_t virt, uint32_t phys, uint32_t flags);

/* 取消映射 */
void vmm_unmap_page(page_directory_t *dir, uint32_t virt);

/* 获取映射的物理地址 */
uint32_t vmm_get_physical(page_directory_t *dir, uint32_t virt);

/* 切换页目录 */
void vmm_switch_directory(page_directory_t *dir);

/* 获取当前页目录 */
page_directory_t *vmm_get_directory(void);

/* 刷新TLB中的一个条目 */
void vmm_flush_tlb(uint32_t virt);

#endif
