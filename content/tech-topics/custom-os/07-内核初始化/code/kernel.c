#include "types.h"
#include "string.h"

/* 简单的VGA输出（下一章会升级为完整的screen模块） */
static uint16_t *video_memory = (uint16_t*)0xB8000;
static int cursor = 0;

static void kprint(const char *str) {
    for (int i = 0; str[i] != '\0'; i++) {
        if (str[i] == '\n') {
            cursor = (cursor / 80 + 1) * 80;
        } else {
            video_memory[cursor] = (uint16_t)str[i] | (0x0F << 8);
            cursor++;
        }
    }
}

static void clear_screen(void) {
    for (int i = 0; i < 80 * 25; i++) {
        video_memory[i] = (uint16_t)' ' | (0x0F << 8);
    }
    cursor = 0;
}

void kernel_main(void) {
    clear_screen();

    kprint("[KERNEL] MyOS kernel initializing...\n");
    kprint("[KERNEL] Type system ready\n");
    kprint("[KERNEL] String utilities ready\n");

    /* 测试字符串函数 */
    char buf[32];
    memset(buf, 0, sizeof(buf));
    const char *test = "Hello";
    memcpy(buf, test, strlen(test));

    kprint("[KERNEL] Kernel initialization complete\n");
    kprint("\n");
    kprint("System ready.\n");

    while (1) {
        __asm__ volatile("hlt");
    }
}
