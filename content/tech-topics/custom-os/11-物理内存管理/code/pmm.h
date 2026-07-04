#ifndef PMM_H
#define PMM_H

#include "types.h"

/* 页帧大小 */
#define PAGE_SIZE       4096
#define PAGE_SHIFT      12

/* 假设128MB物理内存 */
#define TOTAL_MEMORY    (128 * 1024 * 1024)
#define TOTAL_FRAMES    (TOTAL_MEMORY / PAGE_SIZE)
#define BITMAP_SIZE     (TOTAL_FRAMES / 8)

/* 内核堆起始地址（在内核代码之后） */
#define KERNEL_HEAP_START 0x100000

/* 地址与帧号互转 */
#define ADDR_TO_FRAME(addr)  ((uint32_t)(addr) >> PAGE_SHIFT)
#define FRAME_TO_ADDR(frame) ((uint32_t)(frame) << PAGE_SHIFT)

/* 初始化物理内存管理器 */
void pmm_init(uint32_t total_memory_kb);

/* 分配一个页帧，返回物理地址；失败返回0 */
uint32_t pmm_alloc_frame(void);

/* 释放一个页帧 */
void pmm_free_frame(uint32_t phys_addr);

/* 标记地址范围为已使用 */
void pmm_mark_region_used(uint32_t base, uint32_t length);

/* 标记地址范围为可用 */
void pmm_mark_region_free(uint32_t base, uint32_t length);

/* 获取空闲帧数 */
uint32_t pmm_free_frame_count(void);

/* 获取已用帧数 */
uint32_t pmm_used_frame_count(void);

/* 简易kmalloc（bump allocator） */
void *kmalloc(uint32_t size);

/* 页对齐的kmalloc */
void *kmalloc_aligned(uint32_t size);

/* kmalloc并返回物理地址 */
void *kmalloc_ap(uint32_t size, uint32_t *phys);

#endif
