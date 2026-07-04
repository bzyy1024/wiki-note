void kernel_main(void) {
    /* VGA文本模式显存起始地址 */
    char *video_memory = (char*)0xB8000;

    /* 清屏 */
    for (int i = 0; i < 80 * 25 * 2; i++) {
        video_memory[i] = 0;
    }

    /* 打印消息 */
    const char *message = "Hello from C kernel!";
    for (int i = 0; message[i] != '\0'; i++) {
        video_memory[i * 2] = message[i];       /* 字符 */
        video_memory[i * 2 + 1] = 0x0F;         /* 属性：白色前景，黑色背景 */
    }

    /* 死循环，防止CPU执行随机内存 */
    while (1) {
        __asm__ volatile("hlt");
    }
}
