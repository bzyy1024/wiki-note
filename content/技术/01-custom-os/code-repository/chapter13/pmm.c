#include "pmm.h"
#include "string.h"
#include "screen.h"

/* ============================================================
 * 位图
 * ============================================================ */

static uint8_t bitmap[BITMAP_SIZE];
static uint32_t total_frames = 0;
static uint32_t used_frames  = 0;

/* 位图操作 */
static inline void bitmap_set(uint32_t frame) {
    bitmap[frame / 8] |= (1 << (frame % 8));
}

static inline void bitmap_clear(uint32_t frame) {
    bitmap[frame / 8] &= ~(1 << (frame % 8));
}

static inline bool bitmap_test(uint32_t frame) {
    return bitmap[frame / 8] & (1 << (frame % 8));
}

/* 查找第一个空闲帧 */
static uint32_t find_first_free(void) {
    uint32_t bitmap_bytes = total_frames / 8;
    for (uint32_t i = 0; i < bitmap_bytes; i++) {
        if (bitmap[i] != 0xFF) {
            /* 这个字节中有空闲位 */
            for (int j = 0; j < 8; j++) {
                if (!(bitmap[i] & (1 << j))) {
                    return i * 8 + j;
                }
            }
        }
    }
    return (uint32_t)-1;
}

/* ============================================================
 * 公共接口
 * ============================================================ */

void pmm_init(uint32_t total_memory_kb) {
    uint32_t total_memory = total_memory_kb * 1024;
    total_frames = total_memory / PAGE_SIZE;
    used_frames = total_frames; /* 初始全部标记为已使用 */

    /* 初始化位图：全部设为1（已使用） */
    memset(bitmap, 0xFF, BITMAP_SIZE);

    screen_printf("[PMM] Total memory: %d MB (%d frames)\n",
                  total_memory / (1024 * 1024), total_frames);

    /* 标记可用内存区域 */
    /* 跳过低1MB（BIOS、VGA、内核等），从1MB之后开始标记为可用 */
    pmm_mark_region_free(0x100000, total_memory - 0x100000);

    /* 保护位图自身占用的内存 */
    /* 位图放在内核堆中，由kmalloc管理，这里简化处理 */

    screen_printf("[PMM] Free frames: %d (%d MB available)\n",
                  pmm_free_frame_count(),
                  pmm_free_frame_count() * PAGE_SIZE / (1024 * 1024));
}

uint32_t pmm_alloc_frame(void) {
    uint32_t frame = find_first_free();
    if (frame == (uint32_t)-1) {
        screen_puts("[PMM] ERROR: Out of memory!\n");
        return 0;
    }

    bitmap_set(frame);
    used_frames++;
    return FRAME_TO_ADDR(frame);
}

void pmm_free_frame(uint32_t phys_addr) {
    uint32_t frame = ADDR_TO_FRAME(phys_addr);
    if (!bitmap_test(frame)) {
        return; /* 已经是空闲的，双重释放 */
    }
    bitmap_clear(frame);
    used_frames--;
}

void pmm_mark_region_used(uint32_t base, uint32_t length) {
    uint32_t start_frame = ADDR_TO_FRAME(base);
    uint32_t end_frame = ADDR_TO_FRAME(base + length - 1);

    for (uint32_t i = start_frame; i <= end_frame && i < total_frames; i++) {
        if (!bitmap_test(i)) {
            bitmap_set(i);
            used_frames++;
        }
    }
}

void pmm_mark_region_free(uint32_t base, uint32_t length) {
    uint32_t start_frame = ADDR_TO_FRAME(base);
    uint32_t end_frame = ADDR_TO_FRAME(base + length - 1);

    for (uint32_t i = start_frame; i <= end_frame && i < total_frames; i++) {
        if (bitmap_test(i)) {
            bitmap_clear(i);
            used_frames--;
        }
    }
}

uint32_t pmm_free_frame_count(void) {
    return total_frames - used_frames;
}

uint32_t pmm_used_frame_count(void) {
    return used_frames;
}

/* ============================================================
 * 简易 kmalloc（Bump Allocator）
 * ============================================================ */

static uint32_t heap_ptr = KERNEL_HEAP_START;

void *kmalloc(uint32_t size) {
    void *addr = (void *)heap_ptr;
    heap_ptr += size;
    return addr;
}

void *kmalloc_aligned(uint32_t size) {
    /* 对齐到页边界 */
    if (heap_ptr & 0xFFF) {
        heap_ptr = (heap_ptr & ~0xFFF) + PAGE_SIZE;
    }
    void *addr = (void *)heap_ptr;
    heap_ptr += size;
    return addr;
}

void *kmalloc_ap(uint32_t size, uint32_t *phys) {
    if (heap_ptr & 0xFFF) {
        heap_ptr = (heap_ptr & ~0xFFF) + PAGE_SIZE;
    }
    if (phys) {
        *phys = heap_ptr;
    }
    void *addr = (void *)heap_ptr;
    heap_ptr += size;
    return addr;
}
